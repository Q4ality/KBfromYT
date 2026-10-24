from __future__ import annotations

import os
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


class ChatConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    api_key: SecretStr = Field(default=SecretStr(""), repr=False)
    base_url: str = "https://api.openai.com/v1"
    model: str = Field(default="gpt-6-luna", min_length=1)
    reasoning_effort: Literal["none", "low", "medium", "high"] = "low"
    db: Path = Path("data/live/kb.sqlite3")
    index_dir: Path = Path("data/live/semantic")
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    semantic: bool = True
    memory_turns: int = Field(default=3, ge=0, le=20)
    session_ttl: float = Field(default=3600, gt=0)
    max_sessions: int = Field(default=100, ge=1)
    max_requests: int = Field(default=4, ge=3, le=8)
    max_tool_calls: int = Field(default=3, ge=1, le=6)
    max_passages: int = Field(default=12, ge=1, le=20)
    evidence_budget: int = Field(default=8000, ge=1000)
    input_budget: int = Field(default=12000, ge=4000)
    memory_budget: int = Field(default=2500, ge=0)
    max_output_tokens: int = Field(default=1800, ge=200, le=4000)
    deadline: float = Field(default=60, gt=0, le=180)

    @field_validator("base_url")
    @classmethod
    def valid_url(cls, value: str) -> str:
        url = urlparse(value)
        if url.scheme != "https" and not (
            url.scheme == "http" and url.hostname in {"localhost", "127.0.0.1", "::1"}
        ):
            raise ValueError("endpoint must use HTTPS or loopback HTTP")
        if not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError("endpoint URL must not contain credentials, query or fragment")
        return value.rstrip("/")

    @classmethod
    def from_env(cls, dotenv: Path = Path(".env")) -> ChatConfig:
        from dotenv import load_dotenv

        load_dotenv(dotenv, override=False)
        names = {
            "api_key": "OPENAI_API_KEY",
            "base_url": "OPENAI_BASE_URL",
            "model": "OPENAI_MODEL",
            "reasoning_effort": "OPENAI_REASONING_EFFORT",
            "db": "KB_DB",
            "index_dir": "KB_INDEX_DIR",
            "embedding_model": "KB_EMBEDDING_MODEL",
            "memory_turns": "CHAT_MEMORY_TURNS",
            "session_ttl": "CHAT_SESSION_TTL",
            "deadline": "CHAT_DEADLINE",
            "max_requests": "CHAT_MAX_REQUESTS",
        }
        return cls(**{key: os.environ[name] for key, name in names.items() if name in os.environ})

    @property
    def has_key(self) -> bool:
        return bool(self.api_key.get_secret_value().strip())
