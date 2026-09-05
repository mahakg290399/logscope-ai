# LogScope AI contribution instructions

## Project context

- **Application**: Python FastAPI application with a real-time web dashboard served at `src/logscope/web/index.html`.
- **Standard Commands**:
  - Run locally: `python main.py --host 127.0.0.1 --port 8000`
  - Run tests: `python -m pytest -v`
  - Run traffic simulation: `python scripts/simulate_traffic.py`
  - Docker Compose: `docker-compose up --build`
- **Documentation**: Detailed specifications are in `PRD.md`, task history in `progress.md`, and agent guidance in `agent.md`.

## Interaction & Working rules

- **Answer directly**: When the user asks a question (e.g., greetings, how to run, architecture explanation, or debugging questions), answer their question directly and concisely. Do not execute unnecessary automated background exploration or recite repository status dumps for simple queries.
- **Action-oriented for tasks**: When asked to implement features, fix bugs, or modify code, turn the concrete request into clear code changes or evidence-backed diagnoses.
- **Sanitization boundary**: Raw log lines must not be sent to Kafka or an LLM unmasked; always preserve the sanitizer boundary.
- **OmniRoute Gateway**: Use OmniRoute through its OpenAI-compatible endpoint at `http://127.0.0.1:20128/v1` when the local gateway is selected. Never commit API keys.
- **Verification**: After modifying code, run the smallest relevant tests (`python -m pytest -v`) and report any limitations explicitly.

