"""Tests for 5-Minute Aggregator and Anomaly Detector."""

import pytest
from datetime import datetime, timezone, timedelta
from logscope.models import SanitizedObservation, LogLevel, AnomalyType, TemplateBucket
from logscope.aggregator.aggregator import BucketAggregator, get_bucket_window
from logscope.anomaly.detector import AnomalyDetector
from logscope.config import Settings
from logscope.storage.db import Database


@pytest.mark.asyncio
async def test_bucket_aggregator(test_db: Database):
    agg = BucketAggregator(test_db, bucket_minutes=5)
    now = datetime(2026, 8, 10, 14, 7, 23, tzinfo=timezone.utc)

    obs = SanitizedObservation(
        source_id="src1",
        application="auth",
        environment="prod",
        template_id="tmpl_999",
        template_text="Cache missed for <NUM>",
        sanitized_message="Cache missed for 44",
        level=LogLevel.WARN,
        timestamp=now,
        source_path="/logs/auth.log",
        sample_hash="hash_999_1"
    )

    await agg.ingest_observation(obs)
    await agg.flush_all()

    history = await test_db.get_template_history("tmpl_999")
    assert len(history) == 1
    assert history[0]["count"] == 1
    assert history[0]["error_count"] == 0


@pytest.mark.asyncio
async def test_bucket_aggregator_upserts_same_window_after_multiple_flushes(test_db: Database):
    agg = BucketAggregator(test_db, bucket_minutes=5)
    now = datetime(2026, 8, 10, 14, 7, 23, tzinfo=timezone.utc)

    for sample_hash in ("sample-one", "sample-two"):
        await agg.ingest_observation(SanitizedObservation(
            source_id="src1",
            application="auth",
            environment="prod",
            template_id="tmpl_stable",
            template_text="Request completed <NUM>",
            sanitized_message="Request completed 200",
            level=LogLevel.INFO,
            timestamp=now,
            source_path="/logs/auth.log",
            sample_hash=sample_hash,
        ))
        await agg.flush_all()

    history = await test_db.get_template_history("tmpl_stable")
    assert len(history) == 1
    assert history[0]["count"] == 2


@pytest.mark.asyncio
async def test_anomaly_detector_new_template(test_db: Database, test_settings: Settings):
    detector = AnomalyDetector(test_db, test_settings)
    now = datetime.now(timezone.utc)
    b_start, _ = get_bucket_window(now)

    obs = SanitizedObservation(
        source_id="src1",
        application="payment",
        environment="prod",
        template_id="tmpl_err",
        template_text="Payment processor timeout <NUM>",
        sanitized_message="Payment processor timeout 5000ms",
        level=LogLevel.ERROR,
        timestamp=now,
        source_path="/logs/payment.log",
        sample_hash="hash_err_1"
    )

    anomaly = await detector.evaluate_observation(
        obs,
        is_new_template=True,
        current_bucket_count=1,
        bucket_start=b_start
    )

    assert anomaly is not None
    assert anomaly.anomaly_type == AnomalyType.NEW_TEMPLATE
    assert anomaly.application == "payment"
