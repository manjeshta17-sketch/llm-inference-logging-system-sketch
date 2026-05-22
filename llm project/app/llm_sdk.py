from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from uuid import uuid4

import httpx

from .pii import redact_pii
from .settings import settings


class InferenceLogger:
    def __init__(self, ingestion_url: str | None = None) -> None:
        self.ingestion_url = ingestion_url or f"{settings.app_base_url}{settings.ingestion_path}"

    async def log(
        self,
        *,
        conversation_id: str,
        session_id: str,
        provider: str,
        model: str,
        status: str,
        started_at: datetime,
        finished_at: datetime,
        latency_ms: int,
        input_text: str,
        output_text: str,
        usage: dict,
        error_message: str | None = None,
        error_type: str | None = None,
    ) -> str:
        request_id = str(uuid4())
        payload = {
            "request_id": request_id,
            "conversation_id": conversation_id,
            "session_id": session_id,
            "provider": provider,
            "model": model,
            "status": status,
            "latency_ms": latency_ms,
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "total_tokens": usage.get("total_tokens"),
            "input_preview": redact_pii(input_text)[: settings.preview_chars],
            "output_preview": redact_pii(output_text)[: settings.preview_chars],
            "error_message": redact_pii(error_message) if error_message else None,
            "error_type": error_type,
            "started_at": started_at.replace(tzinfo=timezone.utc).isoformat(),
            "finished_at": finished_at.replace(tzinfo=timezone.utc).isoformat(),
            "raw_payload": {
                "provider": provider,
                "model": model,
                "status": status,
                "latency_ms": latency_ms,
                "usage": usage,
            },
        }
        asyncio.create_task(self._post(payload))
        return request_id

    async def _post(self, payload: dict) -> None:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(self.ingestion_url, json=payload)
        except Exception:
            pass
