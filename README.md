# LogScope AI

**Enterprise SRE Log Aggregation, Anomaly Detection & AI Incident Triager (POC v2.0)**

LogScope AI treats application logs as an application heartbeat. It continuously monitors logs from multiple services, reduces repetitive volume into templates and time-bucketed statistics using Drain3, detects deterministic anomalies (new patterns, frequency spikes, error bursts), and leverages LLMs as an SRE copilot to assess and triage incidents with precision.

---

## Architecture Overview

```text
Local Log Files (Read-Only)
  │
  ▼
File Tailer & Multiline Assembler
  │
  ▼
Redactor & Pseudonymizer (PII / Secrets / Tokens stripped)
  │
  ▼
Drain3 Template Mining Engine
  │
  ▼
[ Sanitization Boundary ]
  │
  ▼
Sanitized Kafka Stream Backbone (logscope.template-observations)
  │
  ▼
5-Minute Bucket Aggregator & Deterministic Anomaly Detector
  │
  ▼
SQLite Database (WAL Mode) + Local Vector Semantic Index
  │
  ▼
Asynchronous OpenAI SRE Worker (Severity Sev-0..Sev-4, Prompt-Injection Protected)
  │ (Direct OpenAI chat + embedding APIs)
  ▼
FastAPI Server & Real-time Live Dashboard (SSE + REST)
```

---

## Quickstart

### Option 1: Run Locally (Python)

1. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure Environment & Sources**:
   ```bash
   copy .env.example .env
   copy sources.example.yaml sources.yaml
   ```

3. **Run LogScope AI**:
   ```bash
   python main.py
   ```
   Open your browser to: **[http://localhost:8000](http://localhost:8000)**

4. **(Optional) Simulate Live Traffic**:
   In another terminal:
   ```bash
   python scripts/simulate_traffic.py
   ```

---

### Option 2: Run with Docker Compose

```bash
docker-compose up --build
```
LogScope AI will start with a local Apache Kafka broker in KRaft mode and mount configured host logs in read-only mode (`:ro`).

### Option 3: Public Oracle Always Free showcase

The repository includes an Oracle deployment with a realistic demo workload. It
runs Kafka, LogScope, the demo application, and Caddy on one VM; Kafka and the
application remain private and only HTTPS is exposed publicly.

See [`deploy/oracle/README.md`](deploy/oracle/README.md) for OCI dynamic groups,
least-privilege Secret Management policy, instance-principal retrieval, and the
VM startup commands. API keys are retrieved at runtime from OCI Secret Management;
they are not stored in GitHub, Docker images, browser code, or a committed `.env`.

The demo service writes realistic authentication, payment, order, timeout, and
database-pool logs to a shared volume so the public dashboard demonstrates the
actual ingestion → sanitization → Kafka → anomaly → AI workflow.

---

## Running the Test Suite

Execute the full unit and integration test suite:

```bash
python -m pytest -v
```

---

## Key Features

- **Pre-Kafka Sanitization Boundary**: Raw logs and sensitive tokens (passwords, JWTs, Bearer tokens, API keys, emails, IPs, credit cards, UUIDs) are redacted before streaming.
- **Drain3 Template Clustering**: Groups repetitive log lines into generalized templates with extracted dynamic parameters.
- **5-Minute Bucket Aggregation**: Aligned time-window statistical rollups stored in SQLite with WAL mode.
- **Deterministic Anomaly Detection**:
  - `NEW_TEMPLATE`: First appearance of unseen template patterns.
  - `FREQUENCY_SPIKE`: Dynamic z-score statistical surge against baseline.
  - `ERROR_BURST`: Sudden error clusters.
- **AI SRE Copilot & Prompt Safety**: Untrusted log data protection, structured JSON output (`Sev-0` to `Sev-4`, five confidence levels, root causes, recommended actions), OpenAI embeddings, and historical similarity lookup.
- **Kafka streaming boundary**: Docker mode publishes and consumes sanitized events through Kafka. The in-memory stream is only an explicit test fallback.
- **Interactive Local Dashboard**: Real-time KPI telemetry, active incident triage feed, dismiss feedback loop, and Ask AI interactive chat.
