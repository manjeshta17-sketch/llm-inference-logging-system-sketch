from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

import httpx

from .settings import settings


@dataclass
class LLMResult:
    text: str
    usage: dict[str, Any]
    raw_response: dict[str, Any]


class BaseProvider:
    provider_name: str

    async def generate(self, messages: list[dict[str, str]], model: str) -> LLMResult:
        raise NotImplementedError


class MockProvider(BaseProvider):
    provider_name = "mock"

    async def generate(self, messages: list[dict[str, str]], model: str) -> LLMResult:
        # Walk the conversation history in reverse to find the last and previous user messages
        last_user = None
        previous_user = None
        for msg in reversed(messages):
            if msg.get("role") == "user":
                if last_user is None:
                    last_user = msg.get("content", "")
                else:
                    previous_user = msg.get("content", "")
                    break

        # Simple heuristic: if the latest user asks "what did i just say",
        # reply with the previous user message when available.
        latest = last_user or ""
        context_hint = " ".join([m.get("content", "") for m in messages if m.get("role") == "user"])[:200]

        # normalize (remove punctuation) for robust intent matching
        latest_normalized = re.sub(r"[^a-z0-9\s]", "", (latest or "").lower())
        if "what did i just say" in latest_normalized:
            if previous_user:
                text = f"You said: {previous_user}"
            else:
                text = "I don't see an earlier user message to repeat."
        else:
            text = (
                "I am a lightweight local mock model. "
                f"You said: {latest}. "
                f"I am keeping the last turns in context: {context_hint or 'none yet'}. "
                "Ask a follow-up and I will continue the thread."
            )
        return LLMResult(
            text=text,
            usage={"prompt_tokens": len(json.dumps(messages)) // 4, "completion_tokens": len(text) // 4, "total_tokens": (len(json.dumps(messages)) + len(text)) // 4},
            raw_response={"provider": self.provider_name, "model": model},
        )


class OpenAIProvider(BaseProvider):
    provider_name = "openai"

    async def generate(self, messages: list[dict[str, str]], model: str) -> LLMResult:
        headers = {
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.4,
        }
        async with httpx.AsyncClient(timeout=90) as client:
            response = await client.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
        text = data["choices"][0]["message"]["content"] or ""
        usage = data.get("usage", {})
        return LLMResult(text=text, usage=usage, raw_response=data)


class AnthropicProvider(BaseProvider):
    provider_name = "anthropic"

    async def generate(self, messages: list[dict[str, str]], model: str) -> LLMResult:
        system = ""
        converted_messages: list[dict[str, str]] = []
        for message in messages:
            if message["role"] == "system":
                system = message["content"]
            else:
                converted_messages.append(message)
        headers = {
            "x-api-key": settings.anthropic_api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": model,
            "max_tokens": 1024,
            "system": system,
            "messages": converted_messages,
        }
        async with httpx.AsyncClient(timeout=90) as client:
            response = await client.post("https://api.anthropic.com/v1/messages", headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
        text = "".join(part.get("text", "") for part in data.get("content", []) if part.get("type") == "text")
        usage = data.get("usage", {})
        return LLMResult(text=text, usage=usage, raw_response=data)


def get_provider(provider_name: str) -> BaseProvider:
    provider_name = provider_name.lower().strip()
    if provider_name == "openai":
        return OpenAIProvider()
    if provider_name == "anthropic":
        return AnthropicProvider()
    return MockProvider()
