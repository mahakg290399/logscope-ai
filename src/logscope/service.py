"""Unified LogScope Orchestration Service."""

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from logscope.config import Settings
from logscope.models import (
    SourceConfig, SanitizedObservation, AnomalyRecord, AnomalyStatus, TelemetryMetrics, LogLevel
)
from logscope.sanitizer import Redactor
from logscope.ingestion.parser import LogParser
from logscope.ingestion.tailer import FileTailer
from logscope.templates.engine import Drain3Engine
from logscope.storage.db import Database
from logscope.storage.vector_index import LocalVectorIndex
from logscope.kafka.streaming import KafkaStreamManager
from logscope.aggregator.aggregator import BucketAggregator, get_bucket_window
from logscope.anomaly.detector import AnomalyDetector
from logscope.ai.worker import AIAnalysisWorker

logger = logging.getLogger(__name__)


class LogScopeService:
    """End-to-end LogScope Engine orchestrating ingestion, sanitization, aggregation, anomalies, and AI."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.db = Database(settings.db_path)
        self.vector_index = LocalVectorIndex(self.db)
        self.redactor = Redactor()
        self._default_parser = LogParser()
        self.drain_engines: Dict[tuple[str, str], Drain3Engine] = {}
        self.stream_manager = KafkaStreamManager(settings)
        self.aggregator = BucketAggregator(self.db)
        self.anomaly_detector = AnomalyDetector(self.db, settings)
        self.ai_worker = AIAnalysisWorker(settings, self.db, self.vector_index, self.stream_manager)
        
        self.sources: List[SourceConfig] = []
        self.tailers: Dict[str, FileTailer] = {}
        self._observed_templates: set[str] = set()
        self._last_source_update: Dict[str, float] = {}
        
        # Telemetry metrics
        self.total_lines_read = 0
        self.parsing_warnings_count = 0
        self.openai_error_count = 0
        self._start_time = time.time()
        self._is_running = False
        self._tasks: List[asyncio.Task] = []
        self._pending_ai_batches: Dict[tuple[str, str], List[AnomalyRecord]] = {}
        self._ai_batch_lock = asyncio.Lock()

    async def start(self):
        """Initializes databases, Kafka streaming, and launches background worker tasks."""
        if self._is_running:
            return
        self._is_running = True

        logger.info("Initializing LogScope AI Service...")
        await self.db.initialize()
        await self.db.run_retention_cleanup(
            sample_retention_hours=self.settings.sample_retention_hours,
            aggregate_retention_months=self.settings.aggregate_retention_months,
        )
        await self.stream_manager.initialize()

        # Load sources from config if not already provided
        if not self.sources:
            self.sources = self.settings.get_sources()
        for src in self.sources:
            await self.db.upsert_source(src)
            if src.enabled:
                tailer = FileTailer(src)
                for checkpoint in await self.db.get_checkpoints(src.id):
                    tailer.restore_checkpoint(
                        checkpoint["file_path"],
                        checkpoint["offset"],
                        checkpoint["line_number"],
                    )
                self.tailers[src.id] = tailer

        # Launch workers
        self._tasks.append(asyncio.create_task(self._tailer_loop()))
        self._tasks.append(asyncio.create_task(self.stream_manager.consume_observations(self._handle_observation)))
        self._tasks.append(asyncio.create_task(self.stream_manager.consume_anomalies(self._handle_anomaly)))
        if self.settings.kafka_topic_raw_logs or self.settings.kafka_embedded_fallback:
            self._tasks.append(asyncio.create_task(self.stream_manager.consume_raw_logs(self._handle_raw_kafka_log)))
        self._tasks.append(asyncio.create_task(self._periodic_ai_batch_loop()))
        self._tasks.append(asyncio.create_task(self._periodic_flush_loop()))
        self._tasks.append(asyncio.create_task(self._periodic_retention_loop()))

        logger.info("LogScope AI Service started successfully.")

    async def stop(self):
        """Gracefully shuts down all workers and flushes remaining buffers."""
        self._is_running = False
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        await self._flush_ai_batches()

        await self.aggregator.flush_all()
        await self.stream_manager.stop()
        logger.info("LogScope AI Service stopped.")

    def _build_sanitized_observation(
        self,
        raw_line: str,
        line_num: int,
        file_path: str,
        src_config: SourceConfig,
    ) -> SanitizedObservation:
        """Parses, redacts PII/secrets, clusters with Drain3, and builds a SanitizedObservation."""
        # 1. Parse line
        tailer = self.tailers.get(src_config.id)
        parser = tailer.parser if tailer else self._default_parser
        parsed = parser.parse_record(raw_line, line_num, file_path)

        # 2. Sanitize & Redact PII / Secrets (BEFORE Kafka)
        sanitized_msg, redacted_types = self.redactor.sanitize(parsed.message)
        sanitized_metadata, client_id_hash = self.redactor.sanitize_attributes(parsed.attributes)
        for key in ("service", "host", "container", "source_name"):
            configured_value = getattr(src_config, key, None)
            if configured_value and key not in sanitized_metadata:
                sanitized_metadata[key] = configured_value
        sample_hash = self.redactor.compute_sample_hash(sanitized_msg)

        # 3. Drain3 Template Mining
        engine_key = (src_config.application, src_config.environment)
        drain_engine = self.drain_engines.setdefault(engine_key, Drain3Engine())
        tmpl_id, tmpl_text, params, _ = drain_engine.extract_template(
            sanitized_msg,
            application=src_config.application,
            environment=src_config.environment,
        )

        event_ts = parsed.timestamp or datetime.now(timezone.utc)

        # 4. Construct SanitizedObservation
        return SanitizedObservation(
            source_id=src_config.id,
            application=src_config.application,
            environment=src_config.environment,
            template_id=tmpl_id,
            template_text=tmpl_text,
            sanitized_message=sanitized_msg,
            level=parsed.level,
            timestamp=event_ts,
            source_path=file_path,
            line_number=line_num,
            parameters=params,
            sample_hash=sample_hash,
            client_id_hash=client_id_hash,
            metadata=sanitized_metadata,
            redaction_types=redacted_types,
        )

    async def _update_source_heartbeat(self, src_config: SourceConfig, event_ts: datetime) -> None:
        """Updates source last_seen timestamp in DB, throttled to at most once every 2 seconds."""
        now_ts = time.time()
        if now_ts - self._last_source_update.get(src_config.id, 0.0) >= 2.0:
            self._last_source_update[src_config.id] = now_ts
            await self.db.upsert_source(src_config, last_seen=event_ts)

    async def process_raw_line(self, raw_line: str, line_num: int, file_path: str, src_config: SourceConfig):
        """Pre-Kafka processing boundary: Redaction -> Drain3 -> Sanitized Observation -> Kafka."""
        self.total_lines_read += 1
        obs = self._build_sanitized_observation(raw_line, line_num, file_path, src_config)
        await self.stream_manager.publish_observation(obs)
        await self._update_source_heartbeat(src_config, obs.timestamp)

    async def _handle_raw_kafka_log(self, raw_line: str, metadata: Dict[str, Any]) -> None:
        """Processes raw lines received directly from an external Kafka topic."""
        app = metadata.get("application") or metadata.get("app") or "kafka-raw"
        env = metadata.get("environment") or metadata.get("env") or self.settings.env
        source_name = metadata.get("source_name") or metadata.get("tag") or "kafka-stream"
        raw_topic = self.settings.kafka_topic_raw_logs or "raw_logs"
        await self.ingest_lines(
            application=str(app),
            environment=str(env),
            lines=[raw_line],
            source_name=str(source_name),
            source_path=f"kafka://{raw_topic}",
        )

    async def ingest_lines(
        self,
        application: str,
        environment: str,
        lines: List[Any],
        source_name: str = "http-ingest",
        source_path: str = "http://api/logs/ingest",
    ) -> int:
        """Processes a batch of raw log lines received over the network/HTTP API or Kafka."""
        src_id = f"ingest-{application}-{environment}"
        src_config = SourceConfig(
            id=src_id,
            application=application,
            environment=environment,
            path=source_path,
            source_name=source_name,
            enabled=True,
        )
        ingested = 0
        for idx, line in enumerate(lines, start=1):
            if line is None:
                continue
            line_str = json.dumps(line) if isinstance(line, (dict, list)) else str(line)
            if not line_str.strip():
                continue
            await self.process_raw_line(line_str, idx, source_path, src_config)
            ingested += 1
        return ingested

    async def _tailer_loop(self):
        """Continuously reads from active file tailers."""
        while self._is_running:
            lines_read = 0
            try:
                for src_id, tailer in list(self.tailers.items()):
                    async for assembled_line, line_num, file_path in tailer.read_new_lines():
                        await self.process_raw_line(assembled_line, line_num, file_path, tailer.config)
                        lines_read += 1
                    for state in tailer.files_state.values():
                        await self.db.save_checkpoint(
                            tailer.config.id,
                            state.file_path,
                            state.offset,
                            state.line_number,
                        )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in tailer loop: %s", e)
            if lines_read == 0:
                await asyncio.sleep(0.05)
            else:
                await asyncio.sleep(0.001)

    async def _is_template_novel(self, template_id: str) -> bool:
        """Check template novelty using in-memory cache and DB fallback."""
        if template_id in self._observed_templates:
            return False
        tmpl_in_db = await self.db.get_template(template_id)
        is_new = tmpl_in_db is None or tmpl_in_db.total_count <= 1
        self._observed_templates.add(template_id)
        return is_new

    async def _handle_observation(self, obs: SanitizedObservation) -> None:
        """Consume one sanitized Kafka observation into aggregation and detection."""
        await self.aggregator.ingest_observation(obs)
        bucket_start, _ = get_bucket_window(obs.timestamp)
        key = (obs.template_id, bucket_start)
        curr_count = self.aggregator.active_buckets[key].count if key in self.aggregator.active_buckets else 1

        is_new = await self._is_template_novel(obs.template_id)

        anomaly = await self.anomaly_detector.evaluate_observation(
            obs,
            is_new_template=is_new,
            current_bucket_count=curr_count,
            bucket_start=bucket_start,
        )
        if anomaly:
            await self.stream_manager.publish_anomaly_job(anomaly)

    async def _handle_anomaly(self, anomaly: AnomalyRecord) -> None:
        """Stage an anomaly for the configurable same-app/environment AI batch."""
        key = (anomaly.application, anomaly.environment)
        async with self._ai_batch_lock:
            pending = self._pending_ai_batches.setdefault(key, [])
            if len(pending) >= self.settings.ai_max_batch_size:
                self.openai_error_count += 1
                logger.error("AI batch queue is full for %s/%s; anomaly %s remains retryable", *key, anomaly.id)
                await self.db.update_anomaly_status(anomaly.id, AnomalyStatus.FAILED)
                return
            pending.append(anomaly)

    async def _periodic_ai_batch_loop(self) -> None:
        while self._is_running:
            try:
                await asyncio.sleep(self.settings.ai_batch_interval_seconds)
                await self._flush_ai_batches()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Error processing AI anomaly batches: %s", exc)

    async def _flush_ai_batches(self) -> None:
        async with self._ai_batch_lock:
            batches = self._pending_ai_batches
            self._pending_ai_batches = {}
        for key, anomalies in batches.items():
            logger.info("Triaging %d related anomalies for %s/%s", len(anomalies), *key)
            results = await self.ai_worker.analyze_batch(anomalies)
            self.openai_error_count += sum(1 for result in results if result.error)

    async def _periodic_flush_loop(self):
        """Periodically flushes in-memory bucket aggregates to SQLite."""
        while self._is_running:
            try:
                await asyncio.sleep(10)
                await self.aggregator.flush_all()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error flushing aggregates: %s", e)

    async def _periodic_retention_loop(self):
        """Runs hourly retention cleanup (deleting samples >24h, aggregates >6mo)."""
        while self._is_running:
            try:
                await asyncio.sleep(3600)  # Hourly
                await self.db.run_retention_cleanup(
                    sample_retention_hours=self.settings.sample_retention_hours,
                    aggregate_retention_months=self.settings.aggregate_retention_months
                )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error running retention cleanup: %s", e)

    def get_telemetry(self) -> TelemetryMetrics:
        """Collects live telemetry for dashboard display."""
        elapsed = max(1, time.time() - self._start_time)
        rate = round(self.total_lines_read / elapsed, 2)
        stream_metrics = self.stream_manager.get_metrics()
        source_warnings = sum(tailer.error_count for tailer in self.tailers.values())

        return TelemetryMetrics(
            ingestion_rate_lps=rate,
            total_lines_read=self.total_lines_read,
            dropped_events=stream_metrics["dropped_events_count"],
            kafka_consumer_lag=stream_metrics["consumer_lag"],
            active_anomalies_count=0,  # Will be populated from DB in API
            templates_count=0,
            sources_count=len(self.sources),
            openai_error_count=self.openai_error_count,
            data_loss_warning=stream_metrics["data_loss_warning"],
            parsing_warnings_count=self.parsing_warnings_count + source_warnings
        )

    async def record_incident_resolution(self, anomaly_id: str, comment: str, action: str = "dismiss") -> Optional[str]:
        """Indexes user resolution notes into persistent organizational memory for future matching."""
        if not comment or not comment.strip():
            return None

        anomaly = await self.db.get_anomaly_record(anomaly_id)
        if not anomaly:
            return None

        knowledge_text = (
            f"[Resolution Knowledge - {anomaly.application}/{anomaly.environment}] "
            f"Incident Template: {anomaly.template_text} | "
            f"Anomaly Type: {anomaly.anomaly_type.value} | "
            f"Resolution Notes & Steps: {comment.strip()}"
        )
        embedding = await self.ai_worker._create_embedding(knowledge_text)
        record_id = await self.vector_index.add_record(
            text_content=knowledge_text,
            embedding=embedding,
            template_id=anomaly.template_id,
            anomaly_id=anomaly.id,
        )
        logger.info("Indexed resolution notes for anomaly %s into organizational memory (record: %s)", anomaly_id, record_id)
        return record_id
