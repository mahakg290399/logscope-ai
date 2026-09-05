#!/usr/bin/env bash
set -euo pipefail

echo "============================================================"
echo "LogScope AI - Multi-Component Stack Deployment"
echo "============================================================"

# 1. Check prerequisites
command -v docker >/dev/null 2>&1 || { echo "[!] Docker is required but not installed. Aborting."; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "[!] Docker Compose v2 is required. Aborting."; exit 1; }

# 2. Check environment file
ENV_FILE=".env"
if [ ! -f "$ENV_FILE" ]; then
    if [ -f ".env.example" ]; then
        echo "[-] No .env file found. Copying .env.example -> .env..."
        cp .env.example .env
        echo "[!] Please review .env and set your NVIDIA_API_KEY before starting production traffic."
    else
        echo "[!] No .env or .env.example found. Aborting."; exit 1;
    fi
fi

# 3. Ensure required directories exist
mkdir -p ./data ./logs

# 4. Validate Compose configuration
echo "[-] Validating Docker Compose configuration..."
docker compose config >/dev/null

# 5. Build and start services
echo "[-] Building and launching LogScope stack (Kafka KRaft + App)..."
docker compose up -d --build

# 6. Wait for health check
echo "[-] Waiting for LogScope services to report healthy..."
MAX_RETRIES=30
RETRY_COUNT=0
HEALTHY=0

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    if curl -fsS http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
        HEALTHY=1
        break
    fi
    RETRY_COUNT=$((RETRY_COUNT + 1))
    echo "    Waiting for services... ($RETRY_COUNT/$MAX_RETRIES)"
    sleep 3
done

if [ $HEALTHY -eq 1 ]; then
    echo "============================================================"
    echo "[SUCCESS] LogScope AI stack is up and running!"
    echo "Dashboard URL: http://127.0.0.1:8000"
    echo "Health Check : http://127.0.0.1:8000/api/health"
    echo "Telemetry    : http://127.0.0.1:8000/api/telemetry"
    echo "============================================================"
else
    echo "[!] Timed out waiting for LogScope health endpoint. Checking logs:"
    docker compose logs --tail 30
    exit 1
fi
