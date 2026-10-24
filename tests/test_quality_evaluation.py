from collections import Counter
from pathlib import Path

import pytest
from pydantic import ValidationError

from kbfromyt.chat.config import ChatConfig
from kbfromyt.evaluation import Gold
from scripts.evaluate_chat import ChatBenchmark
from scripts.evaluate_quality import group_metrics, report, review_sheet

A, B = "SCOPE000001", "SCOPE000002"


def test_fifty_candidate_cases_and_split_contract():
    benchmark = ChatBenchmark.model_validate_json(
        Path("examples/chat-playlist-benchmark.json").read_text(encoding="utf-8")
    )
    assert len(benchmark.cases) == 50
    assert Counter(case.split for case in benchmark.cases) == {"development": 35, "heldout": 15}
    assert Counter(case.category for case in benchmark.cases) == {
        "direct": 12,
        "paraphrase": 8,
        "followup": 8,
        "unanswerable": 6,
        "partial": 4,
        "broad": 8,
        "scope": 4,
    }
    assert all(case.review_status != "human_reviewed" for case in benchmark.cases)
    assert all(case.family and case.qualifications for case in benchmark.cases)
    assert len(review_sheet(benchmark)["cases"]) == 50
    mutated = benchmark.model_dump()
    mutated["cases"][0]["id"] = mutated["cases"][1]["id"]
    with pytest.raises(ValidationError):
        ChatBenchmark.model_validate(mutated)


def test_group_credit_handles_alternatives_and_competing_matches():
    hits = [Gold(video_id=A, start=0, end=10), Gold(video_id=B, start=0, end=10)]
    flexible = [Gold(video_id=A, start=0, end=10), Gold(video_id=B, start=0, end=10)]
    only_a = [Gold(video_id=A, start=0, end=10)]
    assert group_metrics(hits, [flexible, only_a], 10) == {"recall": 1, "mrr": 1, "ndcg": 1}
    assert group_metrics(hits, [flexible], 10)["recall"] == 1


def test_quality_report_separates_candidates_and_human_quality(store, video, tmp_path):
    video.video_id = A
    store.import_video(video)
    config = ChatConfig(db=tmp_path / "kb.sqlite3", semantic=False)
    benchmark = ChatBenchmark.model_validate(
        {
            "name": "fixture",
            "playlist_id": "fixture",
            "review_status": "pending",
            "cases": [
                {
                    "id": "q",
                    "category": "direct",
                    "question": "trajectory",
                    "setup_question": None,
                    "expected_status": "grounded",
                    "relevant": [{"video_id": A, "start": 0, "end": 10}],
                    "scope": {"kind": "videos", "video_ids": [A]},
                }
            ],
        }
    )
    result = report(benchmark, config)
    assert result["scope_violations"] == 0 and result["metadata"]["provider_calls"] == 0
    assert result["human_reviewed_metrics"]["5"]["recall"] is None
    assert result["candidate_metrics"]["5"]["recall"] == 1
