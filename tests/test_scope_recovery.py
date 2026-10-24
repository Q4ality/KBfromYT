from __future__ import annotations

import asyncio
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from kbfromyt.chat.config import ChatConfig
from kbfromyt.chat.contracts import ChatRequest, Draft, SourceScope
from kbfromyt.chat.history import History
from kbfromyt.chat.scope import resolve_scope
from kbfromyt.chat.service import ChatService, fingerprint
from kbfromyt.chat.tools import Corpus, EvidenceRegistry
from kbfromyt.chat.validation import validate_draft
from kbfromyt.models import RawSegment
from kbfromyt.semantic import SemanticIndex
from kbfromyt.web.app import create_app
from tests.test_chat import ScriptedProvider
from tests.test_semantic import TestVectors

A, B, SHARED = "SCOPE000001", "SCOPE000002", "SCOPE000003"
PA, PB = "PLAYLIST0001", "PLAYLIST0002"


@pytest.fixture
def scoped_setup(store, video, tmp_path):
    for key, topic in [(A, "alpha"), (B, "beta"), (SHARED, "shared")]:
        clone = video.model_copy(deep=True)
        clone.video_id = key
        clone.title = topic
        clone.segments = [
            RawSegment(
                start=i * 20,
                end=i * 20 + 15,
                text=f"The {topic} speaker discusses trajectory evaluation. "
                + " ".join(f"{topic}{i}_{n}" for n in range(160))
                + ".",
            )
            for i in range(5)
        ]
        store.import_video(clone)
    config = ChatConfig(
        db=tmp_path / "kb.sqlite3",
        semantic=False,
        input_budget=100000,
        evidence_budget=60000,
        memory_budget=12000,
    )
    history = History(tmp_path / "state.sqlite3")
    history.save_playlist({"id": PA, "video_ids": [A, SHARED]})
    history.save_playlist({"id": PB, "video_ids": [B, SHARED]})
    corpus = Corpus(config)
    yield config, history, corpus
    corpus.close()


@pytest.mark.parametrize(
    "payload",
    [
        {"kind": "videos"},
        {"kind": "playlist"},
        {"kind": "library", "video_ids": [A]},
        {"kind": "videos", "video_ids": ["bad"]},
        {"kind": "library", "playlist_id": PA},
    ],
)
def test_scope_rejects_ambiguous_or_empty_selection(payload):
    with pytest.raises(ValidationError):
        SourceScope.model_validate(payload)


def test_scope_resolves_shared_and_missing_sources(scoped_setup):
    _, history, corpus = scoped_setup
    assert resolve_scope(
        SourceScope(kind="playlist", playlist_id=PA), set(corpus.videos), history.playlists()
    ) == [A, SHARED]
    assert SourceScope(kind="videos", video_ids=[B, A, B]).video_ids == [A, B]
    for scope in [
        SourceScope(kind="playlist", playlist_id="MISSING0000"),
        SourceScope(kind="videos", video_ids=["MISSING0000"]),
    ]:
        with pytest.raises(ValueError):
            resolve_scope(scope, set(corpus.videos), history.playlists())


@pytest.mark.parametrize("dense", [False, True])
@pytest.mark.parametrize("broad", [False, True])
def test_all_retrieval_paths_and_citations_enforce_scope(scoped_setup, tmp_path, dense, broad):
    config, _, corpus = scoped_setup
    if dense:
        pytest.importorskip("qdrant_client")
        corpus.semantic = SemanticIndex(tmp_path / "vectors", TestVectors())
        from kbfromyt.store import Store

        with Store(config.db) as store:
            corpus.semantic.rebuild(store)
    registry = EvidenceRegistry(config, corpus, broad=broad, allowed_video_ids=[A])
    result = registry.execute(
        "search_overviews" if broad else "search_transcripts",
        json.dumps({"query": "trajectory", "video_ids_or_null": None, "k": 3}),
    )
    assert result["sources"] and {s.evidence.video_id for s in registry.sources.values()} == {A}
    assert all(card["video_id"] == A for card in result["video_overviews"])
    handle = next(iter(registry.sources))
    registry.execute("get_context", json.dumps({"source_handle": handle, "neighbor_count": 1}))
    assert all(s.evidence.video_id == A for s in registry.sources.values())
    fresh = EvidenceRegistry(config, corpus, allowed_video_ids=[A])
    with pytest.raises(ValueError):
        fresh.execute(
            "search_transcripts",
            json.dumps({"query": "trajectory", "video_ids_or_null": [B], "k": 3}),
        )
    from kbfromyt.chat.contracts import SearchArgs

    outside = corpus.search(SearchArgs(query="trajectory", video_ids_or_null=[B], k=1))[0]
    with pytest.raises(ValueError):
        fresh.register([outside])
    fresh.sources["bad"] = outside
    draft = Draft.model_validate(
        {
            "claims": [
                {
                    "text": "B claim",
                    "citations": [{"source_id": "bad", "quote": outside.evidence.text[:30]}],
                }
            ],
            "unanswered": [],
        }
    )
    with pytest.raises(ValueError):
        validate_draft(draft, fresh)


def test_scope_history_membership_and_memory(scoped_setup):
    config, history, corpus = scoped_setup
    provider = ScriptedProvider()
    service = ChatService(config, provider, corpus, history=history)
    scope = SourceScope(kind="playlist", playlist_id=PA)

    async def scenario():
        key, first = await service.chat(
            None, ChatRequest(message="trajectory", request_id="scope_001", scope=scope), "owner"
        )
        assert first.resolved_video_ids == [A, SHARED] and first.coverage.scope_videos == 2
        before = len(provider.requests)
        _, conflict = await service.chat(
            key,
            ChatRequest(
                message="trajectory", request_id="scope_002", conversation_id=first.conversation_id
            ),
            "owner",
        )
        assert conflict.error_code == "scope_conflict" and len(provider.requests) == before
        history.save_playlist({"id": PA, "video_ids": [B]})
        _, replay = await service.chat(
            None, ChatRequest(message="trajectory", request_id="scope_001", scope=scope), "owner"
        )
        assert replay.reply_id == first.reply_id and replay.resolved_video_ids == [A, SHARED]
        _, second = await service.chat(
            key,
            ChatRequest(
                message="follow up",
                request_id="scope_003",
                conversation_id=first.conversation_id,
                scope=scope,
            ),
            "owner",
        )
        assert second.resolved_video_ids == [B] and second.usage.memory_turns == 1
        _, new = await service.chat(
            None,
            ChatRequest(
                message="trajectory",
                request_id="scope_004",
                scope=SourceScope(kind="videos", video_ids=[A]),
            ),
            "owner",
        )
        assert new.usage.memory_turns == 0 and new.conversation_id != first.conversation_id
        assert history.page("owner", first.conversation_id)["scope"]["playlist_id"] == PA

    asyncio.run(scenario())


def test_completed_first_request_survives_loss_restart_and_library_change(scoped_setup):
    config, history, corpus = scoped_setup
    provider = ScriptedProvider()
    service = ChatService(config, provider, corpus, history=history)
    request = ChatRequest(
        message="trajectory",
        request_id="lost_first",
        scope=SourceScope(kind="videos", video_ids=[A]),
    )

    async def scenario():
        replies = await asyncio.gather(
            service.chat(None, request, "owner"), service.chat(None, request, "owner")
        )
        first = replies[0][1]
        assert first.reply_id == replies[1][1].reply_id and len(provider.requests) == 3
        assert (
            len(history.list("owner")) == 1
            and len(history.page("owner", first.conversation_id)["turns"]) == 1
        )
        restored_provider = ScriptedProvider()
        restored = ChatService(config, restored_provider, corpus, history=History(history.path))
        snapshot = corpus.videos
        corpus.videos = {}
        _, saved = await restored.chat(None, request, "owner")
        assert saved.reply_id == first.reply_id and not restored_provider.requests
        assert restored.recover("owner", request.request_id)["answer"]["reply_id"] == first.reply_id
        with pytest.raises(KeyError):
            restored.recover("other", request.request_id)
        corpus.videos = snapshot
        for changed in [
            request.model_copy(update={"message": "different"}),
            request.model_copy(update={"agentic": False}),
            request.model_copy(update={"scope": SourceScope()}),
        ]:
            _, conflict = await restored.chat(None, changed, "owner")
            assert conflict.error_code == "request_conflict"
        assert not restored_provider.requests

    asyncio.run(scenario())


def test_interruption_after_provider_work_does_not_auto_retry(scoped_setup):
    config, history, corpus = scoped_setup
    provider = ScriptedProvider()
    service = ChatService(config, provider, corpus, history=history)
    request = ChatRequest(message="trajectory", request_id="interrupted1")

    with history.connect() as db:
        db.execute("""CREATE TRIGGER fail_request_commit BEFORE UPDATE OF answer ON chat_requests
                      BEGIN SELECT RAISE(ABORT,'simulated disk failure after turn insert'); END""")

    async def scenario():
        with pytest.raises(sqlite3.IntegrityError):
            await service.chat(None, request, "owner")
        assert (
            len(provider.requests) == 3
            and history.request("owner", request.request_id)["state"] == "interrupted"
        )
        before = len(provider.requests)
        row = history.request("owner", request.request_id)
        assert history.page("owner", row["conversation"])["turns"] == []
        _, reply = await service.chat(None, request, "owner")
        assert reply.error_code == "request_interrupted" and len(provider.requests) == before
        assert "charged" in service.recover("owner", request.request_id)["notice"]

    asyncio.run(scenario())


def test_claim_before_crash_and_cancelled_work_remain_explicit(scoped_setup):
    config, history, corpus = scoped_setup
    request = ChatRequest(message="trajectory", request_id="before_crash")
    history.claim("owner", request.request_id, fingerprint(request), request.scope, None)
    provider = ScriptedProvider("timeout")
    service = ChatService(config, provider, corpus, history=history)

    async def scenario():
        _, reply = await service.chat(None, request, "owner")
        assert reply.error_code == "request_interrupted" and not provider.requests
        cancelled = request.model_copy(update={"request_id": "cancelled1"})
        task = asyncio.create_task(service.chat(None, cancelled, "owner"))
        await asyncio.sleep(0.02)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert history.request("owner", "cancelled1")["state"] == "cancelled"
        before = len(provider.requests)
        _, reply = await service.chat(None, cancelled, "owner")
        assert reply.error_code == "request_cancelled" and len(provider.requests) == before
        assert not history.page("owner", reply.conversation_id)["turns"]

    asyncio.run(scenario())


def test_legacy_migration_backup_and_repeated_startup(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE conversations(id TEXT PRIMARY KEY,owner TEXT,title TEXT,"
            "created REAL,updated REAL)"
        )
        db.execute(
            "INSERT INTO conversations VALUES(?,?,?,?,?)",
            ("a" * 32, History.owner("owner"), "legacy", 1, 1),
        )
    history = History(path)
    assert history.scope("owner", "a" * 32) == SourceScope()
    assert len(list((tmp_path / "backups").glob("*.sqlite3"))) == 1
    History(path)
    assert len(list((tmp_path / "backups").glob("*.sqlite3"))) == 1
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 2


def test_recovery_api_owner_initialization_preview_and_no_duplicate_turn(scoped_setup):
    config, history, corpus = scoped_setup
    provider = ScriptedProvider()
    service = ChatService(config, provider, corpus, history=history)
    payload = {
        "message": "trajectory",
        "request_id": "api_lost_first",
        "scope": {"kind": "videos", "video_ids": [A]},
    }
    with TestClient(create_app(config, service)) as client:
        assert client.post("/api/chat", json=payload).status_code == 409 and not provider.requests
        owner = client.get("/api/conversations").json()["owner_marker"]
        assert owner
        first = client.post("/api/chat", json=payload).json()
        count = len(provider.requests)
        recovered = client.get("/api/requests/api_lost_first").json()
        assert (
            recovered["state"] == "completed"
            and recovered["answer"]["reply_id"] == first["reply_id"]
        )
        assert client.post("/api/chat", json=payload).json()["reply_id"] == first["reply_id"]
        assert len(provider.requests) == count
        assert (
            len(client.get(f"/api/conversations/{first['conversation_id']}").json()["turns"]) == 1
        )
        preview = client.post(
            "/api/library/search",
            json={
                "query": "trajectory",
                "k": 3,
                "video_ids_or_null": None,
                "scope": payload["scope"],
            },
        ).json()
        assert {s["video_id"] for s in preview["sources"]} == {A}
        assert (
            client.post(
                "/api/library/search",
                json={
                    "query": "trajectory",
                    "k": 3,
                    "video_ids_or_null": [B],
                    "scope": payload["scope"],
                },
            ).status_code
            == 400
        )
        client.cookies.clear()
        assert client.get("/api/requests/api_lost_first").status_code == 404
