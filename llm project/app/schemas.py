from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class ConversationCreate(BaseModel):
    title: str | None = None
    provider: str = Field(default="mock")
    model: str = Field(default="mock-chat")


class ConversationOut(BaseModel):
    id: str
    title: str
    provider: str
    model: str
    status: str
    summary: str
    created_at: str
    updated_at: str
    last_message_at: str | None = None


class MessageCreate(BaseModel):
    content: str


class MessageOut(BaseModel):
    id: int
    conversation_id: str
    role: str
    content: str
    created_at: str
    provider: str | None = None
    model: str | None = None
    token_count: int | None = None
    latency_ms: int | None = None
    metadata_json: str = "{}"


class ChatResponse(BaseModel):
    conversation_id: str
    assistant_message: str
    usage: dict[str, Any]
    latency_ms: int
    request_id: str


class IngestionPayload(BaseModel):
    request_id: str
    conversation_id: str
    session_id: str
    provider: str
    model: str
    status: str
    latency_ms: int
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    input_preview: str | None = None
    output_preview: str | None = None
    error_message: str | None = None
    error_type: str | None = None
    started_at: str
    finished_at: str
    raw_payload: dict[str, Any]


class IngestionResult(BaseModel):
    accepted: bool
    request_id: str
