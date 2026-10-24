import asyncio
from collections import Counter
from pathlib import Path

import pytest

from kbfromyt.chat.config import ChatConfig
from kbfromyt.chat.contracts import ChatRequest
from kbfromyt.chat.service import ChatService
from kbfromyt.chat.tools import Corpus
from scripts.evaluate_chat import ChatBenchmark, retrieval_report
from tests.test_chat import ScriptedProvider


def test_twenty_case_playlist_benchmark_contract():
    benchmark = ChatBenchmark.model_validate_json(
        Path("examples/chat-playlist-benchmark.json").read_text(encoding="utf-8")
    )
    assert len(benchmark.cases) == 20
    assert Counter(c.category for c in benchmark.cases) == {
        "direct": 8,
        "paraphrase": 4,
        "followup": 3,
        "unanswerable": 3,
        "partial": 2,
    }
    assert all(c.setup_question for c in benchmark.cases if c.category == "followup")
    assert "human" in benchmark.review_status.lower()


def test_retrieval_evaluation_does_not_call_model(store, video, tmp_path):
    store.import_video(video)
    benchmark = ChatBenchmark.model_validate(
        {
            "name": "Fixture",
            "playlist_id": "fixture",
            "review_status": "test",
            "cases": [
                {
                    "id": "q1",
                    "category": "direct",
                    "question": "trajectory",
                    "setup_question": None,
                    "expected_status": "grounded",
                    "relevant": [{"video_id": video.video_id, "start": 20, "end": 40}],
                }
            ],
        }
    )
    result = retrieval_report(benchmark, ChatConfig(db=tmp_path / "kb.sqlite3", semantic=False))
    assert result["means"]["bounded_parents"]["recall"] == 1


def test_cancelled_request_never_enters_memory(store, video, tmp_path):
    store.import_video(video)
    config = ChatConfig(db=tmp_path / "kb.sqlite3", semantic=False)
    corpus = Corpus(config)
    provider = ScriptedProvider("timeout")
    service = ChatService(config, provider, corpus)

    async def scenario():
        key, session = service.sessions.get(None)
        pending = asyncio.create_task(
            service.chat(key, ChatRequest(message="test", request_id="request_1"))
        )
        await asyncio.sleep(0.01)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert session.turns == [] and session.completed == {}
        assert not session.lock.locked()

    try:
        asyncio.run(scenario())
    finally:
        corpus.close()


def test_duplicate_concurrent_requests_only_run_once(store, video, tmp_path):
    store.import_video(video)
    config = ChatConfig(db=tmp_path / "kb.sqlite3", semantic=False)
    corpus = Corpus(config)
    provider = ScriptedProvider("no_support")
    service = ChatService(config, provider, corpus)

    async def scenario():
        key, session = service.sessions.get(None)
        request = ChatRequest(message="question", request_id="request_1")
        replies = await asyncio.gather(service.chat(key, request), service.chat(key, request))
        assert replies[0][1].reply_id == replies[1][1].reply_id
        assert len(provider.requests) == 2 and len(session.turns) == 1

    try:
        asyncio.run(scenario())
    finally:
        corpus.close()


def test_single_pass_comparison_is_bounded_and_idempotency_checks_mode(store, video, tmp_path):
    store.import_video(video)
    config = ChatConfig(db=tmp_path / "kb.sqlite3", semantic=False)
    corpus = Corpus(config)
    provider = ScriptedProvider("refine")
    service = ChatService(config, provider, corpus)

    async def scenario():
        key, reply = await service.chat(
            None, ChatRequest(message="tools", request_id="request_1", agentic=False)
        )
        assert reply.status == "grounded" and reply.usage.provider_requests == 3
        _, conflict = await service.chat(
            key, ChatRequest(message="tools", request_id="request_1", agentic=True)
        )
        assert conflict.error_code == "request_conflict"

    try:
        asyncio.run(scenario())
    finally:
        corpus.close()


def test_dense_query_filters_document_ids(tmp_path, store, video):
    from kbfromyt.semantic import SemanticIndex
    from tests.test_semantic import TestVectors

    store.import_video(video)
    index = SemanticIndex(tmp_path / "vectors", TestVectors())
    try:
        index.rebuild(store)
        allowed = [store.videos()[0].chunks[0].id]
        rows = index.search(store, "trajectory", threshold=0, document_ids=allowed)
        assert rows[0] == [] and rows[1] == [] and rows[2] == allowed
        assert index.search(store, "trajectory", document_ids=[]) == [[], [], []]
    finally:
        index.close()
