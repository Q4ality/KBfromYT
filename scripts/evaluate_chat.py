"""Playlist chat evaluation. No model calls unless --live is explicitly supplied.

Stop the local chat server before --live: Qdrant local has one process owner.
Review the resulting claims against source videos; automated scores do not prove entailment.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import statistics
import subprocess
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse
from uuid import uuid4

from pydantic import Field, model_validator

from kbfromyt.chat.config import ChatConfig
from kbfromyt.chat.contracts import AnswerEnvelope, ChatRequest, SourceScope
from kbfromyt.chat.memory import configure_tokenizer
from kbfromyt.chat.providers.openai import OpenAIProvider
from kbfromyt.chat.scope import resolve_scope
from kbfromyt.chat.service import ChatService
from kbfromyt.chat.tools import Corpus
from kbfromyt.evaluation import Gold, metrics
from kbfromyt.models import Contract
from kbfromyt.retrieval import search
from kbfromyt.store import Store


class ChatCase(Contract):
    id: str
    category: Literal[
        "direct", "paraphrase", "followup", "unanswerable", "partial", "broad", "scope"
    ]
    question: str
    setup_question: str | None
    expected_status: Literal["grounded", "partial", "no_support"]
    relevant: list[Gold]
    scope: SourceScope = Field(default_factory=SourceScope)
    setup_turns: list[str] = Field(default_factory=list)
    required_points: list[str] = Field(default_factory=list)
    qualifications: list[str] = Field(default_factory=list)
    alternative_groups: list[list[Gold]] = Field(default_factory=list)
    review_status: Literal["provisional", "assistant_inspected", "human_reviewed"] = "provisional"
    reviewer: str | None = None
    split: Literal["development", "heldout"] = "development"
    family: str = ""
    tags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def reviewed(self):
        if self.review_status == "human_reviewed" and not self.reviewer:
            raise ValueError("human-reviewed cases require a reviewer")
        if any(not group for group in self.alternative_groups):
            raise ValueError("alternative groups must not be empty")
        return self


class ChatBenchmark(Contract):
    version: str = "legacy-20"
    name: str
    playlist_id: str
    review_status: str
    cases: list[ChatCase]

    @model_validator(mode="after")
    def unique_cases(self):
        ids = [case.id for case in self.cases]
        if not ids or len(set(ids)) != len(ids):
            raise ValueError("benchmark must have unique nonempty cases")
        families = {}
        for case in self.cases:
            if case.family:
                if case.family in families and families[case.family] != case.split:
                    raise ValueError("related cases must stay in one split")
                families[case.family] = case.split
        return self


def retrieval_report(benchmark: ChatBenchmark, config: ChatConfig) -> dict:
    """Lexical baseline comparison; no provider or semantic client required."""
    rows = []
    with Store(config.db) as store:
        videos = {p.video.video_id: p for p in store.videos()}
        for case in benchmark.cases:
            allowed = resolve_scope(case.scope, set(videos), [])
            for gold in case.relevant:
                if gold.video_id not in videos or gold.end > videos[gold.video_id].video.duration:
                    raise ValueError(f"Gold interval is not in this corpus: {case.id}")
            previous = [*case.setup_turns, *([case.setup_question] if case.setup_question else [])]
            query = " ".join([*previous[-3:], case.question])
            rows.append(
                {
                    "id": case.id,
                    "category": case.category,
                    "flat_parent_baseline": metrics(
                        search(store, query, 5, video_ids=allowed), case.relevant, 5
                    ),
                    "bounded_parents": metrics(
                        search(store, query, 5, parent_child_limit=3, video_ids=allowed),
                        case.relevant,
                        5,
                    ),
                }
            )
        snapshot = store.snapshot_hash()
    means = {}
    for mode in ("flat_parent_baseline", "bounded_parents"):
        answerable = [r[mode] for r in rows if "recall" in r[mode]]
        means[mode] = (
            {
                key: sum(r[key] for r in answerable) / len(answerable)
                for key in ("recall", "mrr", "ndcg")
            }
            if answerable
            else {}
        )
    return {
        "dataset_snapshot": snapshot,
        "review_status": benchmark.review_status,
        "mode": "lexical_retrieval_only",
        "rows": rows,
        "means": means,
        "note": (
            "Unanswerable lexical hits are not a generated-answer judgment. "
            "Human review remains pending."
        ),
    }


def run_metadata(benchmark: ChatBenchmark, config: ChatConfig, snapshot: str) -> dict:
    from kbfromyt.chat.agent import CHECK_INSTRUCTIONS, INSTRUCTIONS
    from kbfromyt.processing import PROCESSING_VERSION
    from kbfromyt.semantic import INDEX_VERSION

    try:
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], text=True).strip())
    except (OSError, subprocess.CalledProcessError):
        revision, dirty = "unavailable", None
    return {
        "git_revision": revision,
        "worktree_dirty": dirty,
        "benchmark_version": benchmark.version,
        "benchmark_hash": hashlib.sha256(benchmark.model_dump_json().encode()).hexdigest(),
        "case_ids": [c.id for c in benchmark.cases],
        "source_snapshot": snapshot,
        "processing_version": PROCESSING_VERSION,
        "index_version": INDEX_VERSION,
        "embedding_model": config.embedding_model,
        "provider_model": config.model,
        "prompt_hash": hashlib.sha256((INSTRUCTIONS + CHECK_INSTRUCTIONS).encode()).hexdigest(),
        "budgets": {
            key: getattr(config, key)
            for key in ("input_budget", "evidence_budget", "max_requests", "max_tool_calls")
        },
    }


def answer_summary(runs: list[dict]) -> dict:
    answers = [r["answer"] for r in runs if r.get("answer")]
    replies = [
        part
        for r in runs
        for part in [*r.get("setup_turns", []), *([r["answer"]] if r.get("answer") else [])]
    ]
    latency = sorted(a["usage"]["latency_ms"] for a in answers)
    return {
        "completed": len(answers),
        "matching_statuses": sum(bool(r.get("status_matches")) for r in runs),
        "invalid_citation_provenance": sum(
            r.get("citation_provenance_valid") is False for r in runs
        ),
        "provider_requests": sum(p["usage"]["provider_requests"] for p in replies),
        "input_tokens": sum(p["usage"]["input_tokens"] for p in replies)
        if all(p["usage"]["input_tokens"] is not None for p in replies)
        else None,
        "output_tokens": sum(p["usage"]["output_tokens"] for p in replies)
        if all(p["usage"]["output_tokens"] is not None for p in replies)
        else None,
        "median_latency_ms": statistics.median(latency) if latency else None,
        "p95_latency_ms": latency[math.ceil(0.95 * len(latency)) - 1] if latency else None,
        "human_review_complete": False,
        "unsupported_answer_rate": None,
        "note": "Status agreement is not human-rated answer correctness.",
    }


async def live_report(
    benchmark: ChatBenchmark, config: ChatConfig, output: Path, compare: bool = False
) -> dict:
    if not config.has_key:
        raise ValueError("Configure OPENAI_API_KEY in the ignored root .env before --live.")
    await asyncio.to_thread(configure_tokenizer, config.model)
    corpus = await asyncio.to_thread(Corpus, config)
    provider = OpenAIProvider(config)
    result = {
        "metadata": run_metadata(benchmark, config, corpus.snapshot),
        "model": config.model,
        "endpoint_type": "Responses API",
        "dataset_snapshot": corpus.snapshot,
        "review_status": benchmark.review_status,
        "mode": "live_model",
        "runs": [],
    }
    try:
        for mode in ["single_pass", "agentic"] if compare else ["agentic"]:
            settings = (
                config.model_copy(update={"max_requests": 3}) if mode == "single_pass" else config
            )
            service = ChatService(settings, provider, corpus)
            for case in benchmark.cases:
                print(f"{mode}: {case.id}", flush=True)
                session = None
                setup_replies = []
                for question in [
                    *case.setup_turns,
                    *([case.setup_question] if case.setup_question else []),
                ]:
                    session, setup = await service.chat(
                        session,
                        ChatRequest(message=question, request_id=uuid4().hex, scope=case.scope),
                    )
                    setup_replies.append(setup.model_dump())
                    if setup.status == "error":
                        result["runs"].append(
                            {
                                "mode": mode,
                                "id": case.id,
                                "setup_error": setup.model_dump(),
                                "setup_turns": setup_replies,
                            }
                        )
                        break
                if setup_replies and setup_replies[-1]["status"] == "error":
                    output.write_text(
                        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
                    )
                    break
                _, reply = await service.chat(
                    session,
                    ChatRequest(message=case.question, request_id=uuid4().hex, scope=case.scope),
                )
                used = reply.citations
                citation_correct = all(
                    c.video_id in corpus.videos
                    and any(
                        chunk.id == c.chunk_id and chunk.text == c.excerpt
                        for chunk in corpus.videos[c.video_id].chunks
                    )
                    for c in used
                )
                result["runs"].append(
                    {
                        "mode": mode,
                        "id": case.id,
                        "expected_status": case.expected_status,
                        "status_matches": reply.status == case.expected_status,
                        "citation_provenance_valid": citation_correct,
                        "human_entailment_review": "pending",
                        "setup_turns": setup_replies,
                        "answer": reply.model_dump(),
                    }
                )
                output.write_text(
                    json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                # Do not spend the whole benchmark on a bad model/credential configuration.
                if reply.status == "error":
                    break
        result["summary"] = answer_summary(result["runs"])
        return result
    finally:
        await provider.close()
        await asyncio.to_thread(corpus.close)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "file", type=Path, nargs="?", default=Path("examples/chat-playlist-benchmark.json")
    )
    parser.add_argument("--output", type=Path, default=Path("data/live/chat-evaluation.json"))
    parser.add_argument(
        "--live",
        action="store_true",
        help="make real, billable requests to the configured endpoint",
    )
    parser.add_argument(
        "--compare", action="store_true", help="run single-pass and bounded-agent variants"
    )
    parser.add_argument(
        "--server", help="use the running loopback chat server; keeps the UI available"
    )
    parser.add_argument("--cases", nargs="+", help="run only these benchmark case IDs")
    parser.add_argument("--split", choices=["development", "heldout"], default="development")
    args = parser.parse_args(argv)
    benchmark = ChatBenchmark.model_validate_json(args.file.read_text(encoding="utf-8"))
    benchmark.cases = [case for case in benchmark.cases if case.split == args.split]
    if args.cases:
        unknown = set(args.cases) - {case.id for case in benchmark.cases}
        if unknown:
            raise ValueError(f"unknown benchmark case IDs: {sorted(unknown)}")
        benchmark.cases = [case for case in benchmark.cases if case.id in args.cases]
    if not benchmark.cases:
        raise ValueError("benchmark is empty")
    config = ChatConfig.from_env()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result = (
        asyncio.run(server_report(benchmark, config, args.output, args.server, args.compare))
        if args.live and args.server
        else asyncio.run(live_report(benchmark, config, args.output, args.compare))
        if args.live
        else retrieval_report(benchmark, config)
    )
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result.get("summary", result.get("means")), indent=2))
    return 0


async def server_report(
    benchmark: ChatBenchmark, config: ChatConfig, output: Path, server: str, compare: bool
) -> dict:
    import httpx

    url = urlparse(server)
    if url.scheme != "http" or url.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("evaluation server must be a loopback HTTP URL")
    with Store(config.db) as store:
        videos = {p.video.video_id: p for p in store.videos()}
        snapshot = store.snapshot_hash()
    async with httpx.AsyncClient(base_url=server, timeout=75, trust_env=False) as client:
        status = (await client.get("/api/status")).json()
        if not status["ready"] or "TEST FIXTURE" in (status.get("message") or ""):
            raise ValueError("live server is not ready or is a test fixture")
        result = {
            "metadata": run_metadata(benchmark, config, snapshot),
            "model": status["model"],
            "endpoint_type": "standard OpenAI via local server",
            "dataset_snapshot": snapshot,
            "review_status": benchmark.review_status,
            "mode": "live_model",
            "runs": [],
        }
        for mode in ["single_pass", "agentic"] if compare else ["agentic"]:
            for case in benchmark.cases:
                print(f"{mode}: {case.id}", flush=True)
                client.cookies.clear()
                initialized = await client.get("/api/conversations")
                initialized.raise_for_status()
                setup = None
                setup_replies = []
                for question in [
                    *case.setup_turns,
                    *([case.setup_question] if case.setup_question else []),
                ]:
                    response = await client.post(
                        "/api/chat",
                        json={
                            "message": question,
                            "scope": case.scope.model_dump(),
                            "request_id": uuid4().hex,
                            "agentic": mode == "agentic",
                        },
                    )
                    response.raise_for_status()
                    setup = AnswerEnvelope.model_validate(response.json())
                    setup_replies.append(setup.model_dump())
                    if setup.status == "error":
                        break
                if setup and setup.status == "error":
                    result["runs"].append(
                        {"mode": mode, "id": case.id, "setup_turns": setup_replies}
                    )
                    output.write_text(
                        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
                    )
                    break
                response = await client.post(
                    "/api/chat",
                    json={
                        "message": case.question,
                        "scope": case.scope.model_dump(),
                        "request_id": uuid4().hex,
                        "agentic": mode == "agentic",
                    },
                )
                response.raise_for_status()
                reply = AnswerEnvelope.model_validate(response.json())
                correct = all(
                    c.video_id in videos
                    and any(
                        chunk.id == c.chunk_id and chunk.text == c.excerpt
                        for chunk in videos[c.video_id].chunks
                    )
                    for c in reply.citations
                )
                result["runs"].append(
                    {
                        "mode": mode,
                        "id": case.id,
                        "expected_status": case.expected_status,
                        "status_matches": reply.status == case.expected_status,
                        "citation_provenance_valid": correct,
                        "human_entailment_review": "pending",
                        "setup": setup.model_dump() if setup else None,
                        "setup_turns": setup_replies,
                        "answer": reply.model_dump(),
                    }
                )
                output.write_text(
                    json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                if reply.status == "error":
                    break
        result["summary"] = answer_summary(result["runs"])
        return result


if __name__ == "__main__":
    raise SystemExit(main())
