import json
import math
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from kbfromyt.answering import answer, validate_synthesis
from kbfromyt.cli import main
from kbfromyt.evaluation import Case, Gold, evaluate, metrics
from kbfromyt.ingest import select_track, video_id
from kbfromyt.models import RawSegment, SourceChapter, VideoInput
from kbfromyt.processing import process
from kbfromyt.retrieval import search


@pytest.mark.parametrize(
    "start,end", [(4, 3), (0, 0), (-1, 1), (0, float("inf")), (float("nan"), 5)]
)
def test_invalid_timestamps(start, end):
    with pytest.raises(ValidationError):
        RawSegment(start=start, end=end, text="evidence")


def test_video_contract_rejects_bad_timeline(video):
    data = video.model_dump()
    data["duration"] = 10
    with pytest.raises(ValidationError):
        VideoInput.model_validate(data)
    data = video.model_dump()
    data["chapters"] = [{"start": 60, "title": "A"}, {"start": 20, "title": "B"}]
    with pytest.raises(ValidationError):
        VideoInput.model_validate(data)


def test_provenance_and_chapter_boundaries(video):
    p = process(video, max_words=10)
    assert len(p.chapters) == 2
    assert {sid for c in p.chunks for sid in c.segment_ids} == {s.id for s in p.segments}
    lookup = {s.id: s for s in p.segments}
    parents = {c.id: c for c in p.chapters}
    for chunk in p.chunks:
        assert set(chunk.segment_ids) <= set(parents[chunk.chapter_id].segment_ids)
        assert chunk.start == lookup[chunk.segment_ids[0]].start
        assert chunk.text == " ".join(lookup[sid].text for sid in chunk.segment_ids)
    assert process(video, max_words=10) == p


def test_normalization_preserves_raw_and_duplicate_segments(video):
    video.segments[0].text = "  <i>Agent</i> &amp; tools\n "
    video.segments[1].text = video.segments[0].text
    p = process(video)
    assert p.segments[0].text == "Agent & tools"
    assert p.segments[0].raw_text == video.segments[0].text
    assert p.segments[0].id != p.segments[1].id
    assert len(p.segments) == len(video.segments)


def test_timed_fallback_and_intro(video):
    video.chapters = []
    assert len(process(video, chapter_seconds=60).chapters) == 2
    video.chapters = [SourceChapter(start=60, title="Second")]
    assert process(video).chapters[0].title == "Introduction"


def test_blank_and_huge_segments(video):
    video.segments = [RawSegment(start=0, end=10, text="<i> </i>")]
    with pytest.raises(ValueError, match="no text"):
        process(video)
    video.segments = [RawSegment(start=0, end=10, text="word " * 1000)]
    assert len(process(video).chunks[0].text.split()) == 1000


def test_atomic_idempotent_replacement(store, video):
    assert store.import_video(video)
    revision = store.revision
    assert not store.import_video(video)
    assert store.revision == revision
    assert store.stats()["videos"] == 1
    assert store.videos()[0].video == video
    video.title = "Updated source"
    video.segments = [RawSegment(start=0, end=10, text="Completely different zebra evidence.")]
    assert store.import_video(video)
    assert not store.lexical("trajectory", "chunk")
    assert store.lexical("zebra", "chunk")
    assert store.stats()["videos"] == 1


def test_rollback_keeps_previous_content(store, video):
    store.import_video(video)
    revision = store.revision
    store.db.execute(
        "CREATE TRIGGER reject_doc BEFORE INSERT ON documents "
        "BEGIN SELECT RAISE(ABORT, 'test rollback'); END;"
    )
    video.title = "Changed"
    with pytest.raises(Exception, match="test rollback"):
        store.import_video(video)
    assert store.revision == revision
    assert store.videos()[0].video.title != "Changed"
    assert store.lexical("trajectory", "chunk")


def test_search_citations_abstention_and_context(store, video):
    store.import_video(video)
    hit = search(store, "trajectory tool selection", 1)[0]
    assert "Trajectory evaluation" in hit.text
    assert hit.url.endswith("DEMOvideo01&t=0s")
    assert hit.segment_ids
    assert "Production monitoring" not in " ".join(hit.context)
    assert search(store, "photosynthesis chlorophyll") == []
    assert search(store, '" OR * : ()') == []
    assert search(store, "") == []
    with pytest.raises(ValueError):
        search(store, "tools", 0)
    assert answer("unknown", [])["abstained"]
    assert answer("tools", [hit])["synthesis"] is None


@pytest.mark.parametrize(
    "value",
    [
        "dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ?t=3",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtube.com/shorts/dQw4w9WgXcQ",
    ],
)
def test_video_ids(value):
    assert video_id(value) == "dQw4w9WgXcQ"


@pytest.mark.parametrize(
    "value",
    ["https://evil.example/watch?v=dQw4w9WgXcQ", "bad", "https://youtube.com/playlist?list=123"],
)
def test_reject_bad_video_ids(value):
    with pytest.raises(ValueError):
        video_id(value)


def test_manual_track_precedes_auto_language_preference():
    auto_en = SimpleNamespace(language_code="en", is_generated=True)
    manual_ru = SimpleNamespace(language_code="ru", is_generated=False)
    manual_en = SimpleNamespace(language_code="en", is_generated=False)
    assert select_track([auto_en, manual_ru], ["en", "ru"]) is manual_ru
    assert select_track([manual_ru, manual_en], ["en", "ru"]) is manual_en


def test_synthesis_rejects_unverified_citations(store, video):
    store.import_video(video)
    hits = search(store, "trajectory")
    valid = {"claims": [{"text": "Check the trajectory.", "citations": [hits[0].id]}]}
    assert validate_synthesis(json.dumps(valid), hits).claims
    valid["claims"][0]["citations"] = ["made-up"]
    with pytest.raises(ValueError, match="unknown citation"):
        validate_synthesis(json.dumps(valid), hits)
    valid["claims"][0]["citations"] = []
    with pytest.raises(ValidationError):
        validate_synthesis(json.dumps(valid), hits)
    with pytest.raises(ValidationError):
        validate_synthesis("not json", hits)


def test_hand_computed_metrics_and_unique_credit(store, video):
    store.import_video(video)
    hit = search(store, "trajectory", 1)[0]
    gold = [
        Gold(video_id=video.video_id, start=20, end=40),
        Gold(video_id=video.video_id, start=60, end=90),
    ]
    result = metrics([hit, hit], gold, 2)
    assert result["recall"] == 0.5
    assert result["mrr"] == 1
    assert result["ndcg"] == pytest.approx(1 / (1 + 1 / math.log2(3)))
    assert metrics([], [], 5) == {"abstention": 1}
    assert metrics([hit], [], 5) == {"abstention": 0}
    with pytest.raises(ValueError):
        evaluate(store, [])
    result = evaluate(
        store, [Case(query="trajectory", relevant=gold), Case(query="chlorophyll", relevant=[])]
    )
    assert result["means"]["abstention"] == 1


def test_cli_lifecycle(tmp_path, capsys):
    from pathlib import Path

    root = Path(__file__).parents[1]
    args = ["--db", str(tmp_path / "cli.sqlite3")]
    assert main([*args, "import", str(root / "examples/demo.json")]) == 0
    assert json.loads(capsys.readouterr().out)["changed"]
    assert main([*args, "import", str(root / "examples/demo.json")]) == 0
    assert not json.loads(capsys.readouterr().out)["changed"]
    assert main([*args, "ask", "trajectory"]) == 0
    assert json.loads(capsys.readouterr().out)["evidence"][0]["url"]
    assert main([*args, "evaluate", str(root / "examples/benchmark.json")]) == 0
    assert json.loads(capsys.readouterr().out)["means"]["recall"] == 1
    assert main([*args, "import", str(tmp_path / "missing.json")]) == 1
    assert "yt-kb:" in capsys.readouterr().err
