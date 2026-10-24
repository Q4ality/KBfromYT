import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from kbfromyt.chat.agent import CHECK_INSTRUCTIONS, INSTRUCTIONS, Agent
from kbfromyt.chat.config import ChatConfig
from kbfromyt.chat.history import History
from kbfromyt.chat.service import ChatService
from kbfromyt.chat.tools import Corpus
from kbfromyt.models import RawSegment, SourceChapter
from kbfromyt.overviews import broad_question, build_overview
from kbfromyt.processing import process
from kbfromyt.retrieval import broad_search, near_duplicate
from kbfromyt.semantic import INDEX_VERSION, SemanticIndex, token_windows
from kbfromyt.web.app import create_app
from tests.test_chat import ScriptedProvider


def tiny_tokenizer():
    from tokenizers import Tokenizer, models, pre_tokenizers, processors

    tokenizer = Tokenizer(models.WordLevel({"[UNK]": 0, "[CLS]": 1, "[SEP]": 2}, unk_token="[UNK]"))
    tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
    tokenizer.post_processor = processors.TemplateProcessing(
        single="[CLS] $A [SEP]", special_tokens=[("[CLS]", 1), ("[SEP]", 2)]
    )
    return tokenizer


def test_token_windows_cover_unicode_source_and_fit_tokenizer():
    tokenizer = tiny_tokenizer()
    text = "  " + " Слова 中文 punctuation, source." * 80 + " terminalneedle "
    windows = token_windows(text, tokenizer, 16)
    assert len(windows) > 1 and windows[0].start == 0 and windows[-1].end == len(text)
    covered = set()
    for window in windows:
        assert window.text == text[window.start : window.end]
        assert len(tokenizer.encode(window.text).ids) <= 16
        covered.update(range(window.start, window.end))
    assert all(i in covered for i, char in enumerate(text) if not char.isspace())
    assert all(a.end > b.start for a, b in zip(windows, windows[1:], strict=False))


class WindowVectors:
    name = "tail-regression"
    token_limit = 16

    def __init__(self):
        self.tokenizer = tiny_tokenizer()

    def windows(self, text):
        return token_windows(text, self.tokenizer, self.token_limit)

    def embed(self, texts, *, query=False):
        if not query:
            assert all(len(self.tokenizer.encode(t).ids) <= self.token_limit for t in texts)
        return [[0.0, 1.0] if "terminalneedle" in text else [1.0, 0.0] for text in texts]


def test_index_retrieves_tail_and_aggregates_windows_to_source_ids(store, video, tmp_path):
    pytest.importorskip("qdrant_client")
    video.segments = [RawSegment(start=0, end=40, text="ordinary " * 200 + "terminalneedle")]
    store.import_video(video)
    index = SemanticIndex(tmp_path / "vectors", WindowVectors())
    try:
        index.rebuild(store)
        manifest = json.loads(index.manifest.read_text())
        assert manifest["count"] > manifest["documents"]
        assert manifest["max_window_tokens"] <= 16
        assert manifest["index_version"] == INDEX_VERSION
        rows = index.search(store, "terminalneedle", threshold=0.9)
        assert rows[0] == [f"{video.video_id}:video"]
        assert rows[2] == [f"{video.video_id}:k0"]
        manifest["index_version"] = "old-truncated-index"
        index.manifest.write_text(json.dumps(manifest))
        with pytest.raises(ValueError, match="format is stale"):
            index.search(store, "terminalneedle")
    finally:
        index.close()


def test_overviews_are_exact_linked_passages_across_the_video(video, store):
    video.chapters = [SourceChapter(start=i * 20, title=f"Topic {i}") for i in range(6)]
    video.segments = [
        RawSegment(
            start=i * 20, end=i * 20 + 10, text=f"The author argues a position in section {i}."
        )
        for i in range(6)
    ]
    processed = process(video)
    overview = build_overview(processed)
    assert len(overview.passages) == 6
    chunks = {c.id: c for c in processed.chunks}
    for passage in overview.passages:
        source = chunks[passage.chunk_id]
        assert passage.excerpt == source.text and passage.segment_ids == source.segment_ids
        assert passage.url.endswith(f"t={int(source.start)}s")
    store.import_video(video)
    assert store.overviews()[0] == overview
    store.db.execute("DELETE FROM overviews")
    store.db.commit()
    assert store.needs_overviews()
    store.refresh_overviews()
    assert not store.needs_overviews()


def test_broad_search_uses_facets_and_diversifies_original_evidence(store, video):
    for number in range(4):
        clone = video.model_copy(deep=True)
        clone.video_id = f"VIDEO{number:06d}"
        clone.segments[0].text = (
            " ".join(f"scenario{number}_{i}" for i in range(40))
            + " trajectory evaluation. "
            + clone.segments[0].text
        )
        store.import_video(clone)
    hits, trace = broad_search(store, "trajectory evaluation", 8)
    assert len(trace) == 3 and len({hit.video_id for hit in hits}) == 4
    assert all(sum(h.video_id == hit.video_id for h in hits) <= 2 for hit in hits)
    assert all(hit.segment_ids and hit.url for hit in hits)
    filtered, _ = broad_search(store, "trajectory evaluation", 8, video_ids=["VIDEO000001"])
    assert all(hit.video_id == "VIDEO000001" for hit in filtered)


def test_repeated_openings_do_not_masquerade_as_distinct_sources():
    opening = " ".join(f"word{i}" for i in range(60))
    assert near_duplicate(opening + " first topic", opening + " second topic")
    assert not near_duplicate(opening, "A distinct argument about source evidence and conclusions.")


def test_broad_agent_records_coverage_and_attribution_policy(store, video, tmp_path):
    store.import_video(video)
    config = ChatConfig(
        db=tmp_path / "kb.sqlite3", semantic=False, evidence_budget=16000, input_budget=24000
    )
    corpus = Corpus(config)
    try:
        provider = ScriptedProvider()
        reply = asyncio.run(
            Agent(config, provider, corpus).run("Who was responsible for the killing?", [], 0)
        )
        assert reply.status == "grounded" and reply.coverage.mode == "overview"
        assert len(reply.retrieval) == 3 and reply.coverage.evidence_videos == 1
        assert provider.requests[0]["choice"]["name"] == "search_overviews"
        assert "independent proof" in INSTRUCTIONS and "independent proof" in CHECK_INSTRUCTIONS
        assert broad_question("Какие доказательства приводит официальная версия?")
        assert not broad_question("В каком году был опубликован документ?")
    finally:
        corpus.close()


def test_overview_api_playlist_filter_and_pagination(store, video, tmp_path):
    for number in range(3):
        clone = video.model_copy(deep=True)
        clone.video_id = f"VIDEO{number:06d}"
        store.import_video(clone)
    config = ChatConfig(db=tmp_path / "kb.sqlite3", semantic=False)
    history = History(tmp_path / "state.sqlite3")
    history.save_playlist(
        {
            "id": "playlist-one",
            "video_ids": ["VIDEO000001"],
            "url": "https://www.youtube.com/playlist?list=playlist-one",
        }
    )
    service = ChatService(config, ScriptedProvider(), Corpus(config), history=history)
    with TestClient(create_app(config, service)) as client:
        page = client.get("/api/library/overview?limit=2").json()
        assert page["total_videos"] == 3 and len(page["videos"]) == 2 and page["has_more"]
        filtered = client.get("/api/library/overview?playlist=playlist-one").json()
        assert [v["video_id"] for v in filtered["videos"]] == ["VIDEO000001"]
        assert client.get("/api/library/overview?playlist=missing").status_code == 404
        assert client.get("/api/library/overview?limit=1000").status_code == 422
        preview = client.post(
            "/api/library/search?broad=true",
            json={"query": "trajectory evaluation", "video_ids_or_null": None, "k": 8},
        ).json()
        assert preview["mode"] == "overview" and len(preview["queries"]) == 3
        assert preview["sources"]
        assert (
            len({s["video_id"] for s in preview["sources"]}) == 1
        )  # Identical source copies deduplicate.
        assert not service.provider.requests
