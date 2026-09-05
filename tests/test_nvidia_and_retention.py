"""Tests for NVIDIA NIM support, configurable retention windows, and explicit incident resolution actions."""

import os
from datetime import datetime, timezone
from pathlib import Path
import pytest
from httpx import AsyncClient, ASGITransport

from logscope.config import Settings, get_settings
from logscope.ai.client import build_llm_clients
from logscope.models import (
    AnomalyRecord,
    AnomalyStatus,
    AnomalyType,
    ResolutionAction,
)
from logscope.service import LogScopeService
from logscope.api.app import create_app


def test_nvidia_nim_provider_configuration():
    """Verify NVIDIA NIM client resolution, default endpoints, and custom base URL."""
    # 1. Direct nvidia provider with default hosted API
    s1 = Settings(
        LOGSCOPE_AI_PROVIDER="nvidia",
        NVIDIA_API_KEY="nvapi-test-key-12345",
    )
    assert s1.resolved_ai_provider() == "nvidia"
    assert s1.has_llm_credentials() is True
    assert s1.provider_chat_model("nvidia") == "nvidia/nemotron-3.5-lightning-30b-a3b"
    assert s1.provider_embedding_model("nvidia") == "nvidia/llama-3.2-nv-embedqa-1b-v1"

    clients1 = build_llm_clients(s1)
    assert len(clients1) == 1
    handle = clients1[0]
    assert handle.name == "nvidia"
    assert handle.model == "nvidia/nemotron-3.5-lightning-30b-a3b"
    assert handle.embedding_model == "nvidia/llama-3.2-nv-embedqa-1b-v1"
    assert "integrate.api.nvidia.com" in str(handle.base_url)

    # 2. Local container / self-hosted NIM microservice
    s2 = Settings(
        LOGSCOPE_AI_PROVIDER="nim",
        NVIDIA_API_KEY="local-nim-key",
        NVIDIA_BASE_URL="http://localhost:8000/v1",
        NVIDIA_MODEL="mistralai/mixtral-8x7b-instruct",
    )
    assert s2.resolved_ai_provider() == "nvidia"
    clients2 = build_llm_clients(s2)
    assert len(clients2) == 1
    assert clients2[0].base_url == "http://localhost:8000/v1"
    assert clients2[0].model == "mistralai/mixtral-8x7b-instruct"

    # 3. Auto mode includes NVIDIA when key is set
    s3 = Settings(
        LOGSCOPE_AI_PROVIDER="auto",
        NVIDIA_API_KEY="nvapi-auto-key",
        OPENAI_API_KEY="sk-fake-openai",
    )
    clients3 = build_llm_clients(s3)
    names = [c.name for c in clients3]
    assert "nvidia" in names


def test_configurable_retention_defaults_and_env():
    """Verify retention windows can be set via env vars."""
    s_env = Settings(
        LOGSCOPE_SAMPLE_RETENTION_HOURS=72,
        LOGSCOPE_AGGREGATE_RETENTION_MONTHS=12,
    )
    assert s_env.sample_retention_hours == 72
    assert s_env.aggregate_retention_months == 12

    # Check sources.yaml defaults loading in get_settings
    loaded = get_settings()
    assert loaded.sample_retention_hours == 24
    assert loaded.aggregate_retention_months == 6


@pytest.mark.asyncio
async def test_explicit_incident_resolution_actions(tmp_path):
    """Verify resolved, false_positive, and transient actions handle memory appropriately."""
    db_file = tmp_path / "test_actions.db"
    settings = Settings(
        LOGSCOPE_DB_PATH=db_file,
        LOGSCOPE_DATA_DIR=tmp_path,
        LOGSCOPE_KAFKA_EMBEDDED_FALLBACK=True,
        LOGSCOPE_AI_PROVIDER="local",
        OPENAI_API_KEY="",
    )
    service = LogScopeService(settings)
    await service.db.initialize()

    # Seed anomaly
    anomaly = AnomalyRecord(
        id="anom-test-action-1",
        application="auth-service",
        environment="production",
        template_id="tpl-action-1",
        template_text="Failed login attempt for user <USER> from <IP>",
        anomaly_type=AnomalyType.FREQUENCY_SPIKE,
        bucket_start=datetime.now(timezone.utc),
        current_count=50,
        baseline_count=5.0,
        z_score=4.2,
        severity="Sev-1",
        status=AnomalyStatus.ACTIVE,
    )
    await service.db.insert_anomaly(anomaly)

    app = create_app(settings=settings, service=service)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Action: Resolved -> should index notes into organizational memory
        res = await client.post(
            "/api/anomalies/anom-test-action-1/dismiss",
            json={
                "action": "resolved",
                "comment": "Scaled auth replica set from 2 to 5; mitigated credential stuffing spike.",
            }
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "dismissed"
        assert data["action"] == "resolved"

        # Verify feedback in DB contains dismissal_action and dismissal_comment
        dismissed = await service.db.get_dismissed_anomalies()
        assert len(dismissed) >= 1
        d_rec = next(d for d in dismissed if d["id"] == "anom-test-action-1")
        assert d_rec["dismissal_action"] == "resolved"
        assert "Scaled auth replica" in d_rec["dismissal_comment"]

        # Verify search_resolutions retrieves the saved knowledge
        matched = await service.vector_index.search_resolutions(
            "credential stuffing spike auth replica", top_k=3, min_score=0.1
        )
        assert len(matched) > 0
        assert "Scaled auth replica set" in matched[0]["text_content"]

    # 2. Action: False Positive on another anomaly -> should NOT index into resolution memory
    anomaly2 = AnomalyRecord(
        id="anom-test-action-2",
        application="order-service",
        environment="staging",
        template_id="tpl-action-2",
        template_text="Staging test transaction processed for <ID>",
        anomaly_type=AnomalyType.NEW_TEMPLATE,
        bucket_start=datetime.now(timezone.utc),
        current_count=10,
        baseline_count=0.0,
        status=AnomalyStatus.ACTIVE,
    )
    await service.db.insert_anomaly(anomaly2)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res2 = await client.post(
            "/api/anomalies/anom-test-action-2/dismiss",
            json={
                "action": "false_positive",
                "comment": "Automated regression pipeline load test.",
            }
        )
        assert res2.status_code == 200
        assert res2.json()["action"] == "false_positive"

        # Verify it does not show up in resolution memory search
        matched_fp = await service.vector_index.search_resolutions(
            "Automated regression pipeline load test", top_k=5, min_score=0.1
        )
        # The false positive comment should not be in resolution memory
        for m in matched_fp:
            assert "Automated regression pipeline load test" not in m["text_content"]

