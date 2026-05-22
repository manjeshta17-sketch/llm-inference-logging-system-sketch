# Architecture Notes

## Ingestion flow

1. The chat UI sends a user message to the FastAPI app.
2. The app stores the user turn in SQLite and builds a short context window from the latest messages.
3. The selected provider adapter generates a response.
4. The inference logging wrapper measures latency, redacts previews, and posts a telemetry payload to `/api/ingest/logs`.
5. The ingestion endpoint validates the payload and persists the normalized log row plus the raw payload.
6. The assistant response is stored in the messages table and streamed back to the browser.

## Logging strategy

The SDK captures:

- model and provider
- request status
- latency
- token usage when available
- timestamps
- conversation/session ID
- redacted input/output previews
- error text and error type on failures

The wrapper posts logs asynchronously to keep the chat path lightweight. The ingestion service stores both structured columns and the raw JSON payload so the schema can evolve without losing original data.

## Scaling considerations

- SQLite is sufficient for a demo and low-volume traffic, but a production version should move to Postgres.
- The ingestion endpoint is stateless and can be scaled horizontally once the database is externalized.
- A queue would help absorb bursts and add retry behavior for log delivery.
- Provider adapters should be moved behind a small service boundary if the system grows into multi-tenant traffic.

## Failure handling assumptions

- If the logging post fails, the chat experience still completes; telemetry loss is acceptable for this lightweight demo.
- If the provider call fails, the app returns an error and emits an error log payload.
- PII redaction is best-effort and regex-based.
- Cancel currently stops the active browser conversation state; the provider call is not preempted in this demo implementation.
