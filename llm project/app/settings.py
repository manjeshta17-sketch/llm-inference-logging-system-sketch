from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "Inference Ledger Chat")
    database_path: str = os.getenv("DATABASE_PATH", str(Path("data") / "inference.db"))
    app_base_url: str = os.getenv("APP_BASE_URL", "http://localhost:8000")
    ingestion_path: str = os.getenv("INGESTION_PATH", "/api/ingest/logs")
    llm_provider: str = os.getenv("LLM_PROVIDER", "mock")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-3-7-sonnet-latest")
    mock_model: str = os.getenv("MOCK_MODEL", "mock-chat")
    max_context_messages: int = int(os.getenv("MAX_CONTEXT_MESSAGES", "8"))
    preview_chars: int = int(os.getenv("PREVIEW_CHARS", "180"))


settings = Settings()
