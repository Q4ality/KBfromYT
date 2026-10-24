from __future__ import annotations

import asyncio
import json
import time

from kbfromyt.chat.agent import Agent
from kbfromyt.chat.config import ChatConfig
from kbfromyt.chat.contracts import AnswerEnvelope, ChatRequest, SourceScope
from kbfromyt.chat.history import History
from kbfromyt.chat.memory import Sessions
from kbfromyt.chat.providers.openai import Provider
from kbfromyt.chat.scope import resolve_scope
from kbfromyt.chat.tools import Corpus


def fingerprint(request: ChatRequest) -> str:
    return json.dumps(
        {
            "message": request.message,
            "agentic": request.agentic,
            "scope": request.scope.model_dump(),
        },
        sort_keys=True,
        ensure_ascii=False,
    )


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
        if history:
            history.interrupt_running()

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

    def error(self, code: str, message: str, conversation: str | None = None) -> AnswerEnvelope:
        return AnswerEnvelope(
            status="error",
            model=self.config.model,
            error_code=code,
            notice=message,
            conversation_id=conversation,
        )

    def recover(self, owner: str, request_id: str) -> dict:
        row = self.history.request(owner, request_id) if self.history else None
        if not row:
            raise KeyError("request not found")
        return {
            "request_id": request_id,
            "state": row["state"],
            "conversation_id": row["conversation"],
            "answer": json.loads(row["answer"]) if row["answer"] else None,
            "notice": "This request may have incurred provider work. A new attempt may be charged."
            if row["state"] in {"interrupted", "cancelled"}
            else None,
        }

    async def chat(
        self, session_id: str | None, request: ChatRequest, owner: str | None = None
    ) -> tuple[str, AnswerEnvelope]:
        async with self.operation_lock:
            return await self._chat(session_id, request, owner)

    async def _chat(
        self, session_id: str | None, request: ChatRequest, owner: str | None
    ) -> tuple[str, AnswerEnvelope]:
        key, session = self.sessions.get(session_id)
        async with session.lock:
            durable = bool(self.history and owner)
            conversation = (request.conversation_id or session.conversation_id) if durable else None
            identity = fingerprint(request)
            existing_request = self.history.request(owner, request.request_id) if durable else None
            if existing_request:
                if existing_request["fingerprint"] != identity:
                    return key, self.error(
                        "request_conflict",
                        "This request ID has a different question, scope or mode.",
                    )
                conversation = request.conversation_id or existing_request["conversation"]
            if durable and conversation:
                self.history.require(owner, conversation)
                if self.history.scope(owner, conversation) != request.scope:
                    return key, self.error(
                        "scope_conflict", "Changing chat scope requires a new conversation."
                    )
                old = self.history.completed(conversation, request.request_id)
                if old:
                    legacy = request.message + "\0" + str(request.agentic)
                    if old[0] == identity or (old[0] == legacy and request.scope == SourceScope()):
                        session.conversation_id = conversation
                        session.scope = request.scope
                        session.turns = self.history.memory(
                            owner, conversation, self.config.memory_turns
                        )
                        return key, old[1]
                    return key, self.error(
                        "request_conflict",
                        "This request ID has a different question, scope or mode.",
                    )
            if durable:
                try:
                    claim = self.history.claim(
                        owner,
                        request.request_id,
                        identity,
                        request.scope,
                        request.conversation_id if existing_request else conversation,
                    )
                except ValueError as exc:
                    return key, self.error(
                        str(exc), "The request ID or conversation scope conflicts with saved state."
                    )
                conversation = claim["conversation"]
                if not claim["created"]:
                    recovered = self.recover(owner, request.request_id)
                    if recovered["answer"]:
                        session.conversation_id = conversation
                        session.scope = request.scope
                        session.turns = self.history.memory(
                            owner, conversation, self.config.memory_turns
                        )
                        return key, AnswerEnvelope.model_validate(recovered["answer"])
                    return key, self.error(
                        "request_" + claim["state"],
                        recovered["notice"]
                        or "This request is already in progress. Recover its result.",
                        conversation,
                    )
                if session.conversation_id != conversation:
                    session.completed.clear()
                session.conversation_id = conversation
                session.turns = self.history.memory(owner, conversation, self.config.memory_turns)
            else:
                old = session.completed.get(request.request_id)
                if old:
                    return (
                        (key, old[1])
                        if old[0] == identity
                        else (
                            key,
                            self.error(
                                "request_conflict",
                                "This request ID has a different question, scope or mode.",
                            ),
                        )
                    )
                if session.scope != request.scope:
                    session.turns.clear()
            session.scope = request.scope
            try:
                readiness = self.status()
                if not readiness["ready"]:
                    reply = self.error(
                        "maintenance" if self.maintenance else "not_ready",
                        readiness["message"],
                        conversation,
                    )
                else:
                    try:
                        allowed = resolve_scope(
                            request.scope,
                            set(self.corpus.videos),
                            self.history.playlists() if self.history else [],
                        )
                    except ValueError as exc:
                        reply = self.error("scope_unavailable", str(exc), conversation)
                    else:
                        if durable:
                            self.history.request_state(owner, request.request_id, "running")
                        history, retained = session.history(
                            self.config.memory_turns, self.config.memory_budget
                        )
                        settings = (
                            self.config
                            if request.agentic
                            else self.config.model_copy(update={"max_requests": 3})
                        )
                        reply = await Agent(settings, self.provider, self.corpus).run(
                            request.message, history, retained, allowed_video_ids=allowed
                        )
                        reply.resolved_video_ids = allowed
                        reply.source_snapshot = self.corpus.snapshot
                reply.scope = request.scope
                reply.conversation_id = conversation
                if durable:
                    self.history.finish_request(
                        owner, request.request_id, identity, request.message, reply
                    )
                session.remember(
                    request.request_id, request.message, reply, self.config.memory_turns, identity
                )
                session.touched = time.monotonic()
                return key, reply
            except asyncio.CancelledError:
                if durable:
                    self.history.request_state(owner, request.request_id, "cancelled")
                raise
            except Exception:
                if durable:
                    self.history.request_state(owner, request.request_id, "interrupted")
                raise

    async def close(self) -> None:
        if self.provider:
            await self.provider.close()
        if self.corpus:
            await asyncio.to_thread(self.corpus.close)
