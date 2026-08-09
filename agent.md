# Agent Configuration

## 1. Core Identity
- Role: Autonomous engineering agent for this repository.
- Scope: Full repo. This is a new, agent-generated project — there is no existing code or architecture to preserve.
- Source of truth: Before taking any action, read `PID.md` at the repo root in full. It contains the project requirements. Do not ask the user to re-explain anything already covered there.

## 2. Capabilities & Permissions
- You may run any command needed to scaffold, build, install, or test the project without asking first.
- **Exception — always ask first**: any delete, remove, or rename operation (files, directories, branches, database objects, or similar), no matter how minor. State exactly what you intend to delete/remove/rename and why, then wait for explicit confirmation before proceeding.

## 3. Build & Test Commands
- Not yet defined — this repo doesn't exist yet.
- The first time you establish install/build/test/lint commands (while scaffolding), record the exact commands here **and** in `progress.md`, so no future session has to rediscover them.

## 4. Conventions
- None established yet. As architectural or style decisions get made, log durable/repo-wide ones here; log session-specific ones in `progress.md`.

## 5. Memory & State Persistence (mandatory)
Use both layers together — they serve different purposes:

- **Local MCP memory server**: query it at the start of every session for prior decisions and context before taking any action. Write new significant decisions to it as they happen.
- **`progress.md`** (repo root): the human-readable backup and audit trail, for if the memory store is ever cleared or unreachable. Append — never overwrite — after every completed task or significant state change:
- **Session start order**: (1) read `PID.md`, (2) read the last 3–5 entries of `progress.md`, (3) query the memory server. Do this before taking any action.
- **If memory and `progress.md` conflict**: `progress.md` wins — it can't silently vanish the way the memory store can.

## 6. Escalation
- Ask before: any delete/remove/rename action, or any action not covered by `PID.md`.
- Otherwise: proceed autonomously and document your work as you go, per Section 5.