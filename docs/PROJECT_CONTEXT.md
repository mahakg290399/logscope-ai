# LogScope AI — Project Context

Last synthesized: 2026-08-20. This is a compact, model-independent orientation; `PRD.md` remains the requirements source of truth.

## Purpose and scope

LogScope AI is a single-user localhost POC for SRE log monitoring. It tails local files, parses records, redacts sensitive values, clusters messages into Drain3 templates, aggregates five-minute signals, detects deterministic anomalies, and provides AI-assisted triage plus historical similarity search.

The POC target is Docker on Windows/Linux with Kafka, SQLite, a local vector index, FastAPI, and a dashboard. Production-direction requirements in `PRD.md` (remote collectors, S3/connectors, auth, multi-tenancy, HA, external alerts, and enterprise security) are not implemented here.

## Source of truth

- `PRD.md`: product requirements and acceptance criteria.
- `progress.md`: implementation status and session history.
- `docs/DECISIONS.md`: durable architectural decisions and trade-offs.
- `src/logscope/`: implementation.
- `tests/`: executable behavior and regression coverage.

## Architecture and data flow

`src/logscope/ingestion/tailer.py` reads configured files; `parser.py` parses and assembles multiline records. `src/logscope/sanitizer.py` redacts and hashes client IDs. `src/logscope/templates/engine.py` runs Drain3 by `application + environment`. `src/logscope/kafka/streaming.py` publishes sanitized observations to Kafka in Docker mode; bounded in-memory queues are explicit test/fallback mode only.

`src/logscope/service.py` coordinates ingestion, aggregation, anomaly detection, AI batching, and persistence. `aggregator/` writes UTC five-minute buckets; `anomaly/` detects new templates, spikes, error bursts, and correlations. `storage/db.py` provides SQLite WAL persistence and retention operations; `storage/vector_index.py` provides local similarity search with an offline fallback. `ai/worker.py` performs structured provider-backed or heuristic triage. `api/app.py` exposes REST/SSE endpoints and `web/index.html` is the dashboard.

Raw logs must not cross Kafka or enter AI prompts. Evidence is bounded and redacted; source path/line references are retained. Kafka retention is 24 hours and aggregate/anomaly/vector retention is six months by design; scheduled automatic cleanup remains a gap.

## Current verified status

- `python -m pytest -q`: **25 passed** on 2026-08-20.
- Parser, checkpoints, multiline handling, sanitizer, Drain3 scope, Kafka/fallback streaming, SQLite WAL, anomaly rules, provider selection/fallback, prompt safety, REST/SSE API, dashboard, and retention primitives are implemented and covered to varying degrees by `tests/`.
- The codebase is a POC, not production-ready. Known gaps include production connectors, missing-heartbeat detection, authentication/multi-user controls, external alerting, HA/cloud deployment, stronger HMAC pseudonymization, and scheduled retention. See `PRD.md` and `progress.md`.

## Deployment and CI/CD (added 2026-09-05)

Target is a single Oracle Always Free Ampere A1 VM (2 OCPU / 12 GB) running
`deploy/oracle/docker-compose.production.yml` behind Caddy; provisioning
order in `docs/ORACLE_SETUP_PLAN.md`, decisions in ADR-008/ADR-009.
Pipeline: `.github/workflows/ci.yml` (pytest + compose validation) and
`cd.yml` (SSH `git pull`, native ARM rebuild, OCI instance-principal secret
refresh, `https://$LOGSCOPE_DOMAIN/api/health` gate). Cloud not yet
provisioned — account created only. The VM must be cloned at `/opt/logscope`
(full repo, not folder copy) for `cd.yml` paths to resolve.

## Important commands

```text
python -m pytest -v
python main.py --host 127.0.0.1 --port 8000
python scripts/simulate_traffic.py
docker-compose up --build
```

## Working agreement

Keep the memory MCP focused on compact facts, decisions, and pointers. Do not copy the whole repository into memory. When code changes, refresh only changed-file summaries or dependencies; keep the canonical facts and decisions in Git-tracked documentation.

## Future-agent invariants

1. Preserve required `application` and `environment` metadata.
2. Never publish raw logs to Kafka or send raw logs to an AI provider.
3. Keep Drain3 isolated by application and environment.
4. Preserve bounded queues, dropped-event metrics, and data-loss warnings.
5. Keep AI output structured, validated, uncertainty-aware, and prompt-injection resistant.
6. Preserve SQLite WAL/checkpoint behavior and trace references after samples expire.
