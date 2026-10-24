"""Reproducible retrieval evaluation and offline human-review sheets. No paid calls."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import subprocess
import time
from pathlib import Path

from kbfromyt.chat.config import ChatConfig
from kbfromyt.evaluation import Gold
from kbfromyt.overviews import OVERVIEW_VERSION, broad_question
from kbfromyt.processing import PROCESSING_VERSION
from kbfromyt.retrieval import broad_search, search
from kbfromyt.semantic import INDEX_VERSION, FastEmbedder, SemanticIndex
from kbfromyt.store import Store

if __package__:
    from .evaluate_chat import ChatBenchmark, ChatCase
else:
    from evaluate_chat import ChatBenchmark, ChatCase


def group_metrics(hits, groups: list[list[Gold]], k: int) -> dict:
    """Maximum bipartite matching: equivalent passages earn one gold-point credit."""
    if not groups:
        return {"no_candidates": not hits[:k]}
    matched: dict[int, int] = {}

    def assign(hit_index, seen):
        hit = hits[hit_index]
        for index, alternatives in enumerate(groups):
            if index in seen or not any(
                hit.video_id == gold.video_id
                and max(hit.start, gold.start) < min(hit.end, gold.end)
                for gold in alternatives
            ):
                continue
            seen.add(index)
            if index not in matched or assign(matched[index], seen):
                matched[index] = hit_index
                return True
        return False

    gains, first = [], 0
    for rank in range(min(k, len(hits))):
        gain = int(assign(rank, set()))
        gains.append(gain)
        if gain and not first:
            first = 1 / (rank + 1)
    ideal = sum(1 / math.log2(i + 2) for i in range(min(k, len(groups))))
    return {
        "recall": len(matched) / len(groups),
        "mrr": first,
        "ndcg": sum(g / math.log2(i + 2) for i, g in enumerate(gains)) / ideal,
    }


def allowed_videos(case: ChatCase, known: set[str], playlists: dict[str, list[str]]) -> list[str]:
    if case.scope.kind == "library":
        return sorted(known)
    if case.scope.kind == "playlist":
        if case.scope.playlist_id not in playlists:
            raise ValueError(f"Missing playlist mapping: {case.id}")
        selected = playlists[case.scope.playlist_id]
    else:
        selected = case.scope.video_ids
    if not selected or set(selected) - known:
        raise ValueError(f"Invalid source scope: {case.id}")
    return sorted(set(selected))


def validate_sources(benchmark: ChatBenchmark, config: ChatConfig) -> dict:
    """Check annotations, including held-out gold bounds, without ranking held-out queries."""
    from kbfromyt.chat.history import History

    playlists = (
        {p["id"]: p["video_ids"] for p in History(config.state_db).playlists()}
        if any(c.scope.kind == "playlist" for c in benchmark.cases)
        else {}
    )
    with Store(config.db) as store:
        known = {p.video.video_id: p for p in store.videos()}
        for case in benchmark.cases:
            allowed = allowed_videos(case, set(known), playlists)
            for gold in [*case.relevant, *(g for group in case.alternative_groups for g in group)]:
                if gold.video_id not in allowed or gold.end > known[gold.video_id].video.duration:
                    raise ValueError(f"Gold outside source scope/bounds: {case.id}")
        return {
            "cases": len(benchmark.cases),
            "source_snapshot": store.snapshot_hash(),
            "human_reviewed": sum(c.review_status == "human_reviewed" for c in benchmark.cases),
        }


def report(
    benchmark: ChatBenchmark,
    config: ChatConfig,
    *,
    semantic=None,
    split="development",
    playlists=None,
) -> dict:
    rows = []
    with Store(config.db) as store:
        known = {p.video.video_id: p for p in store.videos()}
        selected = [case for case in benchmark.cases if case.split == split]
        if not selected:
            raise ValueError("selected benchmark split is empty")
        for case in selected:
            allowed = allowed_videos(case, set(known), playlists or {})
            groups = case.alternative_groups or [[gold] for gold in case.relevant]
            for group in groups:
                for gold in group:
                    if (
                        gold.video_id not in allowed
                        or gold.end > known[gold.video_id].video.duration
                    ):
                        raise ValueError(f"Gold outside source scope/bounds: {case.id}")
            # Frozen history concatenation is explicitly not a model query rewrite.
            previous = [*case.setup_turns, *([case.setup_question] if case.setup_question else [])]
            query = " ".join([*previous[-3:], case.question])
            started = time.perf_counter()
            if broad_question(case.question) or case.category == "broad":
                hits, trace = broad_search(store, query, 10, semantic, allowed)
                route = "overview"
            else:
                hits = search(store, query, 10, semantic, parent_child_limit=3, video_ids=allowed)
                trace, route = [], "detail"
            rows.append(
                {
                    "id": case.id,
                    "category": case.category,
                    "review_status": case.review_status,
                    "route": route,
                    "query": query,
                    "scope": case.scope.model_dump(),
                    "allowed_video_ids": allowed,
                    "chunk_ids": [hit.id for hit in hits],
                    "scope_violations": sum(hit.video_id not in allowed for hit in hits),
                    "at_5": group_metrics(hits, groups, 5),
                    "at_10": group_metrics(hits, groups, 10),
                    "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                    "trace": trace,
                    "required_point_review": "pending" if case.required_points else "not_annotated",
                }
            )
        snapshot = store.snapshot_hash()
    try:
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        revision = "unavailable"

    def aggregate(reviewed_only):
        selected_rows = [
            r for r in rows if not reviewed_only or r["review_status"] == "human_reviewed"
        ]
        return {
            str(k): {
                metric: statistics.mean(values) if values else None
                for metric in ("recall", "mrr", "ndcg")
                for values in [
                    [r[f"at_{k}"][metric] for r in selected_rows if metric in r[f"at_{k}"]]
                ]
            }
            for k in (5, 10)
        }

    return {
        "metadata": {
            "git_revision": revision,
            "benchmark_version": benchmark.version,
            "split": split,
            "benchmark_hash": hashlib.sha256(benchmark.model_dump_json().encode()).hexdigest(),
            "source_snapshot": snapshot,
            "processing_version": PROCESSING_VERSION,
            "index_version": INDEX_VERSION,
            "overview_version": OVERVIEW_VERSION,
            "retrieval_mode": "hybrid" if semantic else "lexical",
            "embedding_model": config.embedding_model if semantic else None,
            "query_mode": "frozen_setup_concatenation_no_model_rewrite",
            "provider_calls": 0,
            "provider_model": config.model,
            "prompt_hash": prompt_hash(),
            "budgets": {
                name: getattr(config, name)
                for name in (
                    "max_requests",
                    "max_tool_calls",
                    "max_passages",
                    "input_budget",
                    "evidence_budget",
                )
            },
            "retrieval_settings": {
                "k": [5, 10],
                "parent_child_limit": 3,
                "dense_threshold": 0.45,
                "context_expansion": "not_evaluated",
            },
        },
        "rows": rows,
        "candidate_metrics": aggregate(False),
        "human_reviewed_metrics": aggregate(True),
        "scope_violations": sum(r["scope_violations"] for r in rows),
        "answer_quality": "not_evaluated; human source/claim review required",
        "note": (
            "Interval overlap is retrieval credit, not proof that a required "
            "answer point is supported."
        ),
    }


def prompt_hash() -> str:
    from kbfromyt.chat.agent import CHECK_INSTRUCTIONS, INSTRUCTIONS

    return hashlib.sha256((INSTRUCTIONS + CHECK_INSTRUCTIONS).encode()).hexdigest()


def review_sheet(benchmark: ChatBenchmark) -> dict:
    return {
        "benchmark_version": benchmark.version,
        "instructions": "Inspect sources in context. Record attribution, completeness, "
        "false abstention, "
        "unsupported claims and failure category; do not infer support from literal quotes alone.",
        "cases": [
            {
                "id": c.id,
                "question": c.question,
                "scope": c.scope.model_dump(),
                "gold_groups": [
                    [g.model_dump() for g in group]
                    for group in (c.alternative_groups or [[g] for g in c.relevant])
                ],
                "required_points": c.required_points,
                "qualifications": c.qualifications,
                "reviewer": None,
                "gold_valid": None,
                "claim_support": None,
                "attribution_correct": None,
                "completeness": None,
                "false_abstention": None,
                "unsupported_answer": None,
                "failure_category": None,
                "notes": "",
            }
            for c in benchmark.cases
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, default=Path("examples/chat-playlist-benchmark.json"))
    parser.add_argument("--output", type=Path, default=Path("data/live/quality-development.json"))
    parser.add_argument("--split", choices=["development", "heldout"], default="development")
    parser.add_argument("--hybrid", action="store_true", help="stop chat first; opens local Qdrant")
    parser.add_argument("--review-sheet", action="store_true", help="export review template only")
    parser.add_argument(
        "--validate-only", action="store_true", help="validate all source bounds without ranking"
    )
    args = parser.parse_args()
    benchmark = ChatBenchmark.model_validate_json(args.file.read_text(encoding="utf-8"))
    semantic = None
    try:
        config = ChatConfig.from_env()
        validation = validate_sources(benchmark, config) if not args.review_sheet else None
        if args.hybrid and not args.review_sheet and not args.validate_only:
            from dotenv import load_dotenv

            load_dotenv()
            semantic = SemanticIndex(config.index_dir, FastEmbedder(config.embedding_model))
        result = (
            review_sheet(benchmark)
            if args.review_sheet
            else validation
            if args.validate_only
            else report(benchmark, config, semantic=semantic, split=args.split)
        )
        if not args.review_sheet and not args.validate_only:
            result["source_validation"] = validation
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Saved {args.output}; no provider calls. Human review remains separate.")
    finally:
        if semantic:
            semantic.close()


if __name__ == "__main__":
    main()
