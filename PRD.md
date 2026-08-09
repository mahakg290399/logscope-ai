# Product Requirements Document: LogScope AI

**Document version:** 2.0
**Status:** POC specification and production-direction draft
**Date:** 2026-08-10
**Project name:** LogScope AI

## 1. Executive summary

LogScope AI is an enterprise-oriented SRE platform that treats application logs as an application heartbeat. It continuously monitors logs from multiple services, reduces repetitive log volume into templates and time-bucketed statistics, detects unusual behavior, and uses OpenAI models to explain whether the behavior is worth investigating.

The product has two explicitly different targets:

1. **POC:** a single-user localhost application running in Docker on Windows or Linux. It reads multiple local log files, uses Kafka as the local streaming backbone, stores summarized data in SQLite, and provides a local dashboard.
2. **Production direction:** distributed source-side collectors, S3 and other connectors, central Kafka, scalable storage, authentication, multi-tenancy, alert integrations, and enterprise security.

The POC must validate the core value proposition without moving raw logs into Kafka or OpenAI.

## 2. Problem statement

Organizations generate large volumes of logs across multiple services. Engineers must manually inspect repetitive messages, correlate events across sources, detect warnings before they become failures, and investigate incidents that may be visible only when several seemingly minor patterns are considered together.

LogScope AI addresses this by:

- grouping similar log messages into templates;
- retaining counts, timestamps, source references, and bounded samples;
- detecting deterministic anomalies such as new patterns and frequency spikes;
- correlating related anomalies across services in the same application and environment;
- using an LLM as an SRE assistant to assess whether the evidence deserves investigation;
- supporting natural-language explanations and historical similarity search;
- reducing the amount of data stored and sent to AI services.

## 3. Goals

### 3.1 POC goals

- Process multiple local log files at approximately 1,000 lines per second.
- Support Windows and Linux through Docker.
- Use Kafka in the POC streaming pipeline.
- Never send raw log lines to Kafka or OpenAI.
- Parse plain-text, JSON, and multiline logs where possible without failing when optional fields are absent.
- Group events with Drain3 per application and environment.
- Aggregate data into five-minute buckets.
- Detect useful real-time anomalies within approximately 30 seconds.
- Use OpenAI embeddings for historical similarity search.
- Use an OpenAI reasoning/chat model for anomaly analysis and explanations.
- Display active anomalies, evidence, analysis, severity, confidence, and dismissed items in a localhost dashboard.
- Retain aggregate data and embeddings for six months.
- Delete raw and redacted samples after 24 hours.
- Measure detection time, explanation time, and false-positive rate.

### 3.2 Production goals

- Collect logs near their source through deployable collectors.
- Support S3 and other ingestion connectors.
- Scale Kafka, processing, storage, and AI workers independently.
- Support multiple users, authentication, authorization, auditability, and enterprise security.
- Provide external alerting and deployment integrations.

## 4. Non-goals for the POC

The following are intentionally excluded from the POC implementation:

- Missing-heartbeat or missing-template detection.
- Authentication and multi-user access.
- Remote source-side collectors.
- S3 ingestion implementation.
- Cloud deployment and high availability.
- Slack, email, PagerDuty, or other external alert delivery.
- Production secret management.
- HMAC-based pseudonymization.
- Permanent raw-log storage.
- Permanent redacted-sample storage.
- Full enterprise compliance controls.

The POC must preserve interfaces and data contracts so these capabilities can be added later.

## 5. Users and primary workflows

### 5.1 Primary user

The primary long-term user is an SRE monitoring several services belonging to the same application or application group in a specific environment.

The POC user is a single local user operating the system through a localhost web dashboard.

### 5.2 Primary workflow: real-time monitoring

1. The user configures multiple local log files.
2. Each source is assigned a required application and environment.
3. The collector tails new log entries.
4. The collector parses, redacts, pseudonymizes, and groups events with Drain3.
5. Sanitized template observations are published to Kafka.
6. The processor aggregates observations into five-minute buckets.
7. Deterministic rules identify candidate anomalies.
8. Related anomalies are grouped into configurable AI batches.
9. OpenAI analyzes the summarized evidence and returns structured findings.
10. The dashboard displays the finding, evidence, severity, confidence, and recommended next steps.

### 5.3 Primary workflow: historical analysis

1. The user asks a natural-language question in the dashboard.
2. The system creates an embedding for the question.
3. The system retrieves semantically similar templates, anomaly records, and incident summaries from the retained six-month index.
4. The system sends only summarized and redacted context to the reasoning model.
5. The response includes evidence references and clearly indicates when evidence is insufficient.

## 6. Source and metadata requirements

### 6.1 POC source scope

The POC implements local file ingestion. It must support multiple files concurrently.

The local connector should support:

- plain-text logs;
- JSON logs;
- multiline records such as stack traces;
- timestamps when present;
- records without timestamps;
- file rotation and truncation;
- local compressed files as batch input where practical.

Live tailing is required for normal files. Compressed files are not live-tailed; they are treated as batch input.

### 6.2 Required source metadata

Every configured source must have:

- `application`;
- `environment`.

The system must reject a source configuration that does not contain these two fields.

### 6.3 Optional metadata

The following fields are optional and must be nullable. Missing values must not crash parsing, aggregation, or AI analysis:

- service;
- host;
- container;
- source name;
- request ID;
- trace ID;
- client ID;
- source severity;
- HTTP status;
- error code;
- timestamp;
- timezone.

### 6.4 Future source contract

All connectors must eventually emit the same normalized event contract. Planned connectors include:

- local file connector;
- source-side server collector;
- S3 collector;
- Kafka input connector;
- CloudWatch connector;
- Splunk connector.

Only the local file connector is implemented in the POC.

## 7. Data locality and privacy

### 7.1 Raw-log rule

Raw log lines may be read temporarily by the local collector, but they must never be:

- published to Kafka;
- sent to OpenAI;
- included in an AI prompt;
- retained locally for more than 24 hours in the POC.

Raw samples may be stored locally during the POC for debugging and testing. They must have an expiration time and be automatically deleted after 24 hours.

### 7.2 Redacted samples

The collector creates a redacted form of a sample before it can leave the collector process. Redacted samples may be used in Kafka messages, local analysis, and AI prompts when necessary, but they must be bounded and deleted locally after 24 hours.

At minimum, the redaction layer should identify or replace common sensitive values such as:

- passwords;
- API keys and bearer tokens;
- email addresses;
- client identifiers;
- obvious secret-like values;
- credentials embedded in URLs.

The POC may begin with simple configurable regular-expression rules. Production must replace this with a stronger, tested redaction system.

### 7.3 POC client-ID pseudonymization

The POC uses deterministic SHA-256 hashing for client IDs so the same client can be correlated across streams without sending the original client ID.

This is a temporary POC measure. It is not considered production-grade pseudonymization because unsalted hashes may be vulnerable to guessing attacks. HMAC-based pseudonymization is deferred.

## 8. Streaming architecture

### 8.1 POC architecture

```text
Local files
  → File connector/tailer
  → Parser and multiline assembler
  → Redactor and POC pseudonymizer
  → Drain3 template engine
  → Sanitized Kafka topic
  → Five-minute aggregator
  → Deterministic anomaly detector
  → SQLite and embedding index
  → Asynchronous OpenAI analysis worker
  → Local API and dashboard
```

### 8.2 Processing boundary

Drain3 and redaction run before Kafka. Kafka receives sanitized observations, not raw lines.

Kafka provides the streaming boundary, buffering, consumer isolation, and short-term replay. It must not become a permanent raw-log data lake.

### 8.3 Kafka requirements

The POC must:

- run Kafka in Docker;
- retain sanitized events for 24 hours;
- partition by `application + environment`;
- support independent consumers for aggregation, anomaly processing, and AI job creation;
- expose consumer lag and dropped-event metrics;
- allow consumers to restart without corrupting SQLite;
- use bounded processing queues.

Suggested POC topics:

- `logscope.template-observations`;
- `logscope.anomaly-jobs`;
- `logscope.analysis-results`.

No topic may contain raw log lines.

### 8.4 Backpressure

If processing is slower than ingestion, the system must not block the entire application indefinitely.

The POC may use approximate aggregation. When a bounded queue is full, it should:

1. preserve processing-health metrics;
2. preserve aggregate signals whenever possible;
3. drop the oldest queued sanitized observations or samples first;
4. record how many observations were dropped;
5. show a data-loss warning in the dashboard.

The system must never claim complete analysis when data was dropped.

## 9. Parsing and Drain3 processing

### 9.1 Parsing behavior

The parser should extract a timestamp and known metadata when available. Unknown formats and missing optional fields must produce nullable values rather than processing failures.

The parser must preserve:

- original source path;
- line number where available;
- event timestamp where available;
- ingestion timestamp;
- raw sample locally for the POC;
- redacted sample;
- parsed optional fields.

### 9.2 Multiline behavior

The connector must support configurable multiline rules. A multiline record should be combined into one logical event before template extraction.

If a multiline rule cannot confidently identify a continuation, the system should emit the line as a separate event and record a parsing warning.

### 9.3 Drain3 scope

Drain3 clustering is scoped to `application + environment`. Source, service, host, and file path remain metadata attached to the event.

Each template must have:

- stable template ID;
- template text;
- application;
- environment;
- first-seen timestamp;
- last-seen timestamp;
- source references;
- configuration/version information for the clustering rules.

The POC must expose Drain3 configuration instead of hiding all values in source code. At minimum, memory limits and masking rules must be configurable.

## 10. Aggregation and retention

### 10.1 Five-minute buckets

Counts are aggregated into five-minute UTC buckets. Each bucket may contain:

- template ID;
- application;
- environment;
- source ID;
- count;
- first event timestamp;
- last event timestamp;
- severity counts;
- optional client-ID hash cardinality;
- bounded redacted samples;
- dropped-event count.

### 10.2 Retention

- Kafka data: 24 hours.
- Raw local samples: 24 hours, POC only.
- Redacted local samples: 24 hours.
- Five-minute aggregates: six months.
- Anomalies and AI analyses: six months.
- Embedding metadata and vectors: six months.
- Data older than six months: deleted; no POC archive is required.

The POC must run scheduled retention cleanup and record cleanup failures.

### 10.3 Bounded samples

Samples must never be stored once per occurrence for high-volume templates. The initial default is a maximum of five redacted samples per template per five-minute bucket, configurable later.

## 11. Anomaly detection

### 11.1 POC anomaly types

The POC should generate candidate anomalies for:

- newly observed templates;
- sudden template-frequency spikes;
- error or warning bursts;
- unusual combinations of templates across sources;
- correlated anomalies within the same application and environment;
- abnormal combinations of available fields such as status codes and error codes.

Missing-heartbeat and missing-template detection are deferred.

### 11.2 Deterministic detection

Code should detect objective candidate signals before invoking the LLM. Detection thresholds must be configurable and recorded with each anomaly.

At minimum, each candidate should contain:

- anomaly ID;
- application;
- environment;
- related template IDs;
- source references;
- time window;
- counts and baseline values;
- detection rule;
- detector version;
- data-loss indicator.

### 11.3 Cross-stream correlation

The first correlation boundary is `application + environment + time window`. The system should group candidate anomalies from multiple source files when they occur in related five-minute buckets.

Request IDs, trace IDs, and client-ID hashes may strengthen correlation when available, but their absence must not prevent processing.

## 12. OpenAI analysis

### 12.1 Model roles

The POC uses two OpenAI capabilities:

- embeddings for semantic retrieval of similar historical templates and incidents;
- a reasoning/chat model for evaluating anomalies and generating explanations.

Embeddings alone cannot generate explanations or determine whether an event is worth investigating.

### 12.2 Analysis batches

Candidate anomalies are submitted asynchronously in batches. The batch interval is configurable in seconds; the initial default is 60 seconds.

The anomaly detector target is approximately 30 seconds. The dashboard target is approximately 30 seconds. AI processing must not block ingestion or Kafka consumption.

### 12.3 AI context

The AI worker may receive:

- current candidate anomalies;
- related template summaries;
- application and environment metadata;
- source references;
- counts and time windows;
- bounded redacted samples;
- historical matches retrieved through embeddings;
- previous user feedback.

It must not receive raw log lines.

### 12.4 Required AI output

The AI response must be validated against a structured schema similar to:

```json
{
  "investigate": true,
  "severity": "Sev-1",
  "confidence": "high",
  "summary": "...",
  "evidence": [
    {
      "template_id": "...",
      "count": 42,
      "first_seen": "...",
      "last_seen": "...",
      "source_path": "...",
      "line_number": 1234
    }
  ],
  "possible_causes": ["..."],
  "recommended_actions": ["..."],
  "limitations": ["..."],
  "prompt_version": "...",
  "model": "..."
}
```

If evidence is insufficient, the response must say so explicitly and reduce confidence rather than inventing a root cause.

### 12.5 Severity

Severity describes potential impact and urgency:

| Level | Meaning |
|---|---|
| Sev-0 | Critical; immediate investigation or action required. |
| Sev-1 | High impact or high likelihood of becoming critical. |
| Sev-2 | Moderate issue requiring planned investigation. |
| Sev-3 | Low-impact issue or early warning. |
| Sev-4 | Very low impact or informational anomaly. |

### 12.6 Confidence

Confidence describes how strongly the evidence supports the conclusion. It is separate from severity:

- very-low;
- low;
- medium;
- high;
- very-high.

For example, an event may be `Sev-0` with medium confidence, or `Sev-3` with very-high confidence. The POC must store both fields.

### 12.7 AI safety and validation

Log content is untrusted data. The prompt must instruct the model not to follow instructions found inside logs. The application must:

- use structured prompts;
- label log content as untrusted evidence;
- validate enum values and required fields;
- reject malformed AI responses;
- persist the failed response and error;
- make failed jobs retryable;
- record model and prompt versions.

## 13. User feedback

Users may dismiss an anomaly. A dismissed anomaly remains stored and appears in a compact dismissed section of the dashboard.

Feedback must record:

- user label or action;
- timestamp;
- anomaly ID;
- optional comment;
- previous severity and confidence;
- resulting correction.

POC feedback is supplied as context to future AI analysis. It is not used to retrain a model.

## 14. Local storage model

SQLite is the POC metadata and aggregate database. The implementation should use WAL mode and separate ingestion, processing, and API access carefully to reduce lock contention.

Minimum logical tables:

- `sources`;
- `templates`;
- `template_buckets`;
- `samples`;
- `anomalies`;
- `ai_analyses`;
- `feedback`;
- `processing_checkpoints`;
- `embedding_records`;
- `retention_runs`.

The vector index may be a separate local persistent index, but every vector must have a corresponding SQLite metadata record.

Every stored record should include creation time and retention expiration where applicable.

## 15. Traceability

Each template observation and anomaly should retain:

- source path;
- source ID;
- line number when available;
- event timestamp when available;
- ingestion timestamp;
- application;
- environment;
- template ID.

References are informational. They may become invalid after file rotation, deletion, or truncation. The UI must show when a reference is unavailable or uncertain.

## 16. Dashboard requirements

The localhost dashboard must provide:

- configured sources and source status;
- ingestion rate;
- Kafka consumer lag;
- dropped-event count;
- active anomalies;
- severity and confidence;
- concise AI summary;
- evidence and source references;
- possible causes and recommended actions;
- historical similarity results;
- an Ask AI interface;
- dismissed anomalies in a smaller secondary view;
- OpenAI errors and retry state;
- data-loss and parsing warnings.

The dashboard must update within approximately 30 seconds under normal POC load.

## 17. Configuration and deployment

### 17.1 Docker

The POC should run through Docker Compose on Windows and Linux. The compose environment should include:

- local collector;
- Kafka;
- processing worker;
- AI worker;
- API/dashboard service;
- persistent volumes for SQLite and indexes.

Host log directories must be mounted read-only into the collector container. The application must not require write access to source log directories.

### 17.2 Localhost access

The POC binds the dashboard to localhost and is single-user. It does not provide authentication. This limitation must be displayed in the documentation and must not be carried into production by default.

### 17.3 OpenAI configuration

The OpenAI API key is read from a local `.env` file. The file must be excluded from Git and must never be copied into a Docker image or committed to the repository.

The `.env` file may also define model, batch interval, retention, and processing settings, but source definitions should be stored in a documented configuration format or through the UI.

## 18. Performance and reliability requirements

The POC targets:

- 1,000 input lines per second;
- dashboard update within 30 seconds;
- candidate anomaly processing within 30 seconds;
- configurable AI batch interval, default 60 seconds;
- approximate aggregation under overload;
- no application-wide stop when OpenAI is unavailable;
- retryable AI failures;
- visible processing lag and data-loss indicators;
- restart without intentional database corruption;
- Kafka consumer restart support;
- automatic retention cleanup.

The POC does not guarantee perfect at-least-once processing. Duplicate or missed observations may occur under overload or restart, and the UI must make approximate processing visible.

## 19. Error handling

Errors must be visible through all applicable local channels:

- dashboard status;
- application logs;
- terminal/container logs;
- persistent failed-analysis records.

OpenAI failures must not stop ingestion. Kafka, parser, database, and retention failures must be recorded with enough context to diagnose the component and source involved.

## 20. Acceptance criteria

The POC is acceptable when all of the following are demonstrated:

1. A user can configure at least two local files with the same application and environment.
2. The system processes both files concurrently.
3. Raw lines are not present in any Kafka message or OpenAI request.
4. Missing optional fields do not terminate processing.
5. Multiline records are handled according to configured rules.
6. Related messages from both files can be correlated through application, environment, timestamps, templates, and available hashes.
7. Counts are stored in five-minute buckets.
8. Raw and redacted samples are automatically deleted after 24 hours.
9. Aggregate data, anomalies, and embeddings are retained for six months.
10. A new template or frequency spike creates a candidate anomaly.
11. An anomaly is analyzed asynchronously by OpenAI in a configurable batch.
12. The AI response contains valid severity, confidence, summary, evidence, limitations, and model metadata.
13. A failed OpenAI request remains visible and retryable.
14. A user can dismiss an anomaly, see that it was dismissed, and add feedback.
15. The dashboard exposes source status, lag, dropped data, active anomalies, and AI results.
16. The system sustains the initial 1,000-lines-per-second target in a repeatable test.
17. The POC is runnable on both Windows and Linux using documented Docker instructions.

## 21. Test strategy

The repository should include fixture logs for:

- normal traffic;
- repeated templates;
- new error patterns;
- warning and error spikes;
- JSON records;
- multiline stack traces;
- missing timestamps;
- rotated files;
- malformed lines;
- multiple sources with correlated failures;
- sensitive values requiring redaction;
- AI failures and malformed AI responses;
- overload and dropped-event behavior.

Tests should cover parser behavior, redaction, hashing, Drain3 clustering, bucket aggregation, anomaly rules, Kafka serialization, retention cleanup, AI schema validation, and dashboard API responses.

## 22. Deferred decisions and future work

These items are intentionally retained for future review:

- missing-heartbeat and missing-template detection;
- automatically learned expected patterns;
- source-side collectors;
- S3 ingestion;
- remote and cloud log sources;
- HMAC-based pseudonymization;
- secure secret storage;
- authentication and authorization;
- multi-user and multi-tenant operation;
- SSO and audit logs;
- enterprise deployment and high availability;
- external alerting integrations;
- scalable production storage;
- production-grade vector search;
- permanent raw-sample removal from all components;
- stronger privacy and compliance controls;
- model routing and self-hosted models;
- advanced feedback-based evaluation or model tuning;
- final performance SLOs beyond the POC targets.

## 23. Open implementation decisions

The product decisions required for the POC are now defined. The implementation plan should still record explicit technical choices for:

- Python web/API framework;
- dashboard framework;
- Kafka distribution and version;
- SQLite vector-index approach;
- exact Drain3 masking and memory settings;
- exact deterministic anomaly thresholds;
- multiline parsing configuration format;
- Docker Compose service layout;
- fixture-log format and load-test tooling.

These choices should be documented as implementation decisions rather than silently embedded in code.
