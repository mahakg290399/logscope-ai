# Architectural Decisions

## ADR-001 — Sanitize before streaming

Raw log contents are redacted and pseudonymized before they cross the Kafka boundary. This limits exposure of secrets and personal data while preserving useful aggregation and triage context.

## ADR-002 — Kafka in Docker, bounded memory only as explicit fallback

Docker mode uses Kafka for the streaming boundary. The in-memory queue path remains for tests and explicit fallback operation, with bounded backpressure behavior.

## ADR-003 — SQLite WAL for local persistence

SQLite in WAL mode stores templates, buckets, samples, anomalies, AI analyses, feedback, checkpoints, embeddings, and retention metadata for the POC.

## ADR-004 — Deterministic anomaly detection before AI triage

New templates, frequency spikes, and error bursts are detected deterministically. The AI worker enriches and triages incidents instead of being the primary detector.

## ADR-005 — Project memory is layered

Git-tracked context and decision documents are the durable, model-independent source. The local memory MCP stores compact searchable facts and pointers. Generated code summaries or indexes should be keyed by file hash and refreshed only for changed files.

## ADR-006 — Application/environment is the processing boundary

Sources require both fields, and Drain3 engines are isolated by their pair. Correlation begins at `application + environment + time window`; optional trace/client metadata strengthens correlation but cannot be required (`src/logscope/models.py`, `src/logscope/templates/engine.py`).

## ADR-007 — POC boundaries remain explicit

Local file ingestion, localhost single-user operation, unsalted SHA-256 client-ID hashing, and provider fallbacks are POC choices—not production guarantees. Compare future work against `PRD.md` before treating a production-direction requirement as complete.

## ADR-008 — Oracle Always Free as deployment target

The full stack (Kafka KRaft + app + Caddy + demo-app, ~1.5–2.5 GB RAM) only fits Oracle's Ampere A1 Always Free shape (2 OCPU / 12 GB since June 2026, 200 GB disk, 10 TB egress). GCP/AWS/Azure free tiers (1 GB RAM, or 12-month trials) and sleep-prone PaaS frees cannot run the Kafka boundary the PRD requires. Setup order is tracked in `docs/ORACLE_SETUP_PLAN.md`.

## ADR-009 — Pull-based GitHub Actions deploy, secrets stay on the VM

CI (`ci.yml`) runs pytest and compose validation on standard runners — free and unlimited on the public repo. CD (`cd.yml`) SSHs into the VM and runs `git pull --ff-only` plus a native ARM `docker compose up -d --build`; no cross-arch image build, no container registry. LLM API keys never enter GitHub Secrets: the VM refreshes them from OCI Secret Management via instance principal (`bootstrap-secrets.sh`). GitHub holds only `OCI_HOST`, `OCI_USER`, `OCI_SSH_KEY`.
