"""Pydantic data models for LogScope AI."""

from __future__ import annotations
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, model_validator
import uuid


class LogLevel(str, Enum):
    TRACE = "TRACE"
    DEBUG = "DEBUG"
import uuid
import secrets


class LogLevel(str, Enum):
    TRACE = "TRACE"
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARN = "WARN"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"
    FATAL = "FATAL"
    UNKNOWN = "UNKNOWN"


class AnomalyType(str, Enum):
    NEW_TEMPLATE = "new_template"
    FREQUENCY_SPIKE = "frequency_spike"
    ERROR_BURST = "error_burst"


class AnomalyStatus(str, Enum):
    ACTIVE = "active"
    DISMISSED = "dismissed"
    ANALYZING = "analyzing"
    ANALYZED = "analyzed"
    FAILED = "failed"


class ResolutionAction(str, Enum):
    RESOLVED = "resolved"
    FALSE_POSITIVE = "false_positive"
    TRANSIENT = "transient"
    DISMISS = "dismiss"


class SeverityLevel(str, Enum):
    SEV_0 = "Sev-0"  # Critical outage / Data loss
    SEV_1 = "Sev-1"  # Major degradation / High business impact
    SEV_2 = "Sev-2"  # Moderate issue / Workaround available
    SEV_3 = "Sev-3"  # Minor anomaly / Low impact
    SEV_4 = "Sev-4"  # Informational / Cosmetic / False alarm


class ConfidenceLevel(str, Enum):
    VERY_LOW = "very-low"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    VERY_HIGH = "very-high"


class SourceConfig(BaseModel):
    id: str
    application: str
    environment: str
    path: str
    format: str = "auto"  # auto, json, regex
    multiline_pattern: Optional[str] = None
    multiline_negate: bool = True
    service: Optional[str] = None
    host: Optional[str] = None
    container: Optional[str] = None
    source_name: Optional[str] = None
    enabled: bool = True

    @model_validator(mode="before")
    @classmethod
    def flatten_multiline_settings(cls, value: Any) -> Any:
        """Accept the documented nested YAML multiline block as well as flat fields."""
        if not isinstance(value, dict):
            return value
        normalized = dict(value)
        multiline = normalized.get("multiline")
        if isinstance(multiline, dict):
            normalized.setdefault("multiline_pattern", multiline.get("pattern"))
            normalized.setdefault("multiline_negate", multiline.get("negate", True))
        return normalized


class ParsedLogEvent(BaseModel):
    raw_line: str
    timestamp: Optional[datetime] = None
    level: LogLevel = LogLevel.UNKNOWN
    message: str
    source_path: str
    line_number: Optional[int] = None
    source_id: str
    application: str
    environment: str
    attributes: Dict[str, Any] = Field(default_factory=dict)


class SanitizedObservation(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_id: str
    application: str
    environment: str
    template_id: str
    template_text: str
    sanitized_message: str
    level: LogLevel = LogLevel.UNKNOWN
    timestamp: datetime
    ingestion_timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source_path: str
    line_number: Optional[int] = None
    parameters: List[str] = Field(default_factory=list)
    sample_hash: str
    client_id_hash: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    redaction_types: List[str] = Field(default_factory=list)


class TemplateRecord(BaseModel):
    id: str
    application: str
    environment: str
    template_pattern: str
    first_seen: datetime
    last_seen: datetime
    total_count: int = 0
    sample_message: Optional[str] = None


class TemplateBucket(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    template_id: str
    application: str
    environment: str
    bucket_start: datetime
    bucket_end: datetime
    count: int = 0
    error_count: int = 0
    sample_hashes: List[str] = Field(default_factory=list)


class AnomalyRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    incident_number: str = Field(default_factory=lambda: f"INC{secrets.randbelow(10_000_000):07d}")
    application: str
    environment: str
    template_id: str
    anomaly_type: AnomalyType
    detected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    bucket_start: datetime
    current_count: int
    baseline_count: float = 0.0
    z_score: Optional[float] = None
    status: AnomalyStatus = AnomalyStatus.ACTIVE
    template_text: str
    sample_evidence: List[str] = Field(default_factory=list)
    source_paths: List[str] = Field(default_factory=list)
    related_template_ids: List[str] = Field(default_factory=list)
    evidence_references: List[Dict[str, Any]] = Field(default_factory=list)
    detector_version: str = "v1"
    data_loss_warning: bool = False


class AIAnalysisResult(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    anomaly_id: str
    model: str
    prompt_version: str
    severity: SeverityLevel
    confidence: ConfidenceLevel
    investigate: bool = True
    summary: str
    evidence: List[Dict[str, Any]] = Field(default_factory=list)
    possible_causes: List[str] = Field(default_factory=list)
    recommended_actions: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)
    raw_response: Optional[str] = None
    error: Optional[str] = None
    is_retryable: bool = False
    execution_time_ms: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class FeedbackRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    anomaly_id: str
    action: str  # e.g., "dismiss", "escalate", "confirm"
    comment: Optional[str] = None
    previous_severity: Optional[str] = None
    previous_confidence: Optional[str] = None
    new_severity: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TelemetryMetrics(BaseModel):
    ingestion_rate_lps: float = 0.0
    total_lines_read: int = 0
    dropped_events: int = 0
    kafka_consumer_lag: int = 0
    active_anomalies_count: int = 0
    templates_count: int = 0
    sources_count: int = 0
    openai_error_count: int = 0
    data_loss_warning: bool = False
    parsing_warnings_count: int = 0
