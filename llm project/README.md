# Inference Ledger Chat

A lightweight LLM chatbot with multi-turn conversations, streaming UI updates, near-real-time inference logging, ingestion validation, and SQLite storage for chat history plus observability data.

## What it includes

- Chat UI for creating, resuming, and cancelling conversations
- Multi-provider adapter layer for `mock`, `openai`, and `anthropic`
- Lightweight SDK wrapper that captures latency, token usage, status, timestamps, and previews
- Ingestion API that validates log payloads and persists them to SQLite
- Dashboard for latency, throughput, provider mix, and recent logs
- Docker Compose setup for one-command startup

## Quick start

### Option A: Docker Compose

Make sure Docker Desktop is installed first. If `docker` is not recognized in PowerShell, install Docker Desktop, restart the terminal, and verify with:

```powershell
docker --version
docker compose version
```

Then run:

```bash
docker compose up --build
```

Open `http://localhost:8000`.

### Option B: Local Python

1. Install Python 3.12 or later.
2. Create and activate a virtual environment.
3. Install dependencies:

```bash
pip install -r requirements.txt
```

4. Run the app:

```bash
uvicorn app.main:app --reload
```

5. Open `http://localhost:8000`.

## Environment variables

- `DATABASE_PATH` - SQLite file path, defaults to `data/inference.db`
- `APP_BASE_URL` - Base URL used by the logging wrapper for ingestion calls
- `LLM_PROVIDER` - `mock`, `openai`, or `anthropic`
- `OPENAI_API_KEY` - Required for OpenAI provider
- `OPENAI_MODEL` - Defaults to `gpt-4.1-mini`
- `ANTHROPIC_API_KEY` - Required for Anthropic provider
- `ANTHROPIC_MODEL` - Defaults to `claude-3-7-sonnet-latest`

## Architecture overview

The browser sends chat messages to the FastAPI app. The API persists the user message, collects a short context window from SQLite, and calls the selected provider adapter. The inference result is then recorded through the logging SDK, which posts a telemetry payload to the ingestion endpoint. The ingestion service validates the payload with Pydantic and stores both the normalized log row and the raw payload in SQLite.

## Schema design

The database uses three main tables:

- `conversations` stores the thread state, provider/model choice, summary, and status flags
- `messages` stores every user and assistant turn with optional model metadata
- `inference_logs` stores normalized telemetry for latency, token usage, status, and redacted previews

A small `ingest_events` table captures whether an ingestion payload was accepted. The design keeps the write path simple while preserving raw payloads for future reprocessing.

## Tradeoffs

- SQLite keeps the demo easy to run locally, but it is not the right long-term choice for high write throughput.
- The streaming UI currently chunks the final model response once it is available, so the user sees incremental output without requiring a provider-specific SSE parser.
- The SDK posts logs asynchronously for low coupling, but a production deployment would add retries and a durable queue.
- PII redaction is intentionally lightweight and regex-based.

## What I would improve with more time

- Add a durable event queue between inference and ingestion
- Implement true provider-native streaming end to end
- Add auth, multi-user isolation, and conversation sharing
- Replace SQLite with Postgres and add migrations
- Expand dashboards with percentile latency, token throughput, and error drill-downs
- Add background retries and dead-letter handling for ingestion failures

## Demo

- Local demo: run the app and open `http://localhost:8000`
- Dashboard: `http://localhost:8000/dashboard`

## Submission note

This repo is ready to be pushed to GitHub and shared with `work@ollive.ai`.
