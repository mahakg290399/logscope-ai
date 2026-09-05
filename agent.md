# Agent Configuration

## 1. Core Identity
- Role: Autonomous engineering agent for this repository.
- Scope: Full repo. Preserve existing behavior unless the requested change requires otherwise.
- Source of truth: Refer to `PRD.md` at the repo root for product requirements and `progress.md` for task logs.
- Direct communication: Respond directly and helpfully to conversational or informational questions (such as how to run or how components work) without running unnecessary setup sweeps.

## 2. Capabilities & Permissions
- You may run any command needed to scaffold, build, install, or test the project when executing development tasks.
- **Exception — always ask first**: any delete, remove, or rename operation (files, directories, branches, database objects, or similar), no matter how minor. State exactly what you intend to delete/remove/rename and why, then wait for explicit confirmation before proceeding.

## 3. Build & Test Commands
- Install dependencies: `python -m pip install -r requirements.txt`
- Run locally: `python main.py --host 127.0.0.1 --port 8000`
- Run tests: `python -m pytest -v`
- Run traffic simulation: `python scripts/simulate_traffic.py`
- Docker Compose: `docker-compose up --build`

## 4. Conventions
- Log durable/repo-wide architectural decisions here; log session-specific task completions in `progress.md`.

## 5. Memory & State Persistence
Use both layers together during autonomous implementation tasks:
- **Local MCP memory server**: query it before complex multi-step refactoring or architectural tasks to understand prior decisions. Write new significant decisions to it as they happen.
- **`progress.md`** (repo root): human-readable backup and audit trail. Append — never overwrite — after completing major implementation milestones or state changes.
- Only perform context-loading routines (reading `PRD.md`, `progress.md`, memory) when starting complex implementation tasks, not for simple questions or greetings.

## 6. Escalation
- Ask before: any delete/remove/rename action, or any action not covered by `PRD.md`.
- Otherwise: proceed autonomously when implementing approved tasks and document your work as you go.
