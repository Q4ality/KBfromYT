from __future__ import annotations

import asyncio
import time

from kbfromyt.chat.agent import Agent
from kbfromyt.chat.config import ChatConfig
from kbfromyt.chat.contracts import AnswerEnvelope, ChatRequest
from kbfromyt.chat.history import History
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
        history: History | None = None,
    ):
        self.config, self.provider, self.corpus = config, provider, corpus
        self.readiness_error = readiness_error
        self.sessions = Sessions(config.session_ttl, config.max_sessions)
        self.history = history
        self.operation_lock = asyncio.Lock()
        self.maintenance = False

    def status(self) -> dict:
        reason = self.readiness_error
        if self.maintenance:
            reason = "Library maintenance is in progress. Chat resumes when indexing finishes."
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
        self, session_id: str | None, request: ChatRequest, owner: str | None = None
    ) -> tuple[str, AnswerEnvelope]:
        if self.maintenance:
            key, _ = self.sessions.get(session_id)
            return key, AnswerEnvelope(
                status="error",
                model=self.config.model,
                error_code="maintenance",
                notice=self.status()["message"],
            )
        async with self.operation_lock:
            return await self._chat(session_id, request, owner)

    async def _chat(
        self, session_id: str | None, request: ChatRequest, owner: str | None
    ) -> tuple[str, AnswerEnvelope]:
        key, session = self.sessions.get(session_id)
        async with session.lock:
            conversation = None
            if self.history and owner:
                conversation = request.conversation_id or session.conversation_id
                if not conversation:
                    conversation = self.history.create(owner)
                self.history.require(owner, conversation)
                if session.conversation_id != conversation:
                    session.completed.clear()
                session.conversation_id = conversation
                session.turns = self.history.memory(owner, conversation, self.config.memory_turns)
            fingerprint = request.message + "\0" + str(request.agentic)
            completed = (
                self.history.completed(conversation, request.request_id)
                if conversation
                else session.completed.get(request.request_id)
            )
            if completed:
                old_question, reply = completed
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
            if conversation:
                reply.conversation_id = conversation
                self.history.append(
                    conversation, request.request_id, fingerprint, request.message, reply
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
            await asyncio.to_thread(self.corpus.close)
