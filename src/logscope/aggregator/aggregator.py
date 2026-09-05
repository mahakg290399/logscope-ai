"""Five-minute Bucket Aggregator for LogScope AI."""

import asyncio
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple
from logscope.models import SanitizedObservation, TemplateBucket, TemplateRecord, LogLevel
from logscope.storage.db import Database


def get_bucket_window(dt: datetime, bucket_minutes: int = 5) -> Tuple[datetime, datetime]:
    """Calculates aligned start and end timestamps for a 5-minute bucket."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    minute = (dt.minute // bucket_minutes) * bucket_minutes
    bucket_start = dt.replace(minute=minute, second=0, microsecond=0)
    bucket_end = bucket_start + timedelta(minutes=bucket_minutes)
    return bucket_start, bucket_end


class BucketAggregator:
    """Aggregates streaming sanitized observations into 5-minute SQLite buckets."""

    def __init__(self, db: Database, bucket_minutes: int = 5):
        self.db = db
        self.bucket_minutes = bucket_minutes
        # (template_id, bucket_start) -> TemplateBucket
        self.active_buckets: Dict[Tuple[str, datetime], TemplateBucket] = {}
        self._known_templates: set[str] = set()
        self._known_sample_hashes: set[str] = set()
        self._lock = asyncio.Lock()

    async def ingest_observation(self, obs: SanitizedObservation):
        """Accumulates an observation into its corresponding 5-minute bucket."""
        bucket_start, bucket_end = get_bucket_window(obs.timestamp, self.bucket_minutes)
        key = (obs.template_id, bucket_start)

        is_error = obs.level in (LogLevel.ERROR, LogLevel.CRITICAL, LogLevel.FATAL)

        save_sample_now = False
        save_tmpl_now = False

        async with self._lock:
            if key not in self.active_buckets:
                self.active_buckets[key] = TemplateBucket(
                    # Stable key makes every flush of the same five-minute
                    # bucket an upsert instead of creating duplicate rows.
                    id=f"{obs.template_id}:{bucket_start.isoformat()}",
                    template_id=obs.template_id,
                    application=obs.application,
                    environment=obs.environment,
                    bucket_start=bucket_start,
                    bucket_end=bucket_end,
                    count=0,
                    error_count=0,
                    sample_hashes=[]
                )

            bucket = self.active_buckets[key]
            bucket.count += 1
            if is_error:
                bucket.error_count += 1

            # Keep bounded sample hashes (up to 5 per bucket)
            if obs.sample_hash not in bucket.sample_hashes and len(bucket.sample_hashes) < 5:
                bucket.sample_hashes.append(obs.sample_hash)

            if obs.sample_hash not in self._known_sample_hashes:
                self._known_sample_hashes.add(obs.sample_hash)
                save_sample_now = True

            if obs.template_id not in self._known_templates:
                self._known_templates.add(obs.template_id)
                tmpl = TemplateRecord(
                    id=obs.template_id,
                    application=obs.application,
                    environment=obs.environment,
                    template_pattern=obs.template_text,
                    first_seen=obs.timestamp,
                    last_seen=obs.timestamp,
                    total_count=1,
                    # Persist the founding sanitized log sample from which this template was formed
                    sample_message=obs.sanitized_message
                )
                save_tmpl_now = True

        # Store sample in DB (bounded retention) if new
        if save_sample_now:
            await self.db.save_sample(obs)

        # Register template metadata if new
        if save_tmpl_now:
            await self.db.upsert_template(tmpl)

    async def flush_all(self):
        """Flushes active in-memory buckets to the database."""
        async with self._lock:
            buckets_to_save = list(self.active_buckets.values())
            self.active_buckets.clear()

        if buckets_to_save:
            await self.db.record_bucket_counts(buckets_to_save)
            for b in buckets_to_save:
                # Synchronize template total count and last_seen on bucket flush
                tmpl = TemplateRecord(
                    id=b.template_id,
                    application=b.application,
                    environment=b.environment,
                    template_pattern="",
                    first_seen=b.bucket_start,
                    last_seen=b.bucket_end,
                    total_count=b.count,
                    sample_message=None
                )
                await self.db.upsert_template(tmpl)
