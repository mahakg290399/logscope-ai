# Project Memory Maintenance

Durable memory has three layers: Git-tracked facts/rationale in `docs/PROJECT_CONTEXT.md`, `docs/DECISIONS.md`, and `progress.md`; compact searchable MCP entities; and optional generated code summaries keyed by file hash.

## Major changes

Update memory when a change affects architecture, data flow, privacy boundaries, persistence/retention, configuration/deployment, public API, provider behavior, commands, known gaps, or invariants. Formatting and isolated implementation fixes do not need a new MCP entity.

## Incremental workflow

1. Run `git diff --name-status` and `git diff --stat`.
2. Classify changed source, tests, deployment/config, docs, and scripts.
3. Read changed files plus directly referenced contracts/tests only; do not rescan unchanged code.
4. Update the relevant context, decision, or progress section with exact paths.
5. Run focused tests, then the full suite for cross-module changes.
6. Add a short dated MCP observation and relation only when the change is durable; update existing entities instead of duplicating them.

```powershell
git diff --name-status
git diff --stat
git diff -- src/logscope tests docker-compose.yml
python -m pytest -q
```

Use stable MCP entities such as `LogScope_AI`, `LogScope_Architecture`, `Project_Workflow`, `Project_Decisions`, and `Project_Risks`. Never store secrets, raw logs, full source files, or transient test output. If MCP conflicts with Git-tracked docs, docs win; correct the MCP and record meaningful corrections in `progress.md`.
