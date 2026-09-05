# LogScope AI

<p align="center">
  <strong>Autonomous SRE Log Intelligence, Online Template Mining & AI Incident Triaging Platform</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%20%7C%203.11%20%7C%203.12-3776AB?logo=python&logoColor=white" alt="Python Version" />
  <img src="https://img.shields.io/badge/Docker-Ready-2496ED?logo=docker&logoColor=white" alt="Docker Ready" />
  <img src="https://img.shields.io/badge/Apache%20Kafka-KRaft%20Mode-231F20?logo=apachekafka&logoColor=white" alt="Kafka KRaft" />
  <img src="https://img.shields.io/badge/AI%20Providers-NVIDIA%20NIM%20%7C%20OpenAI%20%7C%20Gemini-76B900?logo=nvidia&logoColor=white" alt="AI Providers" />
  <img src="https://img.shields.io/badge/Tests-34%20Passing-brightgreen" alt="Tests Status" />
  <img src="https://img.shields.io/badge/License-Apache%202.0-blue.svg" alt="License" />
</p>

---

## What is LogScope AI?

Modern microservice architectures generate millions of repetitive log lines per minute. SRE and DevOps engineers face high storage costs, alert fatigue, and slow mean-time-to-resolution (MTTR) during critical outages.

**LogScope AI** solves this by treating logs as an **application heartbeat**:
1. **Redacts PII & Secrets**: Masks passwords, tokens, API keys, IPs, and credit cards before data ever leaves memory.
2. **Compresses Repetitive Noise**: Employs **Drain3 online template clustering** to distill millions of raw lines into unique structural templates in real time.
3. **Detects Deterministic Anomalies**: Flags new failure patterns, dynamic statistical frequency surges (z-score $\ge 3.0$), and error bursts in synchronized 5-minute buckets.
4. **Autonomously Triages Incidents with AI**: Coordinates an asynchronous SRE Copilot powered by **NVIDIA NIM**, **OpenAI**, or **Google Gemini** to formulate root-cause hypotheses, severity ratings (`Sev-0` to `Sev-4`), and actionable mitigation steps.
5. **Preserves Organizational Incident Memory**: Captures operator remediation feedback and embeds it into a local semantic vector store for instant recall when similar failures reoccur.

---

## System Architecture

```
                  ┌────────────────────────────────────────────────────────┐
                  │              Ingestion Gateways (5 Modes)             │
                  │  • File Tailer   • HTTP REST Ingest  • Fluent Bit Node │
                  │  • Kafka Topic   • CloudWatch / Lambda Forwarder       │
                  └───────────────────────────┬────────────────────────────┘
                                              │
                                              ▼
                  ┌────────────────────────────────────────────────────────┐
                  │             Pre-Stream Sanitization Boundary           │
                  │  • PII / Secrets / Auth Token Masking & Hashing        │
                  │  • Drain3 Online Template Mining & Param Extraction    │
                  └───────────────────────────┬────────────────────────────┘
                                              │ Sanitized Observations
                                              ▼
                  ┌────────────────────────────────────────────────────────┐
                  │           Apache Kafka Backbone (KRaft Consensus)      │
                  │  • logscope.template-observations                      │
                  │  • logscope.anomaly-jobs                               │
                  │  • logscope.analysis-results                           │
                  └───────────────────────────┬────────────────────────────┘
                                              │
                                              ▼
                  ┌────────────────────────────────────────────────────────┐
                  │            5-Minute Statistical Aggregator             │
                  │  • Deterministic Anomaly Rules (New, Spikes, Bursts)   │
                  │  • SQLite WAL Persistent Time-Series Storage           │
                  └───────────────────────────┬────────────────────────────┘
                                              │
                                              ▼
                  ┌────────────────────────────────────────────────────────┐
                  │         Multi-Provider AI SRE Copilot & Memory         │
                  │  • NVIDIA NIM / OpenAI / Gemini / Heuristic Fallback   │
                  │  • Prompt Injection Defense Layer                      │
                  │  • Cosine Vector Index for Historical Incident Memory  │
                  └───────────────────────────┬────────────────────────────┘
                                              │
                                              ▼
                  ┌────────────────────────────────────────────────────────┐
                  │             FastAPI Backend & SRE Console              │
                  │  • Live SSE Telemetry Feed   • Interactive Timeline   │
                  │  • Incident Resolution Modal  • Interactive "Ask AI"   │
                  └────────────────────────────────────────────────────────┘
```

---

## Core Product Capabilities

* **Pre-Kafka Sanitization Boundary**: Raw logs are cleaned in-memory. Regex masks API keys, Bearer tokens, JWTs, emails, IPv4/IPv6, credit cards, and UUIDs before reaching storage or network brokers.
* **Drain3 Template Mining**: Clusters unstructured log messages into structural templates on the fly (e.g. `Connection timed out to redis://<*> after <*> ms`) and extracts variable parameters.
* **Deterministic Anomaly Engine**:
  * `NEW_TEMPLATE`: Instantly flags unprecedented log signatures appearing for the first time in production.
  * `FREQUENCY_SPIKE`: Computes statistical z-scores against rolling historical baselines to identify sudden traffic or error surges.
  * `ERROR_BURST`: Tracks concentrated clusters of `ERROR` or `CRITICAL` logs in 5-minute aligned windows.
* **Multi-Provider AI Triage**:
  * **NVIDIA NIM** (e.g. `nemotron-3.5-lightning-30b-a3b` + `llama-3.2-nv-embedqa-1b-v1`).
  * **OpenAI** (e.g. `gpt-4o-mini`).
  * **Google Gemini** (e.g. `gemini-2.0-flash`).
  * **Offline Heuristic Engine**: Deterministic fallback ensuring 100% operational uptime if LLM keys are absent or network is degraded.
* **Organizational Incident Memory**: When an SRE resolves an incident, LogScope captures the operator's fix notes and indexes them into the vector database. Future similar anomalies automatically retrieve past remediation playbooks.
* **Live SRE Command Center**: A modern, dark-mode real-time dashboard featuring:
  * Live KPI telemetry (ingestion LPS, consumer lag, anomaly counts).
  * 5-minute bucket volume and error timeline charts.
  * Triage cards with AI confidence, root cause, and remediation recommendations.
  * Natural language **"Ask AI"** assistant for conversational log troubleshooting.

---

## Quickstart Guide

### Method A: Docker Compose (Recommended for Production & Cloud)

The fastest and most robust way to run LogScope AI with Apache Kafka (KRaft mode, no ZooKeeper):

1. **Clone the repository**:
   ```bash
   git clone https://github.com/your-org/logscope-ai.git
   cd logscope-ai
   ```

2. **Configure your environment**:
   ```bash
   cp .env.example .env
   cp sources.example.yaml sources.yaml
   ```
   *Edit `.env` to configure your chosen AI provider (e.g. `NVIDIA_API_KEY` or `OPENAI_API_KEY`).*

3. **Start the stack**:
   ```bash
   docker compose up -d --build
   ```

4. **Access the Console**:
   * Open **[http://localhost:8000](http://localhost:8000)** in your browser.
   * Telemetry health: `http://localhost:8000/api/health`

5. **(Optional) Start the Fluent Bit collector node**:
   ```bash
   docker compose --profile collector up -d
   ```

---

### Method B: Local Development Setup (Python venv)

For rapid local testing and development:

1. **Create and activate a virtual environment**:
   ```bash
   python -m venv .venv
   # Windows:
   .venv\Scripts\activate
   # Linux/macOS:
   source .venv/bin/activate
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure environment**:
   ```bash
   cp .env.example .env
   cp sources.example.yaml sources.yaml
   ```
   *In `.env`, set `LOGSCOPE_KAFKA_EMBEDDED_FALLBACK=true` to run without a local Kafka broker.*

4. **Launch LogScope AI**:
   ```bash
   python main.py
   ```
   Open **[http://localhost:8000](http://localhost:8000)**.

5. **Simulate Live Traffic & Incidents**:
   In a separate terminal, trigger realistic traffic with simulated error bursts:
   ```bash
   python scripts/simulate_traffic.py
   ```

---

## 5 Ways to Ingest & Monitor Logs

LogScope AI is designed to integrate into any cloud or on-premise infrastructure:

### 1. Local & Host File Tailing (`sources.yaml`)
Monitor active log files on host machines or shared volumes:

```yaml
sources:
  - id: payment-api
    name: Payment Gateway API
    application: payment-service
    environment: production
    path: /var/log/app/*.log
    multiline:
      pattern: '^\d{4}-\d{2}-\d{2}'
      negate: true
      match: after
```

---

### 2. High-Throughput HTTP REST API
Push logs directly from microservices, CI/CD pipelines, or custom curl scripts:

* **Endpoint**: `POST /api/logs/ingest` (or `POST /api/logs`)
* **Batch Request Format**:
  ```bash
  curl -X POST http://localhost:8000/api/logs/ingest \
    -H "Content-Type: application/json" \
    -d '{
      "application": "checkout-service",
      "environment": "production",
      "logs": [
        "2026-09-06 00:00:01 [INFO] Order #9812 placed successfully",
        "2026-09-06 00:00:02 [ERROR] Payment gateway timeout on stripe provider",
        {"timestamp": "2026-09-06T00:00:03Z", "level": "WARN", "message": "High memory warning"}
      ]
    }'
  ```

---

### 3. Node-Level Agent: Fluent Bit
Use the included production Fluent Bit daemon for high-throughput container and system log collection:

* Pre-configured files in [`deploy/fluent-bit/`](deploy/fluent-bit/):
  * `fluent-bit.conf`: High-performance configuration with disk backpressure buffers.
  * `parsers.conf`: Custom parsers for Docker, Containerd, Syslog, Java, and Python multiline stack traces.
* **Run via Compose**:
  ```bash
  docker compose --profile collector up -d
  ```
* **Kubernetes DaemonSet**: See [`deploy/fluent-bit/README.md`](deploy/fluent-bit/README.md).

---

### 4. Direct Kafka Raw Topic Ingestion
Stream logs directly from enterprise message brokers (e.g. AWS MSK, Confluent Cloud, or LogScope's Kafka cluster):

1. Set the raw topic environment variable in `.env`:
   ```ini
   LOGSCOPE_KAFKA_TOPIC_RAW_LOGS=logscope.raw-logs
   ```
2. Any microservice or forwarder publishing plain text or JSON logs to `logscope.raw-logs` will be automatically consumed, sanitized, and clustered by LogScope AI.

---

### 5. AWS CloudWatch & Serverless Forwarder
Stream logs in real time from AWS CloudWatch Log Groups:

* Pre-built zero-dependency AWS Lambda forwarder in [`deploy/cloudwatch/lambda_function.py`](deploy/cloudwatch/lambda_function.py).
* Automatically decompresses CloudWatch base64 gzip events and streams them via HTTPS.
* **1-Click SAM Deployment**:
  ```bash
  sam deploy --guided --template-file deploy/cloudwatch/template.yaml
  ```
* See [`deploy/cloudwatch/README.md`](deploy/cloudwatch/README.md) for step-by-step subscription filter attachment.

---

## Configuration Reference

Key settings configurable via `.env` or system environment variables:

| Variable | Default | Description |
| :--- | :--- | :--- |
| `LOGSCOPE_ENV` | `development` | Deployment environment name (`production`, `staging`, `development`) |
| `LOGSCOPE_PORT` | `8000` | HTTP port for the web dashboard and REST API |
| `LOGSCOPE_HOST` | `127.0.0.1` | Bind address (`0.0.0.0` in Docker) |
| `LOGSCOPE_DATA_DIR` | `./data` | Directory for persistent database and vector index |
| `LOGSCOPE_DB_PATH` | `./data/logscope.db` | Path to SQLite WAL database |
| `LOGSCOPE_SOURCES_CONFIG`| `./sources.yaml` | Path to declarative log sources YAML config |
| `LOGSCOPE_KAFKA_BOOTSTRAP_SERVERS` | `localhost:9092` | Kafka broker connection string (e.g. `kafka:29092`) |
| `LOGSCOPE_KAFKA_EMBEDDED_FALLBACK` | `false` | Set `true` for local Python development without Kafka |
| `LOGSCOPE_KAFKA_TOPIC_RAW_LOGS` | `None` | Optional topic name for direct Kafka raw log ingestion |
| `LOGSCOPE_AI_PROVIDER` | `nvidia` | Active AI provider (`nvidia`, `openai`, `gemini`, `omniroute`, `auto`) |
| `NVIDIA_API_KEY` | `None` | NVIDIA NIM API key (`nvapi-...`) |
| `NVIDIA_MODEL` | `nvidia/nemotron-3.5-lightning-30b-a3b` | NVIDIA NIM chat model identifier |
| `NVIDIA_EMBEDDING_MODEL` | `nvidia/llama-3.2-nv-embedqa-1b-v1` | NVIDIA NIM embedding model identifier |
| `OPENAI_API_KEY` | `None` | OpenAI API key (`sk-...`) |
| `OPENAI_MODEL` | `gpt-4o-mini` | OpenAI chat model identifier |
| `GEMINI_API_KEY` | `None` | Google AI Studio API key |
| `LOGSCOPE_SAMPLE_RETENTION_HOURS` | `24` | Raw log sample retention period |
| `LOGSCOPE_AGGREGATE_RETENTION_MONTHS` | `6` | 5-minute statistical aggregate retention period |

---

## REST API Reference

LogScope exposes clean, well-documented REST APIs:

* `GET /api/health` — Service readiness probe and Kafka connectivity status.
* `GET /api/telemetry` — Live KPIs (LPS, dropped events, consumer lag, active anomaly count).
* `POST /api/logs/ingest` — Ingest raw log batches (accepts LogScope JSON and Fluent Bit arrays).
* `GET /api/anomalies/active` — Retrieve currently active anomalies requiring SRE triage.
* `POST /api/anomalies/{id}/feedback` — Close or resolve an alert (`resolved`, `false_alarm`, `transient`) with operator fix notes.
* `GET /api/buckets/timeline` — Recent 5-minute bucket volume and error rates for charting.
* `GET /api/templates` — Catalog of discovered Drain3 log templates and occurrence frequencies.
* `POST /api/ask-ai` — Natural language question answering over recent incidents and logs.

---

## Testing & Verification

LogScope AI maintains strict test coverage across all subsystems:

```bash
# Run the entire test suite
python -m pytest -v
```

* **Sanitizer & Redactor Tests**: Verifies PII masking, token pseudonymization, and deterministic sample hashing.
* **Drain3 Clustering Tests**: Tests dynamic parameter extraction and template novelty isolation.
* **Direct Kafka Ingestion Tests**: Verifies raw string and JSON consumption through Kafka queues.
* **CloudWatch Lambda Tests**: Tests base64 gzip stream decompression and HTTP payload forwarding.
* **AI Provider & Prompt Safety Tests**: Verifies structured JSON output, prompt injection defense, and NVIDIA NIM integration.
* **Storage & Retention Tests**: Tests SQLite WAL persistence, concurrent writes, and automated retention cleanup.

---

## Production Deployment Checklist

1. [ ] **Set Production Environment**: `LOGSCOPE_ENV=production` in `.env`.
2. [ ] **Configure AI Provider Key**: Add valid `NVIDIA_API_KEY` or `OPENAI_API_KEY`.
3. [ ] **Mount Persistent Storage**: Ensure named volumes `logscope_data` and `kafka_data` are persisted.
4. [ ] **Configure Log Ingestion**: Tail local paths in `sources.yaml`, start Fluent Bit (`--profile collector`), or point CloudWatch Subscription Filters to the Lambda forwarder.
5. [ ] **Secure Dashboard**: For public exposure, front LogScope with a reverse proxy like Caddy or Nginx with TLS termination (see [`deploy/oracle/`](deploy/oracle/)).

---

## License

This project is licensed under the Apache 2.0 License - see the [LICENSE](LICENSE) file for details.
