"""Tests for FastAPI REST Endpoints and Services."""

import pytest
import httpx
from logscope.config import Settings
from logscope.api.app import create_app


@pytest.mark.asyncio
async def test_api_endpoints(test_settings: Settings):
    app = create_app(test_settings)
    
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # 1. Health check
        res = await client.get("/api/health")
        assert res.status_code == 200
        assert res.json()["status"] == "ok"

        # 2. Telemetry
        res_tel = await client.get("/api/telemetry")
        assert res_tel.status_code == 200
        data = res_tel.json()
        assert "ingestion_rate_lps" in data
        assert "kafka_consumer_lag" in data

        # 3. Active anomalies
        res_anom = await client.get("/api/anomalies/active")
        assert res_anom.status_code == 200
        assert isinstance(res_anom.json(), list)

        # 4. Ask AI
        res_ask = await client.post("/api/ask-ai", json={"query": "Any database errors reported?"})
        assert res_ask.status_code == 200
        assert "answer" in res_ask.json()

        # 5. Bucket Timeline (Phase 5)
        res_timeline = await client.get("/api/buckets/timeline")
        assert res_timeline.status_code == 200
        assert isinstance(res_timeline.json(), list)

        # 6. Dashboard HTML serving
        res_dashboard = await client.get("/")
        assert res_dashboard.status_code == 200
        assert "LogScope AI" in res_dashboard.text
        assert "timelineChart" in res_dashboard.text
        assert "templateDetailModal" in res_dashboard.text

        # 7. HTTP Log Ingestion (Cloud forwarders / Fluent Bit / Vector)
        res_ingest = await client.post(
            "/api/logs/ingest",
            json={
                "application": "checkout-service",
                "environment": "cloud-prod",
                "logs": [
                    "2026-09-05 23:45:00 [INFO] Payment intent created for order 9812",
                    "2026-09-05 23:45:01 [ERROR] Gateway timeout on stripe provider with card 4111-2222-3333-4444",
                    {"timestamp": "2026-09-05T23:45:02Z", "level": "WARN", "message": "Circuit breaker open for stripe"},
                ]
            }
        )
        assert res_ingest.status_code == 200
        ingest_data = res_ingest.json()
        assert ingest_data["status"] == "accepted"
        assert ingest_data["ingested"] == 3
        assert ingest_data["application"] == "checkout-service"

        # Validation test: missing application
        res_bad = await client.post(
            "/api/logs/ingest",
            json={"application": "", "environment": "prod", "logs": ["log line"]}
        )
        assert res_bad.status_code == 400

        # 8. Fluent Bit Array format ingestion
        res_flb = await client.post(
            "/api/logs",
            json=[
                {"log": "Worker starting up", "application": "flb-app", "environment": "prod"},
                {"log": "Listening on port 8080", "application": "flb-app", "environment": "prod"}
            ]
        )
        assert res_flb.status_code == 200
        assert res_flb.json()["status"] == "accepted"
        assert res_flb.json()["ingested"] == 2
        assert res_flb.json()["application"] == "flb-app"
