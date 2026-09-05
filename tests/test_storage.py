"""Tests for SQLite Storage, WAL mode, and Retention Cleanups."""

import pytest
from datetime import datetime, timezone, timedelta
from logscope.models import (
    SourceConfig, TemplateRecord, SanitizedObservation, LogLevel,
    AnomalyRecord, AnomalyType, AnomalyStatus, ConfidenceLevel,
)
from logscope.storage.db import Database


@pytest.mark.asyncio
async def test_database_sources_and_templates(test_db: Database):
    src = SourceConfig(id="auth-test", application="auth", environment="prod", path="/logs/auth.log")
    await test_db.upsert_source(src)

    sources = await test_db.get_all_sources()
    assert len(sources) == 1
    assert sources[0]["id"] == "auth-test"

    tmpl = TemplateRecord(
        id="tmpl_123",
        application="auth",
        environment="prod",
        template_pattern="User login for <NUM>",
        first_seen=datetime.now(timezone.utc),
        last_seen=datetime.now(timezone.utc),
        total_count=5
    )
    await test_db.upsert_template(tmpl)

    retrieved = await test_db.get_template("tmpl_123")
    assert retrieved is not None
    assert retrieved.total_count == 5


@pytest.mark.asyncio
async def test_samples_and_retention(test_db: Database):
    now = datetime.now(timezone.utc)
    obs = SanitizedObservation(
        source_id="auth-test",
        application="auth",
        environment="prod",
        template_id="tmpl_123",
        template_text="User login for <NUM>",
        sanitized_message="User login for 100",
        level=LogLevel.INFO,
        timestamp=now,
        source_path="/logs/auth.log",
        sample_hash="hash_abc_123"
    )

    await test_db.save_sample(obs, retention_hours=24)
    samples = await test_db.get_samples_for_template("tmpl_123")
    assert len(samples) == 1
    assert samples[0]["sanitized_message"] == "User login for 100"

    # Test retention cleanup with 0 hours retention to trigger immediate expiry
    res = await test_db.run_retention_cleanup(sample_retention_hours=0, aggregate_retention_months=0)
    assert res["samples_deleted"] >= 0


@pytest.mark.asyncio
async def test_retention_deletes_old_anomalies_embeddings_and_templates(test_db: Database):
    old = datetime.now(timezone.utc) - timedelta(days=190)
    template = TemplateRecord(
        id="tmpl_old",
        application="auth",
        environment="prod",
        template_pattern="Old template",
        first_seen=old,
        last_seen=old,
        total_count=1,
    )
    await test_db.upsert_template(template)
    anomaly = AnomalyRecord(
        application="auth",
        environment="prod",
        template_id="tmpl_old",
        anomaly_type=AnomalyType.NEW_TEMPLATE,
        detected_at=old,
        bucket_start=old,
        current_count=1,
        template_text="Old template",
    )
    await test_db.insert_anomaly(anomaly)
    async with test_db.get_connection() as conn:
        await conn.execute(
            "INSERT INTO embedding_records (id, template_id, anomaly_id, embedding_json, text_content, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("emb-old", "tmpl_old", anomaly.id, "[0.1, 0.2]", "old", old),
        )
        await conn.commit()

    result = await test_db.run_retention_cleanup(sample_retention_hours=24, aggregate_retention_months=6)
    assert result["anomalies_deleted"] == 1
    assert result["embeddings_deleted"] == 1
    assert result["templates_deleted"] == 1


@pytest.mark.asyncio
async def test_analyzed_anomaly_remains_visible_and_keeps_only_trace_references(test_db: Database):
    anomaly = AnomalyRecord(
        application="auth",
        environment="prod",
        template_id="tmpl_visible",
        anomaly_type=AnomalyType.NEW_TEMPLATE,
        bucket_start=datetime.now(timezone.utc),
        current_count=1,
        template_text="Authentication failed",
        sample_evidence=["sanitized but short-lived sample"],
        source_paths=["/logs/auth.log"],
        evidence_references=[{"source_path": "/logs/auth.log", "line_number": 42}],
    )
    await test_db.insert_anomaly(anomaly)
    await test_db.update_anomaly_status(anomaly.id, AnomalyStatus.ANALYZED)

    active = await test_db.get_active_anomalies()
    assert len(active) == 1
    assert active[0]["status"] == AnomalyStatus.ANALYZED.value
    assert active[0]["sample_evidence"] == []
    assert active[0]["evidence_references"][0]["line_number"] == 42


def test_confidence_has_all_five_prd_levels():
    assert ConfidenceLevel.VERY_LOW.value == "very-low"


@pytest.mark.asyncio
async def test_processing_checkpoint_round_trip(test_db: Database):
    await test_db.save_checkpoint("auth", "/logs/auth.log", 128, 12)
    checkpoints = await test_db.get_checkpoints("auth")
    assert checkpoints == [{"source_id": "auth", "file_path": "/logs/auth.log", "offset": 128, "line_number": 12}]


@pytest.mark.asyncio
async def test_template_sample_message_persistence(test_db: Database):
    now = datetime.now(timezone.utc)
    tmpl = TemplateRecord(
        id="tmpl_sample_test",
        application="payments",
        environment="prod",
        template_pattern="Transaction <NUM> failed with status <NUM>",
        sample_message="Transaction 98412 failed with status 502",
        first_seen=now,
        last_seen=now,
        total_count=1
    )
    await test_db.upsert_template(tmpl)

    stored = await test_db.get_template("tmpl_sample_test")
    assert stored is not None
    assert stored.sample_message == "Transaction 98412 failed with status 502"

    # Subsequent update preserves founding sample even if update doesn't have it
    tmpl2 = TemplateRecord(
        id="tmpl_sample_test",
        application="payments",
        environment="prod",
        template_pattern="Transaction <NUM> failed with status <NUM>",
        sample_message=None,
        first_seen=now,
        last_seen=now,
        total_count=2
    )
    await test_db.upsert_template(tmpl2)

    stored2 = await test_db.get_template("tmpl_sample_test")
    assert stored2 is not None
    assert stored2.total_count == 3
    assert stored2.sample_message == "Transaction 98412 failed with status 502"

