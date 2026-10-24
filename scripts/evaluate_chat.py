"""Playlist chat evaluation. No model calls unless --live is explicitly supplied.

Stop the local chat server before --live: Qdrant local has one process owner.
Review the resulting claims against source videos; automated scores do not prove entailment.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse
from uuid import uuid4

from kbfromyt.chat.config import ChatConfig
from kbfromyt.chat.contracts import AnswerEnvelope, ChatRequest
from kbfromyt.chat.memory import configure_tokenizer
from kbfromyt.chat.providers.openai import OpenAIProvider
from kbfromyt.chat.service import ChatService
from kbfromyt.chat.tools import Corpus
from kbfromyt.evaluation import Gold, metrics
from kbfromyt.models import Contract
from kbfromyt.retrieval import search
from kbfromyt.store import Store


class ChatCase(Contract):
    id: str
    category: Literal["direct", "paraphrase", "followup", "unanswerable", "partial"]
    question: str
    setup_question: str | None
    expected_status: Literal["grounded", "partial", "no_support"]
    relevant: list[Gold]


class ChatBenchmark(Contract):
    name: str
    playlist_id: str
    review_status: str
    cases: list[ChatCase]


def retrieval_report(benchmark: ChatBenchmark, config: ChatConfig) -> dict:
    """Lexical baseline comparison; no provider or semantic client required."""
    rows = []
    with Store(config.db) as store:
        videos = {p.video.video_id: p for p in store.videos()}
        for case in benchmark.cases:
            for gold in case.relevant:
                if gold.video_id not in videos or gold.end > videos[gold.video_id].video.duration:
                    raise ValueError(f"Gold interval is not in this corpus: {case.id}")
            query = " ".join(filter(None, [case.setup_question, case.question]))
            rows.append(
                {
                    "id": case.id,
                    "category": case.category,
                    "flat_parent_baseline": metrics(search(store, query, 5), case.relevant, 5),
                    "bounded_parents": metrics(
                        search(store, query, 5, parent_child_limit=3), case.relevant, 5
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


async def live_report(
    benchmark: ChatBenchmark, config: ChatConfig, output: Path, compare: bool = False
) -> dict:
    if not config.has_key:
        raise ValueError("Configure OPENAI_API_KEY in the ignored root .env before --live.")
    await asyncio.to_thread(configure_tokenizer, config.model)
    corpus = await asyncio.to_thread(Corpus, config)
    provider = OpenAIProvider(config)
    result = {
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
                if case.setup_question:
                    session, setup = await service.chat(
                        None, ChatRequest(message=case.setup_question, request_id=uuid4().hex)
                    )
                    if setup.status == "error":
                        result["runs"].append(
                            {"mode": mode, "id": case.id, "setup_error": setup.model_dump()}
                        )
                        break
                _, reply = await service.chat(
                    session, ChatRequest(message=case.question, request_id=uuid4().hex)
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
                        "answer": reply.model_dump(),
                    }
                )
                output.write_text(
                    json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                # Do not spend the whole benchmark on a bad model/credential configuration.
                if reply.status == "error":
                    break
        result["summary"] = {
            "completed": len(result["runs"]),
            "matching_statuses": sum(bool(r.get("status_matches")) for r in result["runs"]),
            "invalid_citation_provenance": sum(
                r.get("citation_provenance_valid") is False for r in result["runs"]
            ),
            "provider_requests": sum(
                r.get("answer", {}).get("usage", {}).get("provider_requests", 0)
                for r in result["runs"]
            ),
            "human_review_complete": False,
        }
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
    args = parser.parse_args(argv)
    benchmark = ChatBenchmark.model_validate_json(args.file.read_text(encoding="utf-8"))
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
                setup = None
                if case.setup_question:
                    response = await client.post(
                        "/api/chat",
                        json={
                            "message": case.setup_question,
                            "request_id": uuid4().hex,
                            "agentic": mode == "agentic",
                        },
                    )
                    response.raise_for_status()
                    setup = AnswerEnvelope.model_validate(response.json())
                response = await client.post(
                    "/api/chat",
                    json={
                        "message": case.question,
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
                        "answer": reply.model_dump(),
                    }
                )
                output.write_text(
                    json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                if reply.status == "error":
                    break
        result["summary"] = {
            "completed": len(result["runs"]),
            "matching_statuses": sum(r["status_matches"] for r in result["runs"]),
            "invalid_citation_provenance": sum(
                not r["citation_provenance_valid"] for r in result["runs"]
            ),
            "provider_requests": sum(
                (r.get(part) or {}).get("usage", {}).get("provider_requests", 0)
                for r in result["runs"]
                for part in ("setup", "answer")
            ),
            "human_review_complete": False,
        }
        return result


if __name__ == "__main__":
    raise SystemExit(main())
