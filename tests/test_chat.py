from __future__ import annotations

import asyncio
import json
import time

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from kbfromyt.chat.agent import Agent
from kbfromyt.chat.config import ChatConfig
from kbfromyt.chat.contracts import AnswerEnvelope, ChatRequest, Draft, SupportCheck
from kbfromyt.chat.memory import Session, Sessions
from kbfromyt.chat.providers.openai import ModelRound, ProviderError, ToolCall
from kbfromyt.chat.service import ChatService
from kbfromyt.chat.tools import Corpus, EvidenceRegistry, ToolBudget
from kbfromyt.chat.validation import notice, render, validate_draft
from kbfromyt.retrieval import search
from kbfromyt.web.app import create_app


class ScriptedProvider:
    """Deterministic test double. Never used by the production application."""

    def __init__(self, mode="grounded"):
        self.mode, self.requests, self.closed = mode, [], False

    async def respond(self, items, instructions, schema, tools, choice):
        self.requests.append(
            {"items": json.loads(json.dumps(items)), "choice": choice, "schema": schema.__name__}
        )
        if self.mode == "timeout":
            await asyncio.sleep(1)
        if self.mode == "error":
            raise ProviderError("rate_limit", "Provider limit reached.")
        if schema is SupportCheck:
            return ModelRound(
                text=json.dumps(
                    {
                        "supported_claims": [] if self.mode == "irrelevant" else [0],
                        "missing_parts": [],
                    }
                ),
                input_tokens=50,
                output_tokens=10,
            )
        if isinstance(choice, dict) or (self.mode == "refine" and choice == "auto"):
            name = "search_transcripts" if self.mode != "bad_tool" else "run_shell"
            query = "trajectory" if self.mode != "empty" else "chlorophyll"
            args = json.dumps({"query": query, "video_ids_or_null": None, "k": 3})
            call = ToolCall(name, args, f"call{len(self.requests)}")
            item = {
                "type": "function_call",
                "name": name,
                "arguments": args,
                "call_id": call.call_id,
            }
            calls = [call, call] if self.mode == "parallel" else [call]
            return ModelRound(items=[item], calls=calls, input_tokens=50, output_tokens=20)
        if self.mode in {"empty", "no_support"}:
            return ModelRound(
                text='{"claims":[],"unanswered":[]}', input_tokens=50, output_tokens=10
            )
        sources = []
        for item in items:
            if item.get("type") == "function_call_output":
                sources.extend(s for s in json.loads(item["output"])["sources"] if "text" in s)
        source = sources[0]
        quote = source["text"].split(".")[0] + "."
        draft = {
            "claims": [
                {
                    "text": "The video discusses agent evaluation.",
                    "citations": [
                        {
                            "source_id": "invented"
                            if self.mode == "bad_id"
                            else source["source_id"],
                            "quote": "This quote is invented."
                            if self.mode == "bad_quote"
                            or (self.mode == "repair" and len(self.requests) == 2)
                            else quote,
                        }
                    ],
                }
            ],
            "unanswered": ["The second question has no evidence."]
            if self.mode == "partial"
            else [],
        }
        return ModelRound(text=json.dumps(draft), input_tokens=70, output_tokens=30)

    async def close(self):
        self.closed = True


@pytest.fixture
def chat_setup(store, video, tmp_path):
    store.import_video(video)
    config = ChatConfig(db=tmp_path / "kb.sqlite3", semantic=False)
    corpus = Corpus(config)
    yield config, corpus
    corpus.close()


@pytest.mark.parametrize(
    "mode,status",
    [
        ("grounded", "grounded"),
        ("partial", "partial"),
        ("empty", "no_support"),
        ("no_support", "no_support"),
        ("irrelevant", "no_support"),
        ("bad_id", "verification_failed"),
        ("bad_quote", "verification_failed"),
        ("parallel", "verification_failed"),
        ("bad_tool", "verification_failed"),
        ("error", "error"),
    ],
)
def test_agent_states_and_citation_enforcement(chat_setup, mode, status):
    config, corpus = chat_setup
    provider = ScriptedProvider(mode)
    reply = asyncio.run(
        Agent(config, provider, corpus).run("What is trajectory evaluation?", [], 0)
    )
    assert reply.status == status
    assert reply.usage.provider_requests <= config.max_requests
    assert reply.usage.tool_calls <= config.max_tool_calls
    if status in {"grounded", "partial"}:
        assert reply.claims and reply.citations
        assert reply.citations[0].supporting_quotes[0] in reply.citations[0].excerpt
        assert reply.citations[0].url.startswith("https://www.youtube.com/")
    else:
        assert not reply.claims and not reply.citations
        assert reply.notice
    if status == "no_support":
        assert "retrieved passages" in reply.display_text()
        assert "Relevant evidence may exist elsewhere" in reply.display_text()


def test_refinement_limit_and_deadline(chat_setup):
    config, corpus = chat_setup
    repaired = asyncio.run(Agent(config, ScriptedProvider("repair"), corpus).run("tools", [], 0))
    assert repaired.status == "grounded" and repaired.usage.provider_requests == 4
    reply = asyncio.run(Agent(config, ScriptedProvider("refine"), corpus).run("tools", [], 0))
    assert reply.status == "grounded"
    assert reply.usage.provider_requests == 4
    assert reply.usage.tool_calls == 2
    config.max_tool_calls = 1
    reply = asyncio.run(Agent(config, ScriptedProvider("refine"), corpus).run("tools", [], 0))
    assert reply.error_code == "budget_exhausted" and reply.usage.tool_calls == 1
    config.deadline = 0.01
    reply = asyncio.run(Agent(config, ScriptedProvider("timeout"), corpus).run("tools", [], 0))
    assert reply.error_code == "deadline" and not reply.claims


def test_context_registry_limits_and_corrupt_source(chat_setup):
    config, corpus = chat_setup
    registry = EvidenceRegistry(config, corpus)
    result = registry.execute(
        "search_transcripts", '{"query":"trajectory","k":2,"video_ids_or_null":null}'
    )
    assert result["sources"]
    context = registry.execute("get_context", '{"source_handle":"S1","neighbor_count":1}')
    assert context["sources"]
    with pytest.raises(ToolBudget):
        registry.execute("get_context", '{"source_handle":"S1","neighbor_count":1}')
    other = EvidenceRegistry(config, corpus)
    with pytest.raises(ValueError, match="stale"):
        other.execute("get_context", '{"source_handle":"S1","neighbor_count":1}')
    with pytest.raises(ValueError, match="filter"):
        corpus.search(
            __import__("kbfromyt.chat.contracts", fromlist=["SearchArgs"]).SearchArgs(
                query="test", k=3, video_ids_or_null=["unknown"]
            )
        )
    ref = registry.sources["S1"].evidence
    draft = Draft.model_validate(
        {
            "claims": [
                {"text": "Claim", "citations": [{"source_id": "S1", "quote": ref.text[:30]}]}
            ],
            "unanswered": [],
        }
    )
    validate_draft(draft, registry)
    ref.start = 999
    with pytest.raises(ValueError, match="bounds"):
        validate_draft(draft, registry)


def test_memory_window_idempotency_reset_and_isolation(chat_setup):
    config, corpus = chat_setup
    provider = ScriptedProvider("no_support")
    config.memory_budget = 12000
    service = ChatService(config, provider, corpus)

    async def scenario():
        key = None
        for i in range(5):
            key, reply = await service.chat(
                key, ChatRequest(message=f"Question number {i}", request_id=f"request_{i}")
            )
            assert reply.status == "no_support"
            assert reply.usage.memory_turns == min(i, 3)
        messages = provider.requests[-2]["items"]
        user_messages = [m["content"] for m in messages if m.get("role") == "user"]
        assert user_messages == [f"Question number {i}" for i in (1, 2, 3, 4)]
        before = len(provider.requests)
        _, same = await service.chat(
            key, ChatRequest(message="Question number 4", request_id="request_4")
        )
        assert same.reply_id == reply.reply_id and len(provider.requests) == before
        _, conflict = await service.chat(
            key, ChatRequest(message="Different", request_id="request_4")
        )
        assert conflict.error_code == "request_conflict"
        other, other_reply = await service.chat(
            None, ChatRequest(message="Other session", request_id="request_5")
        )
        assert other != key and other_reply.usage.memory_turns == 0
        await service.sessions.reset(key)
        _, after = await service.chat(key, ChatRequest(message="Reset", request_id="request_6"))
        assert after.usage.memory_turns == 0

    asyncio.run(scenario())


def test_memory_budget_ttl_and_failed_turns():
    session = Session()
    reply = AnswerEnvelope(status="no_support", model="test", notice="No support.")
    session.remember("r1", "short", reply, 3)
    session.remember("r2", "X" * 5000, reply, 3)
    assert session.history(3, 500) == ([], 0)
    session.remember("r3", "small", reply, 3)
    messages, count = session.history(3, 500)
    assert count == 1 and messages[0]["content"] == "small"
    session.remember("r4", "failed", AnswerEnvelope(status="error", model="test"), 3)
    assert len(session.turns) == 3
    session.remember(
        "r5", "bad cites", AnswerEnvelope(status="verification_failed", model="test"), 3
    )
    assert len(session.turns) == 3
    sessions = Sessions(0.01, 10)
    key, item = sessions.get(None)
    item.touched = time.monotonic() - 1
    new_key, _ = sessions.get(key)
    assert key != new_key and key not in sessions.items


def test_config_and_no_support_localization(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "test-secret-do-not-leak")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-6-luna")
    config = ChatConfig.from_env(tmp_path / "no.env")
    assert config.has_key and "test-secret" not in repr(config)
    assert "подтверждающих цитат" in notice("no_support", "Вопрос на русском")
    for url in (
        "https://user:password@example.com/v1",
        "http://remote.example/v1",
        "https://api.openai.com/v1?key=secret",
    ):
        with pytest.raises(ValidationError):
            ChatConfig(base_url=url)
    for text in ("", "   ", "x" * 8001):
        with pytest.raises(ValidationError):
            ChatRequest(message=text, request_id="request_1")


def test_api_ui_and_session_cookie(chat_setup):
    config, corpus = chat_setup
    provider = ScriptedProvider()
    service = ChatService(config, provider, corpus)
    with TestClient(create_app(config, service)) as client:
        assert client.get("/").status_code == 200
        assert "Ask your videos" in client.get("/").text
        assert client.get("/static/chat.js").status_code == 200
        assert client.get("/api/status").json()["ready"]
        response = client.post("/api/chat", json={"message": "tools", "request_id": "request_1"})
        assert response.json()["status"] == "grounded"
        assert "HttpOnly" in response.headers["set-cookie"]
        assert "SameSite=strict" in response.headers["set-cookie"]
        assert "api_key" not in response.text
        assert (
            client.post("/api/chat", json={"message": " ", "request_id": "request_2"}).status_code
            == 422
        )
        assert client.post("/api/chat/reset").json()["reset"]
        assert (
            client.post("/api/chat/reset", headers={"Origin": "https://evil.example"}).status_code
            == 403
        )
        assert client.get("/", headers={"Host": "evil.example"}).status_code == 403
        assert "frame-ancestors 'none'" in client.get("/").headers["content-security-policy"]
    assert provider.closed


def test_missing_key_is_not_no_evidence(chat_setup):
    config, corpus = chat_setup
    service = ChatService(config, None, corpus)
    with TestClient(create_app(config, service)) as client:
        assert not client.get("/api/status").json()["ready"]
        reply = client.post(
            "/api/chat", json={"message": "tools", "request_id": "request_1"}
        ).json()
        assert reply["status"] == "error" and reply["error_code"] == "not_ready"
        assert not reply["claims"]


def test_parent_expansion_bound_and_video_filter(store, video):
    store.import_video(video)
    baseline = search(store, "trajectory")
    bounded = search(store, "trajectory", parent_child_limit=1)
    assert len(baseline) == 2 and len(bounded) == 1
    assert "Trajectory" in bounded[0].text
    assert search(store, "trajectory", video_ids=[]) == []
    assert search(store, "trajectory", video_ids=["nonexistent"]) == []
    assert search(store, "trajectory", video_ids=[video.video_id])


def test_support_assessment_must_reference_valid_claims(chat_setup):
    config, corpus = chat_setup
    with pytest.raises(ValueError, match="assessment"):
        render(
            Draft(claims=[], unanswered=[]),
            SupportCheck(supported_claims=[99], missing_parts=[]),
            EvidenceRegistry(config, corpus),
            "q",
            "test",
        )
