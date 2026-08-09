```markdown
# Product Requirements Document (PRD)
## Project Name: LogScope AI (Placeholder)
**Document Version:** 1.2 (Final) | **Date:** [Current Date] | **Author:** [Your Name]

### 1. Executive Summary
**LogScope AI** is an intelligent, real-time log analysis platform designed to eliminate log fatigue by acting as an automated SRE assistant. Built on the core principle that **"data should not be moved or read until absolutely required,"** the system uses stream-processing (Drain3) to condense millions of logs into lightweight templates. It then uses Large Language Models (LLMs) to synthesize these templates into human-readable narratives, providing instant alerts, daily health reports, and deep historical analysis without the need to query massive raw log databases. 

### 2. Problem Statement
*   **Log Overload:** Engineers spend hours filtering thousands of raw log lines in tools like Splunk to find a root cause.
*   **Gray Failures:** Silent errors that occur infrequently (e.g., once an hour) are missed by threshold-based monitoring but indicate critical systemic issues.
*   **Data Gravity & Costs:** Traditional tools ingest terabytes of raw logs centrally, resulting in massive storage and network egress costs.
*   **Loss of Context:** Engineers lack a "bigger picture" view of system health, struggling to connect the dots between multiple minor anomalies.

### 3. Core Architectural Principle: Data Locality
LogScope AI does not act as a raw log data lake. Raw logs remain in their source locations (Server disk, S3, etc.). LogScope only extracts **Templates, Statistics, and Metadata** (file path, line number, timestamp). The raw data is never moved or stored centrally. 

### 4. V1 Scope & Deployment Model
*   **Deployment:** V1 will run locally on the user's machine (e.g., developer laptop or a single dedicated local server). If local resources prove insufficient for processing live log volume, the architecture will seamlessly transition to cloud deployment in future phases.
*   **LLM Integration:** Cloud LLM via API (OpenAI/Anthropic). 
*   **Authentication & Security:** V1 uses **Bring Your Own Key (BYOK)**. The user inputs their own LLM API key into the local system. Self-hosted LLMs, advanced auth, and enterprise security are deferred to future phases.
*   **Traceability:** For V1, AI insights will provide simple textual references (e.g., `Source: /var/log/app/server.log, Line: 48273`). No clickable deep links to external systems will be built yet.

### 5. Core Product Features

**5.1. Pluggable Ingestion (Connectors)**
The system uses a pluggable architecture to ingest logs from various sources. The core engine remains agnostic to the log source.
*   *V1 Connector:* Local File Tail (reads live logs from a local file path).
*   *Future Connectors:* Fluent Bit/Kafka (live streaming), AWS S3 (batch/historical), Splunk API, CloudWatch.

**5.2. Real-Time Noise Reduction (Drain3)**
Raw logs are parsed in real-time. Millions of identical/similar logs are grouped into concise "Templates" (e.g., `Connection refused to <IP>`). The system stores the template, the count, and the metadata (host, timestamp, file path, line number), reducing data volume by 99%.

**5.3. Memory Horizon Management (Hot vs. Cold Memory)**
To mimic human memory and optimize LLM context windows, the system manages time horizons:
*   **Hot Memory (Last 7-30 Days):** Stored in a fast local database (e.g., SQLite for V1). Used for daily reports, live anomaly detection, and on-demand queries.
*   **Cold/Archive Memory (6+ Months):** Compressed and stored cheaply. Dropped from active context, but searchable via user-initiated queries (e.g., "Search the last 6 months for issues similar to this").

**5.4. AI Synthesis Engine (LLM Integration)**
The system queries the Memory DB and sends only condensed anomalies to the LLM. 
*   **Instant Alerts:** If a critical failure or completely new pattern emerges, the LLM analyzes it instantly and triggers an alert.
*   **Scheduled Reports (The Morning Report):** A daily summary explaining the "bigger picture" of system health over the last 24 hours.
*   **On-Demand Analysis:** Users can click "Analyze Now" in the UI for a plain-English status update.

### 6. System Architecture (V1 High-Level)

**6.1. Data Flow (Local Real-Time Path)**
1.  **Source:** Live Application generating logs to a local file.
2.  **Connector (V1):** Python-based file tailer (e.g., `pygtail` or `watchdog`) reads new lines.
3.  **Stream Processor (V1):** Python background process runs the Drain3 algorithm in-memory.
    *   Clusters logs into templates.
    *   Maintains statistical baselines (for spike detection).
    *   Writes templates, counts, and metadata to the Local Memory DB.
4.  **Memory DB (V1):** SQLite database storing Hot Memory (templates, counts, timestamps, file paths, line numbers).
5.  **AI Engine & API (V1):**
    *   Triggered by the processor (instant alerts) or a cron job (scheduled reports).
    *   Fetches condensed context from SQLite.
    *   Calls Cloud LLM API using the user's BYOK key.
6.  **Presentation (V1):** Local Web UI Dashboard (React or Flask) + terminal/CSV output for reports.

### 7. User Experience (UX)
*   **The Dashboard (V1 Focus):** A clean local web UI featuring "Active Anomalies," "System Health Score," and an "Ask AI" chat interface. Instead of raw logs, users see AI-generated narratives.
*   **The Morning Report:** 
    *   *Body:* "Yesterday was mostly stable. At 14:00, a new pattern emerged: 'DB Timeout on port 5432' (50 occurrences). No hard failures, but the DB was under stress. (Source: /var/log/app/server.log, Line: 10234)"
*   **Historical Search:** A search bar where users can ask, "Did we see a memory leak like this 6 months ago?" The system queries Cold Memory, feeds it to the LLM, and returns a summary.

### 8. Cost & Resource Management
*   **Zero LLM Cost for Baseline:** Statistical anomaly detection (new patterns, count spikes) runs purely in Python/SQLite, triggering the LLM *only* when an anomaly is found.
*   **Tiered LLM Strategy:** Cheap models (GPT-4o-mini) for classification; expensive models (GPT-4o) for deep narrative summaries.
*   **Storage Savings:** By not storing raw logs, local disk and memory usage remain extremely low.

### 9. Development Phases (Roadmap)
*   **Phase 1 (MVP - Local V1):** Python script tailing a local file -> Drain3 -> SQLite DB -> Simple Flask/React UI -> BYOK OpenAI API for summaries. Textual traceability (file path + line number).
*   **Phase 2 (Real-Time Engine):** Deploy Kafka + Flink + ClickHouse. Build Fluent Bit connector for live server deployments.
*   **Phase 3 (UI & Alerts):** Build full Web Dashboard. Implement Instant Alerts (Slack/Email) and Scheduled Reports.
*   **Phase 4 (Cold Memory & Scale):** Implement 6-month historical search. Add S3 and Splunk connectors. Add self-hosted LLM support and enterprise auth.
```