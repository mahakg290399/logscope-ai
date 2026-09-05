# LogScope AI - Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code and default configs
COPY src/ ./src/
COPY sources.example.yaml ./sources.yaml
COPY main.py .

# Expose API/Dashboard port
EXPOSE 8000

# Environment defaults
ENV LOGSCOPE_ENV=production
ENV LOGSCOPE_HOST=0.0.0.0
ENV LOGSCOPE_PORT=8000
ENV PYTHONPATH=/app/src

# Healthcheck
HEALTHCHECK --interval=20s --timeout=5s --retries=3 --start-period=10s \
    CMD curl -fsS http://localhost:8000/api/health || exit 1

CMD ["python", "main.py", "--host", "0.0.0.0", "--port", "8000"]
