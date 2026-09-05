"""Kafka streaming boundary for sanitized LogScope events.

Kafka is the POC data path when ``LOGSCOPE_KAFKA_EMBEDDED_FALLBACK=false``.
The bounded in-memory queues are deliberately restricted to the explicit test
fallback; production-style Docker runs must not process around Kafka.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Awaitable, Callable, Dict, Optional, Type, TypeVar

from logscope.config import Settings
from logscope.models import AIAnalysisResult, AnomalyRecord, SanitizedObservation

logger = logging.getLogger(__name__)

T = TypeVar("T")
Handler = Callable[[T], Awaitable[None]]


class KafkaStreamManager:
    """Publish and consume sanitized records with an explicit test fallback."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.use_fallback = settings.kafka_embedded_fallback
        self.producer: Any = None
        self._connected_kafka = False
        self._consumers: list[Any] = []
        self._stopped = asyncio.Event()

        # Fallback queues are used only by tests/local direct mode.
        self.observations_queue: asyncio.Queue[SanitizedObservation] = asyncio.Queue(maxsize=settings.queue_max_size)
        self.anomalies_queue: asyncio.Queue[AnomalyRecord] = asyncio.Queue(maxsize=settings.queue_max_size)
        self.analyses_queue: asyncio.Queue[AIAnalysisResult] = asyncio.Queue(maxsize=settings.queue_max_size)
        self.raw_logs_queue: asyncio.Queue[tuple[str, Dict[str, Any]]] = asyncio.Queue(maxsize=settings.queue_max_size)

        self.dropped_events_count = 0
        self.total_published = 0
        self.consumer_lag = 0

    async def initialize(self) -> None:
        """Connect Kafka or enter the explicitly configured in-memory test mode."""
        self._stopped.clear()
        if self.use_fallback:
            logger.warning("Kafka embedded fallback is enabled; this mode is for tests/local development only.")
            return

        try:
            from kafka import KafkaProducer

            self.producer = await asyncio.to_thread(
                KafkaProducer,
                bootstrap_servers=self.settings.kafka_bootstrap_servers.split(","),
                client_id=self.settings.kafka_client_id,
                value_serializer=lambda value: json.dumps(value, default=str).encode("utf-8"),
                key_serializer=lambda key: key.encode("utf-8") if key else None,
                request_timeout_ms=5000,
                retries=3,
                acks="all",
            )
            await self._ensure_topics()
            self._connected_kafka = True
            logger.info("Connected to Kafka at %s", self.settings.kafka_bootstrap_servers)
        except Exception as exc:
            self.producer = None
            self._connected_kafka = False
            raise RuntimeError(
                "Kafka is required when LOGSCOPE_KAFKA_EMBEDDED_FALLBACK=false; "
                f"unable to connect to {self.settings.kafka_bootstrap_servers}: {exc}"
            ) from exc

    async def _ensure_topics(self) -> None:
        """Create the three POC topics with the required 24-hour retention."""
        from kafka.admin import KafkaAdminClient, NewTopic

        topic_names = [
            self.settings.kafka_topic_observations,
            self.settings.kafka_topic_anomalies,
            self.settings.kafka_topic_analyses,
        ]
        if self.settings.kafka_topic_raw_logs:
            topic_names.append(self.settings.kafka_topic_raw_logs)

        def create_topics() -> None:
            admin = KafkaAdminClient(
                bootstrap_servers=self.settings.kafka_bootstrap_servers.split(","),
                client_id=f"{self.settings.kafka_client_id}-admin",
            )
            try:
                existing = set(admin.list_topics())
                missing = [
                    NewTopic(
                        name=name,
                        num_partitions=1,
                        replication_factor=1,
                        topic_configs={"retention.ms": "86400000"},
                    )
                    for name in topic_names
                    if name not in existing
                ]
                if missing:
                    admin.create_topics(new_topics=missing, validate_only=False)
            finally:
                admin.close()

        await asyncio.to_thread(create_topics)

    async def stop(self) -> None:
        self._stopped.set()
        for consumer in self._consumers:
            try:
                await asyncio.to_thread(consumer.close)
            except Exception:
                logger.debug("Kafka consumer close failed", exc_info=True)
        self._consumers.clear()
        if self.producer is not None:
            try:
                await asyncio.to_thread(self.producer.flush, 5)
                await asyncio.to_thread(self.producer.close)
            except Exception:
                logger.debug("Kafka producer close failed", exc_info=True)
        self.producer = None
        self._connected_kafka = False

    async def _publish(self, topic: str, key: Optional[str], payload: Dict[str, Any]) -> None:
        if not self._connected_kafka or self.producer is None:
            raise RuntimeError("Kafka producer is not connected")

        def send() -> None:
            future = self.producer.send(topic, key=key, value=payload)
            future.get(timeout=5)

        await asyncio.to_thread(send)

    async def publish_observation(self, observation: SanitizedObservation) -> bool:
        self.total_published += 1
        if self.use_fallback:
            return self._queue_put_oldest_drop(self.observations_queue, observation)
        await self._publish(
            self.settings.kafka_topic_observations,
            f"{observation.application}::{observation.environment}",
            observation.model_dump(mode="json"),
        )
        return True

    async def publish_anomaly_job(self, anomaly: AnomalyRecord) -> bool:
        if self.use_fallback:
            return self._queue_put_oldest_drop(self.anomalies_queue, anomaly)
        await self._publish(
            self.settings.kafka_topic_anomalies,
            f"{anomaly.application}::{anomaly.environment}",
            anomaly.model_dump(mode="json"),
        )
        return True

    async def publish_analysis_result(self, analysis: AIAnalysisResult) -> bool:
        if self.use_fallback:
            return self._queue_put_oldest_drop(self.analyses_queue, analysis)
        await self._publish(
            self.settings.kafka_topic_analyses,
            analysis.anomaly_id,
            analysis.model_dump(mode="json"),
        )
        return True

    def _queue_put_oldest_drop(self, queue: asyncio.Queue[T], item: T) -> bool:
        if queue.full():
            try:
                queue.get_nowait()
                queue.task_done()
                self.dropped_events_count += 1
            except asyncio.QueueEmpty:
                pass
        try:
            queue.put_nowait(item)
            self.consumer_lag = queue.qsize()
            return True
        except asyncio.QueueFull:
            self.dropped_events_count += 1
            return False

    async def publish_raw_log(self, raw_line: str, metadata: Optional[Dict[str, Any]] = None) -> bool:
        meta = metadata or {}
        if self.use_fallback:
            return self._queue_put_oldest_drop(self.raw_logs_queue, (raw_line, meta))  # type: ignore
        if not self.settings.kafka_topic_raw_logs:
            raise RuntimeError("LOGSCOPE_KAFKA_TOPIC_RAW_LOGS is not configured.")
        payload = {"message": raw_line, **meta}
        await self._publish(
            self.settings.kafka_topic_raw_logs,
            meta.get("application") or "raw",
            payload,
        )
        return True

    async def consume_raw_logs(self, handler: Callable[[str, Dict[str, Any]], Awaitable[None]]) -> None:
        if self.use_fallback:
            while not self._stopped.is_set():
                item = await self.raw_logs_queue.get()
                try:
                    raw_line, meta = item
                    await handler(raw_line, meta)
                finally:
                    self.raw_logs_queue.task_done()
                    self.consumer_lag = self.raw_logs_queue.qsize()
            return

        if not self.settings.kafka_topic_raw_logs:
            logger.info("LOGSCOPE_KAFKA_TOPIC_RAW_LOGS not set; skipping raw Kafka consumer.")
            return

        await self._consume_kafka_raw_topic(
            self.settings.kafka_topic_raw_logs,
            f"{self.settings.kafka_client_id}-raw-ingest",
            handler,
        )

    async def consume_observations(self, handler: Handler[SanitizedObservation]) -> None:
        if self.use_fallback:
            await self._consume_fallback_queue(self.observations_queue, handler)
            return
        await self._consume_kafka_topic(
            self.settings.kafka_topic_observations,
            f"{self.settings.kafka_client_id}-aggregator",
            SanitizedObservation,
            handler,
        )

    async def consume_anomalies(self, handler: Handler[AnomalyRecord]) -> None:
        if self.use_fallback:
            await self._consume_fallback_queue(self.anomalies_queue, handler)
            return
        await self._consume_kafka_topic(
            self.settings.kafka_topic_anomalies,
            f"{self.settings.kafka_client_id}-ai",
            AnomalyRecord,
            handler,
        )

    async def _consume_fallback_queue(self, queue: asyncio.Queue[T], handler: Handler[T]) -> None:
        while not self._stopped.is_set():
            item = await queue.get()
            try:
                await handler(item)
            finally:
                queue.task_done()
                self.consumer_lag = queue.qsize()

    async def _consume_kafka_topic(
        self,
        topic: str,
        group_id: str,
        model: Type[T],
        handler: Handler[T],
    ) -> None:
        from kafka import KafkaConsumer

        consumer = await asyncio.to_thread(
            KafkaConsumer,
            topic,
            bootstrap_servers=self.settings.kafka_bootstrap_servers.split(","),
            group_id=group_id,
            enable_auto_commit=False,
            auto_offset_reset="earliest",
            value_deserializer=lambda raw: json.loads(raw.decode("utf-8")),
            consumer_timeout_ms=1000,
        )
        self._consumers.append(consumer)
        try:
            while not self._stopped.is_set():
                records = await asyncio.to_thread(consumer.poll, timeout_ms=1000, max_records=100)
                if not records:
                    continue
                processed = 0
                for messages in records.values():
                    for message in messages:
                        payload = model.model_validate(message.value)
                        await handler(payload)
                        processed += 1
                if processed:
                    await asyncio.to_thread(consumer.commit)
                self.consumer_lag = await asyncio.to_thread(self._consumer_lag, consumer)
        finally:
            if consumer in self._consumers:
                self._consumers.remove(consumer)
            try:
                await asyncio.to_thread(consumer.close)
            except Exception:
                logger.debug("Kafka consumer close failed", exc_info=True)

    async def _consume_kafka_raw_topic(
        self,
        topic: str,
        group_id: str,
        handler: Callable[[str, Dict[str, Any]], Awaitable[None]],
    ) -> None:
        from kafka import KafkaConsumer

        def deserialize_raw(raw_bytes: bytes) -> tuple[str, Dict[str, Any]]:
            try:
                decoded = raw_bytes.decode("utf-8")
                if decoded.startswith("{") and decoded.endswith("}"):
                    data = json.loads(decoded)
                    if isinstance(data, dict):
                        msg = str(data.get("message") or data.get("log") or decoded)
                        return msg, data
                return decoded, {}
            except Exception:
                return raw_bytes.decode("utf-8", errors="replace"), {}

        consumer = await asyncio.to_thread(
            KafkaConsumer,
            topic,
            bootstrap_servers=self.settings.kafka_bootstrap_servers.split(","),
            group_id=group_id,
            enable_auto_commit=False,
            auto_offset_reset="earliest",
            value_deserializer=deserialize_raw,
            consumer_timeout_ms=1000,
        )
        self._consumers.append(consumer)
        try:
            while not self._stopped.is_set():
                records = await asyncio.to_thread(consumer.poll, timeout_ms=1000, max_records=100)
                if not records:
                    continue
                processed = 0
                for messages in records.values():
                    for message in messages:
                        raw_line, meta = message.value
                        await handler(raw_line, meta)
                        processed += 1
                if processed:
                    await asyncio.to_thread(consumer.commit)
                self.consumer_lag = await asyncio.to_thread(self._consumer_lag, consumer)
        finally:
            if consumer in self._consumers:
                self._consumers.remove(consumer)
            try:
                await asyncio.to_thread(consumer.close)
            except Exception:
                logger.debug("Kafka raw consumer close failed", exc_info=True)

    @staticmethod
    def _consumer_lag(consumer: Any) -> int:
        assignment = consumer.assignment()
        if not assignment:
            return 0
        ends = consumer.end_offsets(assignment)
        return sum(max(0, ends[partition] - consumer.position(partition)) for partition in assignment)

    def get_metrics(self) -> Dict[str, Any]:
        return {
            "connected_kafka": self._connected_kafka,
            "fallback_mode": self.use_fallback,
            "observations_queue_size": self.observations_queue.qsize() if self.use_fallback else 0,
            "anomalies_queue_size": self.anomalies_queue.qsize() if self.use_fallback else 0,
            "raw_logs_queue_size": self.raw_logs_queue.qsize() if self.use_fallback else 0,
            "dropped_events_count": self.dropped_events_count,
            "total_published": self.total_published,
            "consumer_lag": self.consumer_lag,
            "data_loss_warning": self.dropped_events_count > 0,
        }
