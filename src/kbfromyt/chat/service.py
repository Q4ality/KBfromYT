from __future__ import annotations

import time

from kbfromyt.chat.agent import Agent
from kbfromyt.chat.config import ChatConfig
from kbfromyt.chat.contracts import AnswerEnvelope, ChatRequest
from kbfromyt.chat.memory import Sessions
from kbfromyt.chat.providers.openai import Provider
from kbfromyt.chat.tools import Corpus


class ChatService:
    def __init__(
        self,
        config: ChatConfig,
        provider: Provider | None,
        corpus: Corpus | None,
        readiness_error: str | None = None,
    ):
        self.config, self.provider, self.corpus = config, provider, corpus
        self.readiness_error = readiness_error
        self.sessions = Sessions(config.session_ttl, config.max_sessions)

    def status(self) -> dict:
        reason = self.readiness_error
        if not self.provider:
            reason = "Configure OPENAI_API_KEY in the local .env file, then restart chat."
        elif not self.corpus and not reason:
            reason = "The source corpus is not ready."
        return {
            "ready": not reason,
            "message": reason,
            "model": self.config.model,
            "videos": len(self.corpus.videos) if self.corpus else 0,
            "memory_turns": self.config.memory_turns,
            "semantic": self.config.semantic,
        }

    async def chat(
        self, session_id: str | None, request: ChatRequest
    ) -> tuple[str, AnswerEnvelope]:
        key, session = self.sessions.get(session_id)
        async with session.lock:
            fingerprint = request.message + "\0" + str(request.agentic)
            if request.request_id in session.completed:
                old_question, reply = session.completed[request.request_id]
                if old_question != fingerprint:
                    return key, AnswerEnvelope(
                        status="error",
                        model=self.config.model,
                        error_code="request_conflict",
                        notice="This request ID was already used for a different message.",
                    )
                return key, reply
            readiness = self.status()
            if not readiness["ready"]:
                return key, AnswerEnvelope(
                    status="error",
                    model=self.config.model,
                    error_code="not_ready",
                    notice=readiness["message"],
                )
            history, retained = session.history(self.config.memory_turns, self.config.memory_budget)
            settings = (
                self.config
                if request.agentic
                else self.config.model_copy(update={"max_requests": 3})
            )
            reply = await Agent(settings, self.provider, self.corpus).run(
                request.message, history, retained
            )
            session.remember(
                request.request_id, request.message, reply, self.config.memory_turns, fingerprint
            )
            session.touched = time.monotonic()
            return key, reply

    async def close(self) -> None:
        if self.provider:
            await self.provider.close()
        if self.corpus:
            import asyncio

            await asyncio.to_thread(self.corpus.close)
