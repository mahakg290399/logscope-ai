"""Configuration management for LogScope AI."""

import os
from pathlib import Path
from typing import List, Optional
import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from logscope.models import SourceConfig


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Core
    env: str = Field(default="development", alias="LOGSCOPE_ENV")
    port: int = Field(default=8000, alias="LOGSCOPE_PORT")
    host: str = Field(default="127.0.0.1", alias="LOGSCOPE_HOST")
    data_dir: Path = Field(default=Path("./data"), alias="LOGSCOPE_DATA_DIR")
"""Configuration management for LogScope AI."""

import os
from pathlib import Path
from typing import List, Optional
import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from logscope.models import SourceConfig


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Core
    env: str = Field(default="development", alias="LOGSCOPE_ENV")
    port: int = Field(default=8000, alias="LOGSCOPE_PORT")
    host: str = Field(default="127.0.0.1", alias="LOGSCOPE_HOST")
    data_dir: Path = Field(default=Path("./data"), alias="LOGSCOPE_DATA_DIR")
    db_path: Path = Field(default=Path("./data/logscope.db"), alias="LOGSCOPE_DB_PATH")
    sources_config_path: Path = Field(default=Path("./sources.yaml"), alias="LOGSCOPE_SOURCES_CONFIG")

    # Kafka
    kafka_bootstrap_servers: str = Field(default="localhost:9092", alias="LOGSCOPE_KAFKA_BOOTSTRAP_SERVERS")
    kafka_client_id: str = Field(default="logscope-local", alias="LOGSCOPE_KAFKA_CLIENT_ID")
    kafka_topic_observations: str = Field(default="logscope.template-observations", alias="LOGSCOPE_KAFKA_TOPIC_OBSERVATIONS")
    kafka_topic_anomalies: str = Field(default="logscope.anomaly-jobs", alias="LOGSCOPE_KAFKA_TOPIC_ANOMALIES")
    kafka_topic_analyses: str = Field(default="logscope.analysis-results", alias="LOGSCOPE_KAFKA_TOPIC_ANALYSES")
    kafka_topic_raw_logs: Optional[str] = Field(default=None, alias="LOGSCOPE_KAFKA_TOPIC_RAW_LOGS")
    kafka_embedded_fallback: bool = Field(default=False, alias="LOGSCOPE_KAFKA_EMBEDDED_FALLBACK")
    queue_max_size: int = Field(default=10000, alias="LOGSCOPE_QUEUE_MAX_SIZE")

    # POC uses direct OpenAI. The compatibility code remains available only for
    # local development migrations and is not the documented deployment path.
    ai_provider: str = Field(default="openai", alias="LOGSCOPE_AI_PROVIDER")
    ai_base_url: Optional[str] = Field(
        default=None,
        alias="LOGSCOPE_AI_BASE_URL",
    )
    openai_api_key: Optional[str] = Field(default=None, alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4o-mini", alias="OPENAI_MODEL")
    openai_embedding_model: str = Field(
        default="text-embedding-3-small",
        alias="OPENAI_EMBEDDING_MODEL",
    )
    # Optional direct Google AI Studio (Gemini OpenAI-compat endpoint) fallback
    gemini_api_key: Optional[str] = Field(default=None, alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-2.0-flash", alias="GEMINI_MODEL")
    gemini_base_url: str = Field(
        default="https://generativelanguage.googleapis.com/v1beta/openai/",
        alias="GEMINI_BASE_URL",
    )
    gemini_embedding_model: str = Field(
        default="text-embedding-004",
        alias="GEMINI_EMBEDDING_MODEL",
    )

    # NVIDIA NIM (OpenAI-compatible microservice & hosted endpoint)
    nvidia_api_key: Optional[str] = Field(default=None, alias="NVIDIA_API_KEY")
    nvidia_model: str = Field(default="nvidia/nemotron-3.5-lightning-30b-a3b", alias="NVIDIA_MODEL")
    nvidia_base_url: str = Field(
        default="https://integrate.api.nvidia.com/v1",
        alias="NVIDIA_BASE_URL",
    )
    nvidia_embedding_model: str = Field(
        default="nvidia/llama-3.2-nv-embedqa-1b-v1",
        alias="NVIDIA_EMBEDDING_MODEL",
    )

    ai_batch_interval_seconds: int = Field(default=60, alias="LOGSCOPE_AI_BATCH_INTERVAL_SECONDS")
    ai_max_batch_size: int = Field(default=10, alias="LOGSCOPE_AI_MAX_BATCH_SIZE")

    def resolved_ai_provider(self) -> str:
        """Normalize provider name."""
        provider = (self.ai_provider or "omniroute").strip().lower()
        if provider in {"nvidia", "nim", "nvidia-nim"}:
            return "nvidia"
        if provider in {"omni", "omniroute", "openrouter-local"}:
            return "omniroute"
        if provider in {"gemini", "google", "ai-studio", "google-ai-studio"}:
            return "gemini"
        if provider in {"openai", "oai"}:
            return "openai"
        if provider == "auto":
            return "auto"
        return provider

    def has_llm_credentials(self) -> bool:
        """True when at least one chat provider can be configured."""
        provider = self.resolved_ai_provider()
        if provider in {"nvidia", "auto"} and (self.nvidia_api_key or self.openai_api_key):
            return True
        if provider in {"omniroute", "openai", "auto"} and self.openai_api_key:
            return True
        if provider in {"gemini", "auto"} and (self.gemini_api_key or self.openai_api_key):
            return True
        return bool(self.nvidia_api_key or self.openai_api_key or self.gemini_api_key)

    def provider_chat_model(self, provider: str) -> str:
        """Chat model id for the active provider."""
        if provider == "nvidia":
            return self.nvidia_model
        if provider == "gemini":
            return self.gemini_model
        return self.openai_model

    def provider_embedding_model(self, provider: str) -> str:
        """Embedding model id for the active provider (local TF-IDF remains default index)."""
        if provider == "nvidia":
            return self.nvidia_embedding_model
        if provider == "gemini":
            return self.gemini_embedding_model
        return self.openai_embedding_model

    # Retention
    sample_retention_hours: int = Field(default=24, alias="LOGSCOPE_SAMPLE_RETENTION_HOURS")
    aggregate_retention_months: int = Field(default=6, alias="LOGSCOPE_AGGREGATE_RETENTION_MONTHS")

    # Anomaly
    spike_zscore_threshold: float = Field(default=3.0, alias="LOGSCOPE_SPIKE_ZSCORE_THRESHOLD")
    min_sample_count_for_spike: int = Field(default=5, alias="LOGSCOPE_MIN_SAMPLE_COUNT_FOR_SPIKE")
    baseline_window_buckets: int = Field(default=12, alias="LOGSCOPE_BASELINE_WINDOW_BUCKETS")  # 1 hour baseline

    def get_sources(self) -> List[SourceConfig]:
        """Load sources from configured yaml file or fallback."""
        if self.sources_config_path.exists():
            with open(self.sources_config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
                raw_sources = data.get("sources", [])
                return [SourceConfig(**s) for s in raw_sources]
        
        # Check if example exists
        example_path = Path("sources.example.yaml")
        if example_path.exists():
            with open(example_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
                raw_sources = data.get("sources", [])
                return [SourceConfig(**s) for s in raw_sources]

        return []


def get_settings() -> Settings:
    settings = Settings()
    # Check if sources.yaml provides retention overrides and env vars were not explicitly set
    config_file = settings.sources_config_path if settings.sources_config_path.exists() else Path("sources.example.yaml")
    if config_file.exists():
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
                retention_conf = data.get("retention", {})
                if isinstance(retention_conf, dict):
                    if "sample_retention_hours" in retention_conf and "LOGSCOPE_SAMPLE_RETENTION_HOURS" not in os.environ:
                        settings.sample_retention_hours = int(retention_conf["sample_retention_hours"])
                    if "aggregate_retention_months" in retention_conf and "LOGSCOPE_AGGREGATE_RETENTION_MONTHS" not in os.environ:
                        settings.aggregate_retention_months = int(retention_conf["aggregate_retention_months"])
        except Exception:
            pass

    # Ensure data directory exists
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return settings
