"""FastAPI Application exposing REST API and Dashboard for LogScope AI."""

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional, Dict, Any, List
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from logscope.config import Settings, get_settings
from logscope.service import LogScopeService
from logscope.models import FeedbackRecord, AnomalyStatus

logger = logging.getLogger(__name__)


class LogIngestRequest(BaseModel):
    application: str
    environment: str
    logs: List[Any]
    source_name: Optional[str] = "http-ingest"


class DismissRequest(BaseModel):
    comment: Optional[str] = None
    action: str = "dismiss"


class AskAIRequest(BaseModel):
    query: str


def create_app(
    settings: Optional[Any] = None,
    service: Optional[LogScopeService] = None,
) -> FastAPI:
    # If a LogScopeService instance was passed as the first positional argument
    if isinstance(settings, LogScopeService):
        service = settings
        settings = service.settings
    elif service is not None:
        settings = service.settings
    else:
        settings = settings or get_settings()
        service = LogScopeService(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await service.start()
        try:
            yield
        finally:
            await service.stop()

    app = FastAPI(title="LogScope AI", version="2.0.0", lifespan=lifespan)

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            f"http://localhost:{settings.port}",
            f"http://127.0.0.1:{settings.port}",
        ],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.state.service = service
    app.state.settings = settings

    @app.get("/api/health")
    async def health_check():
        return {"status": "ok", "version": "2.0.0", "env": settings.env}

    @app.post("/api/logs/ingest")
    @app.post("/api/logs")
    async def ingest_logs(
        request: Request,
        application: Optional[str] = None,
        environment: Optional[str] = None,
        source_name: Optional[str] = None,
    ):
        """High-throughput HTTP endpoint for cloud log shippers (Fluent Bit, Vector, CloudWatch, curl).

        Accepts:
        1. Standard format: `{"application": "...", "environment": "...", "logs": [...]}`
        2. Fluent Bit JSON Array: `[{"log": "...", "application": "..."}, ...]`
        3. Single log object: `{"log": "...", "application": "..."}`
        """
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON payload")

        logs_list: List[Any] = []
        app_name = application
        env_name = environment
        src_name = source_name or "http-ingest"

        if isinstance(body, dict):
            if "logs" in body and isinstance(body["logs"], list):
                logs_list = body["logs"]
                app_name = body.get("application") if "application" in body else application
                env_name = body.get("environment") if "environment" in body else environment
                src_name = body.get("source_name") or src_name
                if not (app_name or "").strip() or not (env_name or "").strip():
                    raise HTTPException(status_code=400, detail="Fields 'application' and 'environment' are required")
            else:
                logs_list = [body]
                app_name = body.get("application") or body.get("app") or application or "default-app"
                env_name = body.get("environment") or body.get("env") or environment or settings.env
                src_name = body.get("source_name") or src_name
        elif isinstance(body, list):
            logs_list = body
            if logs_list and isinstance(logs_list[0], dict):
                first = logs_list[0]
                app_name = application or first.get("application") or first.get("app") or "fluent-bit"
                env_name = environment or first.get("environment") or first.get("env") or settings.env
                src_name = src_name or first.get("source_name") or "fluent-bit"
        else:
            raise HTTPException(status_code=400, detail="Payload must be a JSON object or array")

        app_name = (app_name or "default-app").strip()
        env_name = (env_name or settings.env).strip()

        if not logs_list:
            return {"status": "ok", "ingested": 0, "application": app_name, "environment": env_name}

        count = await service.ingest_lines(
            application=app_name,
            environment=env_name,
            lines=logs_list,
            source_name=src_name,
        )
        return {
            "status": "accepted",
            "ingested": count,
            "application": app_name,
            "environment": env_name,
        }

    @app.get("/api/telemetry")
    async def get_telemetry():
        metrics = service.get_telemetry()
        # Enrich with live DB counts
        active_anomalies = await service.db.get_active_anomalies()
        templates = await service.db.get_all_templates(limit=1000)
        metrics.active_anomalies_count = len(active_anomalies)
        metrics.templates_count = len(templates)
        return metrics

    @app.get("/api/sources")
    async def get_sources():
        return await service.db.get_all_sources()

    @app.get("/api/templates")
    async def get_templates(limit: int = 100):
        return await service.db.get_all_templates(limit=limit)

    @app.get("/api/templates/{template_id}")
    async def get_template_details(template_id: str):
        """Return one template with its recent buckets and sanitized samples."""
        template = await service.db.get_template(template_id)
        if template is None:
            raise HTTPException(status_code=404, detail="Template not found")
        return {
            "template": template.model_dump(mode="json"),
            "history": await service.db.get_template_history(template_id),
            "samples": await service.db.get_samples_for_template(template_id),
        }

    @app.get("/api/buckets/timeline")
    async def get_bucket_timeline(limit: int = 30):
        return await service.db.get_recent_bucket_timeline(limit=limit)

    @app.get("/api/anomalies")
    @app.get("/api/anomalies/active")
    async def get_active_anomalies():
        return await service.db.get_active_anomalies()

    @app.get("/api/anomalies/dismissed")
    async def get_dismissed_anomalies(limit: int = 50):
        return await service.db.get_dismissed_anomalies(limit=limit)

    @app.post("/api/anomalies/{anomaly_id}/dismiss")
    async def dismiss_anomaly(anomaly_id: str, req: DismissRequest):
        anomaly = await service.db.get_anomaly(anomaly_id)
        if not anomaly:
            raise HTTPException(status_code=404, detail="Anomaly not found")

        feedback = FeedbackRecord(
            anomaly_id=anomaly_id,
            action=req.action,
            comment=req.comment
        )
        await service.db.insert_feedback(feedback)
        if req.action in {"resolved", "resolve", "dismiss"} and req.comment and req.comment.strip():
            await service.record_incident_resolution(anomaly_id, req.comment, req.action)
        return {"status": "dismissed", "action": req.action, "anomaly_id": anomaly_id}

    @app.post("/api/anomalies/{anomaly_id}/retry")
    async def retry_anomaly(anomaly_id: str):
        anomaly = await service.db.get_anomaly_record(anomaly_id)
        if not anomaly:
            raise HTTPException(status_code=404, detail="Anomaly not found")

        try:
            analysis = await service.ai_worker.analyze_anomaly(anomaly)
            return {"status": "retried", "analysis": analysis.model_dump(mode="json")}
        except Exception as exc:
            logger.exception("Retry triage failed for anomaly %s", anomaly_id)
            raise HTTPException(status_code=500, detail=f"Retry triage failed: {exc}") from exc


    @app.post("/api/ask")
    @app.post("/api/ask-ai")
    async def ask_ai(req: AskAIRequest):
        res = await service.ai_worker.ask_ai(req.query)
        return res

    @app.get("/api/stream")
    async def telemetry_stream(request: Request):
        """SSE stream pushing live dashboard telemetry every 2 seconds."""
        async def event_generator():
            while True:
                if await request.is_disconnected():
                    break
                metrics = service.get_telemetry()
                active_anomalies = await service.db.get_active_anomalies()
                templates = await service.db.get_all_templates(limit=10)
                payload = {
                    "metrics": metrics.model_dump(mode="json"),
                    "active_anomalies": active_anomalies,
                    "recent_templates": templates
                }
                yield f"data: {json.dumps(payload)}\n\n"
                await asyncio.sleep(2.0)

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    # Serve static dashboard UI
    @app.get("/", response_class=HTMLResponse)
    async def serve_dashboard():
        html_file = Path(__file__).parent.parent / "web" / "index.html"
        if html_file.exists():
            return HTMLResponse(content=html_file.read_text(encoding="utf-8"))
        return HTMLResponse("<h1>LogScope AI</h1><p>Dashboard UI not found.</p>")

    return app
