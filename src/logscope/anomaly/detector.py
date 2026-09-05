"""Deterministic Anomaly Detector for LogScope AI."""

import math
from datetime import datetime, timezone
from typing import Optional, List, Dict, Set
import numpy as np
from logscope.models import (
    SanitizedObservation, AnomalyRecord, AnomalyType, AnomalyStatus, LogLevel
)
from logscope.storage.db import Database
from logscope.config import Settings


class AnomalyDetector:
    """Detects deterministic log anomalies (New Templates, Frequency Spikes, Error Bursts)."""

    def __init__(self, db: Database, settings: Settings):
        self.db = db
        self.settings = settings
        # Track recently fired anomaly keys (template_id, bucket_start, anomaly_type) to prevent spamming
        self._recently_fired: Set[str] = set()

    @staticmethod
    def _create_anomaly_record(
        obs: SanitizedObservation,
        anomaly_type: AnomalyType,
        bucket_start: datetime,
        current_count: int,
        baseline_count: float,
        z_score: Optional[float],
        sample_evidence: List[str],
    ) -> AnomalyRecord:
        """Factory consolidating consistent AnomalyRecord construction and evidence references."""
        return AnomalyRecord(
            application=obs.application,
            environment=obs.environment,
            template_id=obs.template_id,
            anomaly_type=anomaly_type,
            bucket_start=bucket_start,
            current_count=current_count,
            baseline_count=round(baseline_count, 2),
            z_score=round(float(z_score), 2) if z_score is not None else None,
            status=AnomalyStatus.ACTIVE,
            template_text=obs.template_text,
            sample_evidence=sample_evidence,
            source_paths=[obs.source_path],
            related_template_ids=[obs.template_id],
            evidence_references=[{
                "template_id": obs.template_id,
                "source_id": obs.source_id,
                "source_path": obs.source_path,
                "line_number": obs.line_number,
                "timestamp": obs.timestamp.isoformat(),
                "sample_hash": obs.sample_hash,
            }],
        )

    async def evaluate_observation(
        self,
        obs: SanitizedObservation,
        is_new_template: bool,
        current_bucket_count: int,
        bucket_start: datetime
    ) -> Optional[AnomalyRecord]:
        """Evaluates an observation and its bucket statistics for anomalies."""
        tmpl_id = obs.template_id

        # 1. Check for New Template anomaly
        if is_new_template:
            dedup_key = f"new_{tmpl_id}"
            if dedup_key not in self._recently_fired:
                self._recently_fired.add(dedup_key)
                anomaly = self._create_anomaly_record(
                    obs=obs,
                    anomaly_type=AnomalyType.NEW_TEMPLATE,
                    bucket_start=bucket_start,
                    current_count=1,
                    baseline_count=0.0,
                    z_score=None,
                    sample_evidence=[obs.sanitized_message],
                )
                await self.db.insert_anomaly(anomaly)
                return anomaly

        # 2. Check for Frequency Spike / Error Burst
        # Only evaluate spike if minimum count threshold is met
        if current_bucket_count >= self.settings.min_sample_count_for_spike:
            # Query historical buckets for baseline
            history = await self.db.get_template_history(tmpl_id, limit_buckets=self.settings.baseline_window_buckets)
            # Exclude current bucket from historical baseline
            historical_counts = [h["count"] for h in history if str(h["bucket_start"]) != str(bucket_start)]

            if len(historical_counts) >= 3:
                mean = float(np.mean(historical_counts))
                std = float(np.std(historical_counts))

                if std > 0:
                    z_score = (current_bucket_count - mean) / std
                else:
                    # If std is 0 and current count is significantly higher
                    z_score = 4.0 if current_bucket_count > (mean * 3 + 5) else 0.0

                if z_score >= self.settings.spike_zscore_threshold:
                    dedup_key = f"spike_{tmpl_id}_{bucket_start.isoformat()}"
                    if dedup_key not in self._recently_fired:
                        self._recently_fired.add(dedup_key)

                        is_error = obs.level in (LogLevel.ERROR, LogLevel.CRITICAL, LogLevel.FATAL)
                        anomaly_type = AnomalyType.ERROR_BURST if is_error else AnomalyType.FREQUENCY_SPIKE

                        # Retrieve recent samples for evidence
                        recent_samples = await self.db.get_samples_for_template(tmpl_id, limit=3)
                        sample_texts = [s["sanitized_message"] for s in recent_samples] or [obs.sanitized_message]

                        anomaly = self._create_anomaly_record(
                            obs=obs,
                            anomaly_type=anomaly_type,
                            bucket_start=bucket_start,
                            current_count=current_bucket_count,
                            baseline_count=mean,
                            z_score=z_score,
                            sample_evidence=sample_texts,
                        )
                        await self.db.insert_anomaly(anomaly)
                        return anomaly

        return None
