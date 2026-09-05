"""Tests for direct Kafka raw topic ingestion (Interface 2)."""

import asyncio
import pytest
from logscope.config import Settings
from logscope.service import LogScopeService


@pytest.mark.asyncio
async def test_kafka_raw_ingest(test_settings: Settings):
    """Test raw logs streamed from Kafka raw queue are consumed, sanitized, and ingested."""
    service = LogScopeService(test_settings)
    await service.start()
    try:
        # 1. Publish plain string with metadata dict
        published_1 = await service.stream_manager.publish_raw_log(
            "2026-09-05 12:00:00 [ERROR] Connection refused to redis://cache:6379 user user@example.com",
            metadata={"application": "cart-svc", "environment": "staging", "source_name": "kafka-raw-topic"},
        )
        assert published_1 is True

        # 2. Publish JSON encoded raw string
        published_2 = await service.stream_manager.publish_raw_log(
            '{"timestamp": "2026-09-05 12:00:01", "level": "WARN", "message": "High memory consumption on worker", "application": "worker-svc"}'
        )
        assert published_2 is True

        # Wait for the background Kafka consumer task to consume and process lines
        for _ in range(30):
            if service.total_lines_read >= 2:
                break
            await asyncio.sleep(0.05)

        assert service.total_lines_read >= 2

        metrics = service.stream_manager.get_metrics()
        assert "raw_logs_queue_size" in metrics
    finally:
        await service.stop()
