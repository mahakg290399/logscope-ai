"""SQLite Async Storage Layer with WAL mode and repository functions."""

import json
import logging
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import AsyncGenerator, List, Optional, Dict, Any, Tuple
import aiosqlite
from logscope.models import (
    SourceConfig, TemplateRecord, TemplateBucket, AnomalyRecord,
    AIAnalysisResult, FeedbackRecord, SanitizedObservation, AnomalyStatus
)

logger = logging.getLogger(__name__)


def _adapt_datetime_iso(val: datetime) -> str:
    return val.isoformat()


sqlite3.register_adapter(datetime, _adapt_datetime_iso)


def _json_loads_safe(val: Any, default: Any = None) -> Any:
    """Safely deserializes a JSON string, returning `default` on error or empty input."""
    if val is None or val == "":
        return default
    if isinstance(val, (dict, list)):
        return val
    try:
        return json.loads(val)
    except (TypeError, json.JSONDecodeError, ValueError):
        return default


def _hydrate_dict_json_fields(data: Dict[str, Any], fields: Tuple[str, ...]) -> Dict[str, Any]:
    """In-place hydrates string JSON columns in a dictionary into native Python structures."""
    for field in fields:
        if field in data and data[field] is not None:
            data[field] = _json_loads_safe(data[field], default=[])
    return data


ANOMALY_JSON_FIELDS: Tuple[str, ...] = (
    "sample_evidence",
    "source_paths",
    "related_template_ids",
    "evidence_references",
    "recommended_actions",
    "possible_causes",
    "evidence",
)


def _row_to_template(row: aiosqlite.Row) -> TemplateRecord:
    """Converts a database row to a validated TemplateRecord."""
    return TemplateRecord(
        id=row["id"],
        application=row["application"],
        environment=row["environment"],
        template_pattern=row["template_pattern"],
        first_seen=datetime.fromisoformat(str(row["first_seen"])),
        last_seen=datetime.fromisoformat(str(row["last_seen"])),
        total_count=row["total_count"],
        sample_message=row["sample_message"],
    )



SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA busy_timeout = 5000;

CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    application TEXT NOT NULL,
    environment TEXT NOT NULL,
    path TEXT NOT NULL,
    format TEXT NOT NULL DEFAULT 'auto',
    enabled INTEGER NOT NULL DEFAULT 1,
    last_seen TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS templates (
    id TEXT PRIMARY KEY,
    application TEXT NOT NULL,
    environment TEXT NOT NULL,
    template_pattern TEXT NOT NULL,
    first_seen TIMESTAMP NOT NULL,
    last_seen TIMESTAMP NOT NULL,
    total_count INTEGER NOT NULL DEFAULT 0,
    sample_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_templates_app_env ON templates(application, environment);

CREATE TABLE IF NOT EXISTS template_buckets (
    id TEXT PRIMARY KEY,
    template_id TEXT NOT NULL,
    application TEXT NOT NULL,
    environment TEXT NOT NULL,
    bucket_start TIMESTAMP NOT NULL,
    bucket_end TIMESTAMP NOT NULL,
    count INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    sample_hashes TEXT, -- JSON array
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(template_id) REFERENCES templates(id)
);

CREATE INDEX IF NOT EXISTS idx_buckets_template_time ON template_buckets(template_id, bucket_start);
CREATE INDEX IF NOT EXISTS idx_buckets_app_env ON template_buckets(application, environment, bucket_start);

CREATE TABLE IF NOT EXISTS samples (
    sample_hash TEXT PRIMARY KEY,
    template_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    application TEXT NOT NULL,
    environment TEXT NOT NULL,
    sanitized_message TEXT NOT NULL,
    level TEXT NOT NULL,
    timestamp TIMESTAMP NOT NULL,
    line_number INTEGER,
    source_path TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP NOT NULL,
    FOREIGN KEY(template_id) REFERENCES templates(id)
);

CREATE INDEX IF NOT EXISTS idx_samples_template ON samples(template_id);
CREATE INDEX IF NOT EXISTS idx_samples_expires ON samples(expires_at);

CREATE TABLE IF NOT EXISTS anomalies (
    id TEXT PRIMARY KEY,
    incident_number TEXT UNIQUE,
    application TEXT NOT NULL,
    environment TEXT NOT NULL,
    template_id TEXT NOT NULL,
    anomaly_type TEXT NOT NULL,
    detected_at TIMESTAMP NOT NULL,
    bucket_start TIMESTAMP NOT NULL,
    current_count INTEGER NOT NULL,
    baseline_count REAL NOT NULL DEFAULT 0.0,
    z_score REAL,
    status TEXT NOT NULL DEFAULT 'active',
    template_text TEXT NOT NULL,
    sample_evidence TEXT, -- JSON array
    source_paths TEXT, -- JSON array
    expires_at TIMESTAMP,
    FOREIGN KEY(template_id) REFERENCES templates(id)
);

CREATE INDEX IF NOT EXISTS idx_anomalies_status ON anomalies(status, detected_at);
CREATE INDEX IF NOT EXISTS idx_anomalies_app_env ON anomalies(application, environment);

CREATE TABLE IF NOT EXISTS ai_analyses (
    id TEXT PRIMARY KEY,
    anomaly_id TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    severity TEXT NOT NULL,
    confidence TEXT NOT NULL,
    summary TEXT NOT NULL,
    evidence TEXT, -- JSON array
    possible_causes TEXT, -- JSON array
    recommended_actions TEXT, -- JSON array
    limitations TEXT,
    raw_response TEXT,
    error TEXT,
    is_retryable INTEGER NOT NULL DEFAULT 0,
    execution_time_ms INTEGER NOT NULL DEFAULT 0,
    investigate INTEGER NOT NULL DEFAULT 1,
    expires_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(anomaly_id) REFERENCES anomalies(id)
);

CREATE INDEX IF NOT EXISTS idx_ai_analyses_anomaly ON ai_analyses(anomaly_id);

CREATE TABLE IF NOT EXISTS feedback (
    id TEXT PRIMARY KEY,
    anomaly_id TEXT NOT NULL,
    action TEXT NOT NULL,
    comment TEXT,
    previous_severity TEXT,
    previous_confidence TEXT,
    new_severity TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(anomaly_id) REFERENCES anomalies(id)
);

CREATE TABLE IF NOT EXISTS processing_checkpoints (
    source_id TEXT NOT NULL,
    file_path TEXT NOT NULL,
    offset INTEGER NOT NULL DEFAULT 0,
    line_number INTEGER NOT NULL DEFAULT 0,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(source_id, file_path)
);

CREATE TABLE IF NOT EXISTS embedding_records (
    id TEXT PRIMARY KEY,
    template_id TEXT,
    anomaly_id TEXT,
    embedding_json TEXT NOT NULL, -- JSON array of floats
    text_content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS retention_runs (
    id TEXT PRIMARY KEY,
    run_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    samples_deleted INTEGER NOT NULL DEFAULT 0,
    buckets_deleted INTEGER NOT NULL DEFAULT 0,
    anomalies_deleted INTEGER NOT NULL DEFAULT 0,
    analyses_deleted INTEGER NOT NULL DEFAULT 0,
    embeddings_deleted INTEGER NOT NULL DEFAULT 0,
    templates_deleted INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'completed'
);
"""


class Database:
    """Async Database wrapper managing SQLite with connection pool & transactions."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._initialized = False

    async def initialize(self):
        """Creates parent directories, applies schema, and sets WAL mode."""
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            async with aiosqlite.connect(self.db_path) as db:
                await db.executescript(SCHEMA_SQL)
                await self._apply_compatible_migrations(db)
                await db.commit()
            self._initialized = True
            logger.info("[Database:SQLite] Successfully initialized database at %s with WAL mode", self.db_path)
        except Exception as e:
            logger.error("[Database:SQLite] Failed to initialize SQLite database at %s: %s", self.db_path, e, exc_info=True)
            raise

    async def _apply_compatible_migrations(self, db: aiosqlite.Connection) -> None:
        """Additive migrations keep existing local POC databases usable."""
        migrations = {
            "anomalies": {
                "incident_number": "TEXT",
                "related_template_ids": "TEXT",
                "evidence_references": "TEXT",
                "detector_version": "TEXT NOT NULL DEFAULT 'v1'",
                "data_loss_warning": "INTEGER NOT NULL DEFAULT 0",
            },
            "ai_analyses": {
                "investigate": "INTEGER NOT NULL DEFAULT 1",
                "expires_at": "TIMESTAMP",
            },
            "retention_runs": {
                "analyses_deleted": "INTEGER NOT NULL DEFAULT 0",
                "embeddings_deleted": "INTEGER NOT NULL DEFAULT 0",
                "templates_deleted": "INTEGER NOT NULL DEFAULT 0",
            },
        }
        for table, columns in migrations.items():
            cursor = await db.execute(f"PRAGMA table_info({table})")
            existing = {row[1] for row in await cursor.fetchall()}
            for name, definition in columns.items():
                if name not in existing:
                    await db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
            if table == "anomalies" and "incident_number" not in existing:
                cursor = await db.execute(
                    "SELECT rowid, id FROM anomalies WHERE incident_number IS NULL ORDER BY rowid"
                )
                for sequence, row in enumerate(await cursor.fetchall(), start=1):
                    await db.execute(
                        "UPDATE anomalies SET incident_number = ? WHERE rowid = ?",
                        (f"INC{sequence:07d}", row[0]),
                    )
        await db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_anomalies_incident_number ON anomalies(incident_number)"
        )

    @asynccontextmanager
    async def get_connection(self) -> AsyncGenerator[aiosqlite.Connection, None]:
        if not self._initialized:
            await self.initialize()
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            await conn.execute("PRAGMA busy_timeout = 5000;")
            yield conn

    # --- Sources ---
    async def upsert_source(self, source: SourceConfig, last_seen: Optional[datetime] = None):
        async with self.get_connection() as db:
            await db.execute(
                """
                INSERT INTO sources (id, application, environment, path, format, enabled, last_seen)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    application=excluded.application,
                    environment=excluded.environment,
                    path=excluded.path,
                    format=excluded.format,
                    enabled=excluded.enabled,
                    last_seen=COALESCE(excluded.last_seen, sources.last_seen)
                """,
                (source.id, source.application, source.environment, source.path,
                 source.format, 1 if source.enabled else 0, last_seen)
            )
            await db.commit()

    async def get_all_sources(self) -> List[Dict[str, Any]]:
        async with self.get_connection() as db:
            async with db.execute("SELECT * FROM sources ORDER BY id") as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    # --- File processing checkpoints ---
    async def save_checkpoint(self, source_id: str, file_path: str, offset: int, line_number: int) -> None:
        async with self.get_connection() as db:
            await db.execute(
                """
                INSERT INTO processing_checkpoints (source_id, file_path, offset, line_number, last_updated)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(source_id, file_path) DO UPDATE SET
                    offset=excluded.offset,
                    line_number=excluded.line_number,
                    last_updated=CURRENT_TIMESTAMP
                """,
                (source_id, file_path, offset, line_number),
            )
            await db.commit()

    async def get_checkpoints(self, source_id: str) -> List[Dict[str, Any]]:
        async with self.get_connection() as db:
            async with db.execute(
                "SELECT source_id, file_path, offset, line_number FROM processing_checkpoints WHERE source_id = ?",
                (source_id,),
            ) as cursor:
                return [dict(row) for row in await cursor.fetchall()]

    # --- Templates ---
    async def upsert_template(self, template: TemplateRecord):
        async with self.get_connection() as db:
            await db.execute(
                """
                INSERT INTO templates (id, application, environment, template_pattern, first_seen, last_seen, total_count, sample_message)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    last_seen = excluded.last_seen,
                    total_count = templates.total_count + excluded.total_count,
                    sample_message = COALESCE(templates.sample_message, excluded.sample_message)
                """,
                (template.id, template.application, template.environment, template.template_pattern,
                 template.first_seen, template.last_seen, template.total_count, template.sample_message)
            )
            await db.commit()

    async def get_template(self, template_id: str) -> Optional[TemplateRecord]:
        async with self.get_connection() as db:
            async with db.execute("SELECT * FROM templates WHERE id = ?", (template_id,)) as cursor:
                row = await cursor.fetchone()
                return _row_to_template(row) if row else None

    async def get_all_templates(self, limit: int = 100) -> List[Dict[str, Any]]:
        async with self.get_connection() as db:
            async with db.execute("SELECT * FROM templates ORDER BY total_count DESC LIMIT ?", (limit,)) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    # --- Buckets ---
    async def record_bucket_counts(self, buckets: List[TemplateBucket]):
        if not buckets:
            return
        params = [
            (
                b.id, b.template_id, b.application, b.environment, b.bucket_start,
                b.bucket_end, b.count, b.error_count, json.dumps(b.sample_hashes)
            )
            for b in buckets
        ]
        async with self.get_connection() as db:
            await db.executemany(
                """
                INSERT INTO template_buckets (id, template_id, application, environment, bucket_start, bucket_end, count, error_count, sample_hashes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    count = template_buckets.count + excluded.count,
                    error_count = template_buckets.error_count + excluded.error_count,
                    sample_hashes = excluded.sample_hashes
                """,
                params
            )
            await db.commit()


    async def get_template_history(self, template_id: str, limit_buckets: int = 12) -> List[Dict[str, Any]]:
        async with self.get_connection() as db:
            async with db.execute(
                """
                SELECT * FROM template_buckets
                WHERE template_id = ?
                ORDER BY bucket_start DESC
                LIMIT ?
                """,
                (template_id, limit_buckets)
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def get_recent_bucket_timeline(self, limit: int = 30) -> List[Dict[str, Any]]:
        """Return aggregated 5-minute bucket timeline for volume charts."""
        async with self.get_connection() as db:
            async with db.execute(
                """
                SELECT 
                    bucket_start,
                    bucket_end,
                    application,
                    SUM(count) as total_count,
                    SUM(error_count) as total_error_count
                FROM template_buckets
                GROUP BY bucket_start, application
                ORDER BY bucket_start DESC
                LIMIT ?
                """,
                (limit,)
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    # --- Samples (Bounded 24h) ---
    async def save_sample(self, obs: SanitizedObservation, retention_hours: int = 24):
        expires_at = datetime.now(timezone.utc) + timedelta(hours=retention_hours)
        async with self.get_connection() as db:
            await db.execute(
                """
                INSERT INTO samples (sample_hash, template_id, source_id, application, environment, sanitized_message, level, timestamp, line_number, source_path, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(sample_hash) DO NOTHING
                """,
                (obs.sample_hash, obs.template_id, obs.source_id, obs.application,
                 obs.environment, obs.sanitized_message, str(obs.level.value),
                 obs.timestamp, obs.line_number, obs.source_path, expires_at)
            )
            await db.commit()

    async def get_samples_for_template(self, template_id: str, limit: int = 5) -> List[Dict[str, Any]]:
        async with self.get_connection() as db:
            async with db.execute(
                """
                SELECT * FROM samples
                WHERE template_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (template_id, limit)
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    # --- Anomalies ---
    async def insert_anomaly(self, anomaly: AnomalyRecord):
        async with self.get_connection() as db:
            await db.execute(
                """
                INSERT INTO anomalies (id, incident_number, application, environment, template_id, anomaly_type, detected_at, bucket_start, current_count, baseline_count, z_score, status, template_text, sample_evidence, source_paths, related_template_ids, evidence_references, detector_version, data_loss_warning)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (anomaly.id, anomaly.incident_number, anomaly.application, anomaly.environment, anomaly.template_id,
                 anomaly.anomaly_type.value, anomaly.detected_at, anomaly.bucket_start,
                 anomaly.current_count, anomaly.baseline_count, anomaly.z_score,
                 anomaly.status.value, anomaly.template_text,
                 # Redacted samples are retained only in `samples` for 24h.
                 # Long-lived anomaly records keep trace references instead.
                 json.dumps([]), json.dumps(anomaly.source_paths),
                 json.dumps(anomaly.related_template_ids), json.dumps(anomaly.evidence_references),
                 anomaly.detector_version, 1 if anomaly.data_loss_warning else 0)
            )
            await db.commit()

    async def update_anomaly_status(self, anomaly_id: str, status: AnomalyStatus):
        async with self.get_connection() as db:
            await db.execute(
                "UPDATE anomalies SET status = ? WHERE id = ?",
                (status.value, anomaly_id)
            )
            await db.commit()

    async def get_active_anomalies(self) -> List[Dict[str, Any]]:
        async with self.get_connection() as db:
            async with db.execute(
                """
                SELECT a.*, ai.severity, ai.confidence, ai.investigate, ai.summary, ai.recommended_actions, ai.possible_causes, ai.error AS ai_error, ai.is_retryable
                FROM anomalies a
                LEFT JOIN ai_analyses ai ON a.id = ai.anomaly_id
                WHERE a.status IN ('active', 'analyzing', 'analyzed', 'failed')
                ORDER BY a.detected_at DESC
                """
            ) as cursor:
                rows = await cursor.fetchall()
                return [_hydrate_dict_json_fields(dict(r), ANOMALY_JSON_FIELDS) for r in rows]

    async def get_dismissed_anomalies(self, limit: int = 50) -> List[Dict[str, Any]]:
        async with self.get_connection() as db:
            async with db.execute(
                """
                SELECT a.*, f.comment as dismissal_comment, f.action as dismissal_action, f.created_at as dismissed_at,
                ai.summary, ai.severity, ai.confidence, ai.investigate,
                ai.recommended_actions, ai.possible_causes, ai.evidence,
                ai.error AS ai_error, ai.is_retryable
                FROM anomalies a
                LEFT JOIN feedback f ON a.id = f.anomaly_id
                LEFT JOIN ai_analyses ai ON a.id = ai.anomaly_id
                WHERE a.status = 'dismissed'
                ORDER BY a.detected_at DESC
                LIMIT ?
                """,
                (limit,)
            ) as cursor:
                rows = await cursor.fetchall()
                return [_hydrate_dict_json_fields(dict(r), ANOMALY_JSON_FIELDS) for r in rows]

    async def get_anomaly(self, anomaly_id: str) -> Optional[Dict[str, Any]]:
        async with self.get_connection() as db:
            async with db.execute("SELECT * FROM anomalies WHERE id = ?", (anomaly_id,)) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def get_anomaly_record(self, anomaly_id: str) -> Optional[AnomalyRecord]:
        """Fetch an anomaly from SQLite and return a fully hydrated AnomalyRecord domain model."""
        raw = await self.get_anomaly(anomaly_id)
        if not raw:
            return None
        _hydrate_dict_json_fields(raw, ANOMALY_JSON_FIELDS)
        return AnomalyRecord.model_validate(raw)


    # --- AI Analyses ---
    async def insert_ai_analysis(self, analysis: AIAnalysisResult):
        async with self.get_connection() as db:
            await db.execute(
                """
                INSERT INTO ai_analyses (id, anomaly_id, model, prompt_version, severity, confidence, summary, evidence, possible_causes, recommended_actions, limitations, raw_response, error, is_retryable, execution_time_ms, investigate)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    severity = excluded.severity,
                    confidence = excluded.confidence,
                    summary = excluded.summary,
                    evidence = excluded.evidence,
                    possible_causes = excluded.possible_causes,
                    recommended_actions = excluded.recommended_actions,
                    limitations = excluded.limitations,
                    raw_response = excluded.raw_response,
                    error = excluded.error,
                    is_retryable = excluded.is_retryable,
                    execution_time_ms = excluded.execution_time_ms,
                    investigate = excluded.investigate
                """,
                (analysis.id, analysis.anomaly_id, analysis.model, analysis.prompt_version,
                 analysis.severity.value, analysis.confidence.value, analysis.summary,
                 json.dumps(analysis.evidence), json.dumps(analysis.possible_causes),
                 json.dumps(analysis.recommended_actions), json.dumps(analysis.limitations),
                  # Do not retain unrestricted model output: it can repeat a
                  # redacted sample and outlive the sample-retention boundary.
                  None, analysis.error, 1 if analysis.is_retryable else 0,
                 analysis.execution_time_ms, 1 if analysis.investigate else 0)
            )
            await db.commit()

    # --- User Feedback ---
    async def insert_feedback(self, fb: FeedbackRecord):
        async with self.get_connection() as db:
            await db.execute(
                """
                INSERT INTO feedback (id, anomaly_id, action, comment, previous_severity, previous_confidence, new_severity)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (fb.id, fb.anomaly_id, fb.action, fb.comment, fb.previous_severity,
                 fb.previous_confidence, fb.new_severity)
            )
            # If action closes/resolves the incident, update anomaly status
            if fb.action.lower() in ("dismiss", "dismissed", "resolve", "resolved", "false_positive", "transient"):
                await db.execute("UPDATE anomalies SET status = 'dismissed' WHERE id = ?", (fb.anomaly_id,))
            await db.commit()

    async def get_recent_feedback(self, limit: int = 10) -> List[Dict[str, Any]]:
        async with self.get_connection() as db:
            async with db.execute("SELECT * FROM feedback ORDER BY created_at DESC LIMIT ?", (limit,)) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    # --- Retention Cleanups ---
    async def run_retention_cleanup(self, sample_retention_hours: int = 24, aggregate_retention_months: int = 6) -> Dict[str, int]:
        now = datetime.now(timezone.utc)
        sample_cutoff = now - timedelta(hours=sample_retention_hours)
        aggregate_cutoff = now - timedelta(days=aggregate_retention_months * 30)

        logger.info("[Database:Retention] Running retention cleanup (sample_hours=%d, aggregate_months=%d)...", sample_retention_hours, aggregate_retention_months)
        async with self.get_connection() as db:
            # Delete expired samples
            cursor1 = await db.execute("DELETE FROM samples WHERE expires_at < ? OR created_at < ?", (now, sample_cutoff))
            samples_deleted = cursor1.rowcount

            # Redacted evidence must not outlive the 24-hour sample window.
            await db.execute(
                "UPDATE anomalies SET sample_evidence = '[]' WHERE detected_at < ? AND sample_evidence != '[]'",
                (sample_cutoff,),
            )
            await db.execute(
                "UPDATE ai_analyses SET raw_response = NULL WHERE created_at < ? AND raw_response IS NOT NULL",
                (sample_cutoff,),
            )

            # Delete all retained observability data beyond the six-month POC horizon.
            cursor_ai = await db.execute("DELETE FROM ai_analyses WHERE created_at < ?", (aggregate_cutoff,))
            analyses_deleted = cursor_ai.rowcount

            cursor_feedback = await db.execute("DELETE FROM feedback WHERE created_at < ?", (aggregate_cutoff,))
            feedback_deleted = cursor_feedback.rowcount

            cursor_embeddings = await db.execute(
                "DELETE FROM embedding_records WHERE created_at < ? OR (expires_at IS NOT NULL AND expires_at < ?)",
                (aggregate_cutoff, now),
            )
            embeddings_deleted = cursor_embeddings.rowcount

            cursor_anomalies = await db.execute("DELETE FROM anomalies WHERE detected_at < ?", (aggregate_cutoff,))
            anomalies_deleted = cursor_anomalies.rowcount

            cursor2 = await db.execute("DELETE FROM template_buckets WHERE bucket_end < ?", (aggregate_cutoff,))
            buckets_deleted = cursor2.rowcount

            cursor_templates = await db.execute("DELETE FROM templates WHERE last_seen < ?", (aggregate_cutoff,))
            templates_deleted = cursor_templates.rowcount

            logger.info(
                "[Database:Retention] Cleanup completed: deleted %d samples, %d analyses, %d embeddings, %d anomalies, %d buckets, %d templates",
                samples_deleted, analyses_deleted, embeddings_deleted, anomalies_deleted, buckets_deleted, templates_deleted
            )

            # Log retention run
            import uuid
            run_id = str(uuid.uuid4())
            await db.execute(
                """
                INSERT INTO retention_runs (
                    id, samples_deleted, buckets_deleted, anomalies_deleted,
                    analyses_deleted, embeddings_deleted, templates_deleted, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id, samples_deleted, buckets_deleted, anomalies_deleted,
                    analyses_deleted, embeddings_deleted, templates_deleted, "completed",
                )
            )
            await db.commit()

            return {
                "samples_deleted": samples_deleted,
                "buckets_deleted": buckets_deleted,
                "anomalies_deleted": anomalies_deleted,
                "analyses_deleted": analyses_deleted,
                "embeddings_deleted": embeddings_deleted,
                "templates_deleted": templates_deleted,
                "feedback_deleted": feedback_deleted,
            }
