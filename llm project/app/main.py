from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .db import execute, execute_insert, fetch_all, fetch_one, init_db, json_dumps
from .llm_sdk import InferenceLogger
from .providers import get_provider
from .schemas import ConversationCreate, ConversationOut, IngestionPayload, IngestionResult, MessageCreate
from .settings import settings

app = FastAPI(title=settings.app_name)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
logger = InferenceLogger()


@app.on_event("startup")
async def startup() -> None:
    init_db()


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    conversations = fetch_all("SELECT * FROM conversations ORDER BY updated_at DESC")
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "app_name": settings.app_name,
            "default_provider": settings.llm_provider,
            "default_model": settings.openai_model if settings.llm_provider == "openai" else settings.mock_model,
            "conversations": conversations,
        },
    )


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={"app_name": settings.app_name},
    )


@app.get("/api/conversations")
async def list_conversations() -> dict[str, Any]:
    conversations = fetch_all("SELECT * FROM conversations ORDER BY updated_at DESC")
    return {"items": conversations}


@app.post("/api/conversations", response_model=ConversationOut)
async def create_conversation(payload: ConversationCreate) -> dict[str, Any]:
    conversation_id = str(uuid4())
    title = payload.title or "New conversation"
    execute_insert(
        """
        INSERT INTO conversations (id, title, provider, model, status, summary, created_at, updated_at, last_message_at)
        VALUES (?, ?, ?, ?, 'active', '', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, NULL)
        """,
        (conversation_id, title, payload.provider, payload.model),
    )
    conversation = fetch_one("SELECT * FROM conversations WHERE id = ?", (conversation_id,))
    return conversation or {}


@app.get("/api/conversations/{conversation_id}")
async def get_conversation(conversation_id: str) -> dict[str, Any]:
    conversation = fetch_one("SELECT * FROM conversations WHERE id = ?", (conversation_id,))
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


@app.get("/api/conversations/{conversation_id}/messages")
async def get_messages(conversation_id: str) -> dict[str, Any]:
    messages = fetch_all(
        "SELECT * FROM messages WHERE conversation_id = ? ORDER BY id ASC",
        (conversation_id,),
    )
    return {"items": messages}


@app.post("/api/conversations/{conversation_id}/cancel")
async def cancel_conversation(conversation_id: str) -> dict[str, Any]:
    updated = execute(
        "UPDATE conversations SET status = 'cancelled', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (conversation_id,),
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"ok": True, "conversation_id": conversation_id, "status": "cancelled"}


@app.post("/api/conversations/{conversation_id}/resume")
async def resume_conversation(conversation_id: str) -> dict[str, Any]:
    updated = execute(
        "UPDATE conversations SET status = 'active', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (conversation_id,),
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"ok": True, "conversation_id": conversation_id, "status": "active"}


@app.post("/api/conversations/{conversation_id}/messages")
async def send_message(conversation_id: str, payload: MessageCreate) -> StreamingResponse:
    conversation = fetch_one("SELECT * FROM conversations WHERE id = ?", (conversation_id,))
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if conversation["status"] == "cancelled":
        raise HTTPException(status_code=409, detail="Conversation is cancelled. Resume it before sending more messages.")

    execute_insert(
        "INSERT INTO messages (conversation_id, role, content, created_at, metadata_json) VALUES (?, 'user', ?, CURRENT_TIMESTAMP, '{}')",
        (conversation_id, payload.content),
    )
    execute(
        "UPDATE conversations SET updated_at = CURRENT_TIMESTAMP, last_message_at = CURRENT_TIMESTAMP WHERE id = ?",
        (conversation_id,),
    )

    recent_messages = fetch_all(
        "SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY id DESC LIMIT ?",
        (conversation_id, settings.max_context_messages),
    )[::-1]
    context_messages = [
        {"role": "system", "content": "You are a concise, helpful assistant. Keep answers brief unless the user asks for depth."},
        *[{"role": item["role"], "content": item["content"]} for item in recent_messages],
    ]

    provider = get_provider(conversation["provider"])
    started_at = datetime.now(timezone.utc)
    start = time.perf_counter()

    try:
        result = await provider.generate(context_messages, conversation["model"])
        latency_ms = int((time.perf_counter() - start) * 1000)
        finished_at = datetime.now(timezone.utc)
        request_id = await logger.log(
            conversation_id=conversation_id,
            session_id=conversation_id,
            provider=conversation["provider"],
            model=conversation["model"],
            status="success",
            started_at=started_at,
            finished_at=finished_at,
            latency_ms=latency_ms,
            input_text=payload.content,
            output_text=result.text,
            usage=result.usage,
        )
        execute_insert(
            """
            INSERT INTO messages (conversation_id, role, content, created_at, provider, model, token_count, latency_ms, metadata_json)
            VALUES (?, 'assistant', ?, CURRENT_TIMESTAMP, ?, ?, ?, ?, ?)
            """,
            (
                conversation_id,
                result.text,
                conversation["provider"],
                conversation["model"],
                result.usage.get("total_tokens"),
                latency_ms,
                json_dumps({"request_id": request_id, "usage": result.usage}),
            ),
        )
        execute(
            "UPDATE conversations SET updated_at = CURRENT_TIMESTAMP, summary = ? WHERE id = ?",
            (summarize_recent(recent_messages + [{"role": "assistant", "content": result.text}]), conversation_id),
        )

        async def text_stream() -> Any:
            for chunk in chunk_text(result.text, size=32):
                yield chunk
                await asyncio.sleep(0.01)

        return StreamingResponse(text_stream(), media_type="text/plain; charset=utf-8")
    except Exception as exc:
        latency_ms = int((time.perf_counter() - start) * 1000)
        finished_at = datetime.now(timezone.utc)
        await logger.log(
            conversation_id=conversation_id,
            session_id=conversation_id,
            provider=conversation["provider"],
            model=conversation["model"],
            status="error",
            started_at=started_at,
            finished_at=finished_at,
            latency_ms=latency_ms,
            input_text=payload.content,
            output_text="",
            usage={},
            error_message=str(exc),
            error_type=type(exc).__name__,
        )
        raise HTTPException(status_code=502, detail="Model call failed")


@app.post("/api/ingest/logs", response_model=IngestionResult)
async def ingest_log(payload: IngestionPayload) -> dict[str, Any]:
    existing = fetch_one("SELECT id FROM inference_logs WHERE request_id = ?", (payload.request_id,))
    if existing:
        return {"accepted": True, "request_id": payload.request_id}

    execute(
        """
        INSERT INTO inference_logs (
            request_id, conversation_id, session_id, provider, model, status, latency_ms,
            prompt_tokens, completion_tokens, total_tokens, input_preview, output_preview,
            error_message, error_type, started_at, finished_at, raw_payload
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            payload.request_id,
            payload.conversation_id,
            payload.session_id,
            payload.provider,
            payload.model,
            payload.status,
            payload.latency_ms,
            payload.prompt_tokens,
            payload.completion_tokens,
            payload.total_tokens,
            payload.input_preview,
            payload.output_preview,
            payload.error_message,
            payload.error_type,
            payload.started_at,
            payload.finished_at,
            json.dumps(payload.raw_payload, ensure_ascii=True),
        ),
    )
    execute_insert(
        "INSERT INTO ingest_events (request_id, status, error_message) VALUES (?, 'accepted', NULL)",
        (payload.request_id,),
    )
    return {"accepted": True, "request_id": payload.request_id}


@app.get("/api/dashboard/summary")
async def dashboard_summary() -> dict[str, Any]:
    totals = fetch_one(
        """
        SELECT
            COUNT(*) AS total_logs,
            SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS successes,
            SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS errors,
            AVG(latency_ms) AS avg_latency,
            SUM(COALESCE(total_tokens, 0)) AS total_tokens
        FROM inference_logs
        """
    ) or {}
    by_provider = fetch_all(
        """
        SELECT provider, COUNT(*) AS count, AVG(latency_ms) AS avg_latency
        FROM inference_logs
        GROUP BY provider
        ORDER BY count DESC
        """
    )
    latency_points = fetch_all(
        """
        SELECT substr(created_at, 1, 13) AS hour_bucket, COUNT(*) AS count, AVG(latency_ms) AS avg_latency
        FROM inference_logs
        GROUP BY hour_bucket
        ORDER BY hour_bucket ASC
        """
    )
    recent_logs = fetch_all(
        "SELECT request_id, conversation_id, provider, model, status, latency_ms, created_at FROM inference_logs ORDER BY id DESC LIMIT 10"
    )
    return {"totals": totals, "by_provider": by_provider, "latency_points": latency_points, "recent_logs": recent_logs}


@app.exception_handler(HTTPException)
async def http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


def summarize_recent(messages: list[dict[str, str]]) -> str:
    user_turns = [message["content"] for message in messages if message["role"] == "user"]
    assistant_turns = [message["content"] for message in messages if message["role"] == "assistant"]
    if not user_turns and not assistant_turns:
        return ""
    summary_parts = []
    if user_turns:
        summary_parts.append(f"User topics: {user_turns[-2:]}")
    if assistant_turns:
        summary_parts.append(f"Assistant replies: {assistant_turns[-2:]}")
    return " | ".join(summary_parts)[:500]


def chunk_text(text: str, size: int = 32) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)] or [""]
