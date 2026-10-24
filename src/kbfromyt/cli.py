from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from kbfromyt.answering import answer
from kbfromyt.evaluation import Case, evaluate
from kbfromyt.ingest import enumerate_videos, fetch_video, transcribe, video_id
from kbfromyt.models import VideoInput
from kbfromyt.retrieval import search
from kbfromyt.semantic import DEFAULT_MODEL, FastEmbedder, SemanticIndex
from kbfromyt.store import Store


def positive(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be positive")
    return number


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Local YouTube transcript knowledge base")
    root.add_argument("--db", type=Path, default=Path("data/kb.sqlite3"))
    root.add_argument("--index-dir", type=Path, default=Path("data/semantic"))
    root.add_argument("--embedding-model", default=DEFAULT_MODEL)
    commands = root.add_subparsers(dest="command", required=True)
    local = commands.add_parser("import", help="import one VideoInput JSON object")
    local.add_argument("file", type=Path)
    ingest = commands.add_parser("ingest", help="ingest a YouTube video/playlist/channel")
    ingest.add_argument("url")
    ingest.add_argument("--collection", action="store_true", help="URL is playlist/channel")
    ingest.add_argument("--limit", type=positive, default=20)
    ingest.add_argument("--languages", nargs="+", default=["en", "ru"])
    ingest.add_argument("--whisper", action="store_true")
    ingest.add_argument("--whisper-model", default="base")
    audio = commands.add_parser("transcribe", help="import local audio with Whisper")
    audio.add_argument("file", type=Path)
    audio.add_argument("--video-id", required=True)
    audio.add_argument("--title", required=True)
    audio.add_argument("--model", default="base")
    for name in ("search", "ask"):
        item = commands.add_parser(name)
        item.add_argument("query")
        item.add_argument("--k", type=positive, default=5)
        item.add_argument("--semantic", action="store_true")
        if name == "ask":
            item.add_argument("--model", help="optional local Ollama model")
    commands.add_parser("index", help="rebuild local dense index; downloads model on first run")
    commands.add_parser("stats")
    chat = commands.add_parser("chat", help="start the local RAG browser chat")
    chat.add_argument("--host", choices=["127.0.0.1", "localhost", "::1"])
    chat.add_argument("--port", type=positive)
    chat.add_argument(
        "--lexical-only", action="store_true", help="explicitly run without a vector index"
    )
    benchmark = commands.add_parser("evaluate")
    benchmark.add_argument("file", type=Path)
    benchmark.add_argument("--k", type=positive, default=5)
    benchmark.add_argument("--semantic", action="store_true")
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    semantic = None
    try:
        if args.command == "chat":
            import os

            import uvicorn

            from kbfromyt.chat.config import ChatConfig
            from kbfromyt.web.app import create_app

            config = ChatConfig.from_env()
            if args.lexical_only:
                config.semantic = False
            host, port = (
                args.host or os.getenv("CHAT_HOST", "127.0.0.1"),
                args.port or int(os.getenv("CHAT_PORT", "8000")),
            )
            if host not in {"127.0.0.1", "localhost", "::1"} or not 1 <= port <= 65535:
                raise ValueError("chat must bind to a loopback address and valid port")
            uvicorn.run(create_app(config), host=host, port=port, workers=1)
            return 0
        with Store(args.db) as store:
            if args.command == "index" or getattr(args, "semantic", False):
                semantic = SemanticIndex(args.index_dir, FastEmbedder(args.embedding_model))
            if args.command == "import":
                video = VideoInput.model_validate_json(args.file.read_text(encoding="utf-8"))
                output = {"video_id": video.video_id, "changed": store.import_video(video)}
            elif args.command == "ingest":
                ids = (
                    enumerate_videos(args.url, args.limit)
                    if args.collection
                    else [video_id(args.url)]
                )
                if not ids:
                    raise ValueError("no videos found in collection")
                rows = []
                for vid in ids:
                    try:
                        video = fetch_video(vid, args.languages, args.whisper, args.whisper_model)
                        rows.append({"video_id": vid, "changed": store.import_video(video)})
                    except Exception as exc:
                        rows.append({"video_id": vid, "error": str(exc)})
                output = {"results": rows}
                emit(output)
                return int(any("error" in r for r in rows))
            elif args.command == "transcribe":
                segments = transcribe(args.file, args.model)
                if not segments:
                    raise ValueError("audio contains no recognized speech")
                video = VideoInput(
                    video_id=video_id(args.video_id),
                    title=args.title,
                    language="und",
                    duration=max(s.end for s in segments),
                    transcript_source="whisper",
                    segments=segments,
                )
                output = {"changed": store.import_video(video)}
            elif args.command in {"search", "ask"}:
                evidence = search(store, args.query, args.k, semantic)
                output = (
                    answer(args.query, evidence, args.model)
                    if args.command == "ask"
                    else {"query": args.query, "evidence": [e.as_dict() for e in evidence]}
                )
            elif args.command == "index":
                output = {"indexed": semantic.rebuild(store)}
            elif args.command == "evaluate":
                cases = [
                    Case.model_validate(c)
                    for c in json.loads(args.file.read_text(encoding="utf-8"))
                ]
                output = evaluate(store, cases, args.k, semantic)
            else:
                output = store.stats()
            emit(output)
        return 0
    except Exception as exc:
        print(f"yt-kb: {exc}", file=sys.stderr)
        return 1
    finally:
        if semantic:
            semantic.close()


def emit(value: dict) -> None:
    print(json.dumps(value, ensure_ascii=True, indent=2))
