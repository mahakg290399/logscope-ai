"""End-to-end integration verification test for LogScope AI."""

import asyncio
import os
import shutil
import sys
import time
from pathlib import Path

# Ensure src/ is on python path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import httpx

from logscope.config import Settings
from logscope.service import LogScopeService
from logscope.api.app import create_app


async def run_e2e_verification():
    test_dir = Path("./data/e2e_test")
    if test_dir.exists():
        shutil.rmtree(test_dir)
    test_dir.mkdir(parents=True, exist_ok=True)

    log_dir = test_dir / "logs"
    auth_dir = log_dir / "auth-service"
    auth_dir.mkdir(parents=True, exist_ok=True)
    auth_file = auth_dir / "auth.log"

    db_path = test_dir / "test_logscope.db"

    settings = Settings(
        LOGSCOPE_ENV="development",
        LOGSCOPE_DATA_DIR=str(test_dir),
        LOGSCOPE_DB_PATH=str(db_path),
        LOGSCOPE_KAFKA_EMBEDDED_FALLBACK=True,
        LOGSCOPE_AI_PROVIDER=os.getenv("LOGSCOPE_AI_PROVIDER", "heuristic"),
        LOGSCOPE_AI_BASE_URL=os.getenv("LOGSCOPE_AI_BASE_URL", None),
        OPENAI_API_KEY=os.getenv("OPENAI_API_KEY", ""),
        OPENAI_MODEL=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
    )

    service = LogScopeService(settings)
    app = create_app(service)

    print("1. Starting LogScope Service...")
    await service.start()

    print("2. Generating test log traffic...")
    for i in range(10):
        with open(auth_file, "a", encoding="utf-8") as f:
            f.write(
                f"2026-08-10 12:00:{i:02d} [INFO] auth-service: User account {1000+i} logged in successfully\n"
            )
            if i % 3 == 0:
                f.write(
                    f"2026-08-10 12:00:{i:02d} [FATAL] auth-service: Outage on primary Postgres cluster connection refused on port 5432\n"
                )
        await asyncio.sleep(0.1)

    print("3. Allowing ingestion, clustering, and anomaly triage loops to process...")
    await asyncio.sleep(2.0)

    print("4. Testing REST API endpoints...")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # Telemetry
        r = await client.get("/api/telemetry")
        assert r.status_code == 200
        telemetry = r.json()
        print(f"   -> Telemetry: {telemetry}")

        # Sources
        r = await client.get("/api/sources")
        assert r.status_code == 200
        sources = r.json()
        print(f"   -> Found {len(sources)} sources")

        # Templates
        r = await client.get("/api/templates")
        assert r.status_code == 200
        templates = r.json()
        print(f"   -> Found {len(templates)} templates")

        # Anomalies
        r = await client.get("/api/anomalies")
        assert r.status_code == 200
        anomalies = r.json()
        print(f"   -> Found {len(anomalies)} anomalies")

        # Ask AI
        r = await client.post("/api/ask", json={"query": "What errors occurred?"})
        assert r.status_code == 200
        ask_res = r.json()
        print(f"   -> Ask AI response: {ask_res.get('answer', '')[:100]}...")

    print("5. Stopping LogScope Service...")
    await service.stop()

    print("End-to-end integration verification completed successfully! [SUCCESS]")


if __name__ == "__main__":
    asyncio.run(run_e2e_verification())
