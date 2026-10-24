from __future__ import annotations

import asyncio
import json
import math
import os
import secrets
import time
from dataclasses import dataclass, field

from kbfromyt.chat.contracts import AnswerEnvelope

_encoder = None


def configure_tokenizer(model: str) -> None:
    """Initialize at application/evaluation startup, never during unit imports."""
    import tiktoken

    global _encoder
    os.environ.setdefault("TIKTOKEN_CACHE_DIR", "data/models/tiktoken")
    try:
        _encoder = tiktoken.encoding_for_model(model)
    except KeyError:
        _encoder = tiktoken.get_encoding("o200k_base")


def budget_size(value: object) -> int:
    """Budget estimate with 25% margin; actual usage comes only from the provider.

    Offline tests use the stricter byte bound without downloading tokenizer data.
    """
    text = json.dumps(value, ensure_ascii=False, default=str)
    if _encoder is not None:
        return math.ceil(len(_encoder.encode(text, disallowed_special=())) * 1.25)
    return len(text.encode("utf-8"))


@dataclass
class Session:
    conversation_id: str | None = None
    turns: list[tuple[str, AnswerEnvelope]] = field(default_factory=list)
    completed: dict[str, tuple[str, AnswerEnvelope]] = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    touched: float = field(default_factory=time.monotonic)

    def history(self, count: int, budget: int) -> tuple[list[dict], int]:
        pairs = self.turns[-count:] if count else []
        while pairs:
            messages = [
                message
                for user, reply in pairs
                for message in (
                    {"role": "user", "content": user},
                    {"role": "assistant", "content": reply.display_text()},
                )
            ]
            if budget_size(messages) <= budget:
                return messages, len(pairs)
            pairs = pairs[1:]
        return [], 0

    def remember(
        self,
        request_id: str,
        question: str,
        reply: AnswerEnvelope,
        count: int,
        fingerprint: str | None = None,
    ) -> None:
        self.completed[request_id] = (fingerprint or question, reply)
        # Only a bounded idempotency cache; transcripts do not persist after expiry/reset.
        while len(self.completed) > 50:
            del self.completed[next(iter(self.completed))]
        if reply.status in {"grounded", "partial", "no_support"}:
            self.turns.append((question, reply))
            self.turns = self.turns[-count:] if count else []


class Sessions:
    def __init__(self, ttl: float, limit: int):
        self.ttl, self.limit = ttl, limit
        self.items: dict[str, Session] = {}

    def get(self, session_id: str | None) -> tuple[str, Session]:
        now = time.monotonic()
        for key, session in list(self.items.items()):
            if not session.lock.locked() and now - session.touched >= self.ttl:
                del self.items[key]
        if session_id not in self.items:
            if len(self.items) >= self.limit:
                idle = [k for k, s in self.items.items() if not s.lock.locked()]
                if not idle:
                    raise ValueError("session capacity reached")
                del self.items[min(idle, key=lambda k: self.items[k].touched)]
            session_id = secrets.token_urlsafe(32)
            self.items[session_id] = Session()
        session = self.items[session_id]
        session.touched = now
        return session_id, session

    async def reset(self, session_id: str | None) -> None:
        session = self.items.get(session_id)
        if session:
            async with session.lock:
                session.turns.clear()
                session.completed.clear()
                session.conversation_id = None
                session.touched = time.monotonic()
