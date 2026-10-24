from __future__ import annotations

import json
import threading
from dataclasses import dataclass

from kbfromyt.chat.config import ChatConfig
from kbfromyt.chat.contracts import ContextArgs, RetrievalStep, SearchArgs
from kbfromyt.chat.memory import budget_size
from kbfromyt.models import Evidence, ProcessedVideo
from kbfromyt.overviews import content_terms
from kbfromyt.retrieval import broad_search, search
from kbfromyt.semantic import INDEX_VERSION, FastEmbedder, SemanticIndex
from kbfromyt.store import Store


def tool_schemas() -> list[dict]:
    return [
        {
            "type": "function",
            "name": name,
            "description": description,
            "strict": True,
            "parameters": schema.model_json_schema(),
        }
        for name, description, schema in (
            (
                "search_transcripts",
                "Search indexed video transcripts for fresh evidence. "
                "Use a standalone query, in Russian for the current corpus where appropriate. "
                "Use video_ids_or_null to focus a follow-up on a previously cited video.",
                SearchArgs,
            ),
            (
                "search_overviews",
                "Search broad questions about authors' positions, competing versions or a series. "
                "Uses source-linked video overviews, multiple query facets and diverse videos. "
                "Returned transcript passages are evidence; overview metadata is navigation only.",
                SearchArgs,
            ),
            (
                "get_context",
                "Get up to one neighboring chunk on each side of a source "
                "returned in this request. Use only current source handles.",
                ContextArgs,
            ),
        )
    ]


@dataclass
class Source:
    evidence: Evidence
    language: str
    origin: str


class ToolBudget(Exception):
    pass


class Corpus:
    """One model/vector client per process; SQLite connections stay in calling threads."""

    def __init__(self, config: ChatConfig):
        self.config = config
        self.semantic: SemanticIndex | None = None
        self.lock = threading.RLock()
        self.videos: dict[str, ProcessedVideo] = {}
        if not config.db.is_file():
            raise ValueError(
                "Source database is missing. Ingest the playlist before starting chat."
            )
        with Store(config.db) as store:
            self.snapshot = store.snapshot_hash()
            self.videos = {p.video.video_id: p for p in store.videos()}
        if not self.videos:
            raise ValueError("Source database is empty. Ingest a video before starting chat.")
        if config.semantic:
            marker = config.index_dir / "complete.json"
            if not marker.is_file():
                raise ValueError("Semantic index is missing. Stop chat and build the index.")
            metadata = json.loads(marker.read_text(encoding="utf-8"))
            if metadata.get("index_version") != INDEX_VERSION:
                raise ValueError("Semantic index format changed. Use Clean and rebuild.")
            if metadata["snapshot"] != self.snapshot or metadata["model"] != config.embedding_model:
                raise ValueError("Semantic index is stale or model differs. Stop chat and reindex.")
            self.semantic = SemanticIndex(config.index_dir, FastEmbedder(config.embedding_model))

    def current(self, store: Store) -> None:
        if store.snapshot_hash() != self.snapshot:
            raise ValueError("Source database changed. Stop chat, reindex and restart.")

    def rebuild(self) -> int:
        with self.lock, Store(self.config.db) as store:
            store.refresh_overviews()
            count = self.semantic.rebuild(store) if self.semantic else 0
            self.videos = {p.video.video_id: p for p in store.videos()}
            self.snapshot = store.snapshot_hash()
            return count

    def search(
        self, args: SearchArgs, broad: bool = False, trace: list[dict] | None = None
    ) -> list[Source]:
        if args.video_ids_or_null is not None and any(
            vid not in self.videos for vid in args.video_ids_or_null
        ):
            raise ValueError("unknown source video filter")
        with self.lock, Store(self.config.db) as store:
            self.current(store)
            if broad:
                hits, steps = broad_search(
                    store, args.query, args.k, self.semantic, args.video_ids_or_null
                )
                if trace is not None:
                    trace.extend(steps)
                return [self.source(e) for e in hits]
            hits = search(
                store,
                args.query,
                args.k,
                self.semantic,
                parent_child_limit=3,
                video_ids=args.video_ids_or_null,
            )
            return [self.source(e) for e in hits]

    def catalogue(self, query: str, video_ids: list[str] | None = None) -> list[dict]:
        with self.lock, Store(self.config.db) as store:
            self.current(store)
            summaries = [
                s for s in store.overviews() if video_ids is None or s.video_id in video_ids
            ]
        terms = content_terms(query)
        summaries.sort(
            key=lambda s: (
                -len(
                    terms
                    & content_terms(
                        " ".join([s.title, *s.topics, *(p.excerpt for p in s.passages)])
                    )
                ),
                s.video_id,
            )
        )
        return [
            {
                "video_id": s.video_id,
                "title": s.title,
                "topics": s.topics[:8],
                "method": s.method,
                "source_chunk_ids": [p.chunk_id for p in s.passages],
            }
            for s in summaries[:8]
        ]

    def source(self, evidence: Evidence) -> Source:
        video = self.videos[evidence.video_id].video
        return Source(evidence, video.language, video.transcript_source)

    def context(self, source: Source, neighbors: int) -> list[Source]:
        with self.lock, Store(self.config.db) as store:
            self.current(store)
            p = self.videos[source.evidence.video_id]
            siblings = [c for c in p.chunks if c.chapter_id == source.evidence.chapter_id]
            position = next(i for i, c in enumerate(siblings) if c.id == source.evidence.id)
            return [
                self.source(
                    Evidence(
                        **c.model_dump(),
                        video_title=p.video.title,
                        chapter_title=source.evidence.chapter_title,
                        score=0,
                    )
                )
                for c in siblings[max(0, position - neighbors) : position + neighbors + 1]
            ]

    def close(self) -> None:
        with self.lock:
            if self.semantic:
                self.semantic.close()


class EvidenceRegistry:
    def __init__(self, config: ChatConfig, corpus: Corpus, broad: bool = False):
        self.config, self.corpus = config, corpus
        self.sources: dict[str, Source] = {}
        self.used_bytes = 0
        self.omitted = 0
        self.searches = self.expansions = self.executions = 0
        self.broad = broad
        self.trace: list[RetrievalStep] = []

    def register(self, sources: list[Source]) -> list[dict]:
        output = []
        for source in sources:
            existing = next(
                (key for key, s in self.sources.items() if s.evidence.id == source.evidence.id),
                None,
            )
            if existing:
                # Already delivered evidence need not be repeated in later tool messages.
                output.append({"source_id": existing, "already_returned": True})
                continue
            if len(self.sources) >= self.config.max_passages:
                break
            key = f"S{len(self.sources) + 1}"
            e = source.evidence
            item = {
                "source_id": key,
                "video_id": e.video_id,
                "title": e.video_title,
                "chapter": e.chapter_title,
                "start": e.start,
                "end": e.end,
                "text": e.text,
                "language": source.language,
                "caption_source": source.origin,
            }
            size = budget_size(item)
            if self.used_bytes + size > self.config.evidence_budget:
                self.omitted += 1
                continue
            self.sources[key] = source
            self.used_bytes += size
            output.append(item)
        return output

    def execute(self, name: str, arguments: str) -> dict:
        if self.executions >= self.config.max_tool_calls:
            raise ToolBudget("tool budget exhausted")
        self.executions += 1
        if name in {"search_transcripts", "search_overviews"}:
            if self.searches >= 2:
                raise ToolBudget("search budget exhausted")
            self.searches += 1
            args = SearchArgs.model_validate_json(arguments)
            broad = self.broad or name == "search_overviews"
            catalogue, steps = [], []
            if broad:
                for card in self.corpus.catalogue(args.query, args.video_ids_or_null):
                    size = budget_size(card)
                    if (
                        budget_size(catalogue) + size > 1200
                        or self.used_bytes + size > self.config.evidence_budget
                    ):
                        break
                    catalogue.append(card)
                    self.used_bytes += size
            sources = self.corpus.search(args, broad=broad, trace=steps)
            returned = self.register(sources)
            for step in steps or [
                {"query": args.query, "chunk_ids": [s.evidence.id for s in sources]}
            ]:
                self.trace.append(
                    RetrievalStep(
                        tool=name,
                        query=step["query"],
                        chunk_ids=step["chunk_ids"],
                        returned_chunk_ids=[
                            self.sources[item["source_id"]].evidence.id for item in returned
                        ],
                        returned_video_ids=list(
                            dict.fromkeys(
                                self.sources[item["source_id"]].evidence.video_id
                                for item in returned
                            )
                        ),
                    )
                )
            return {
                "sources": returned,
                "video_overviews": catalogue,
                "coverage": {
                    "library_videos": len(self.corpus.videos),
                    "evidence_videos": len({s.evidence.video_id for s in self.sources.values()}),
                    "navigation_only": True,
                },
            }
        if name == "get_context":
            if self.expansions >= 1:
                raise ToolBudget("context expansion budget exhausted")
            self.expansions += 1
            args = ContextArgs.model_validate_json(arguments)
            if args.source_handle not in self.sources:
                raise ValueError("unknown or stale source handle")
            sources = self.corpus.context(self.sources[args.source_handle], args.neighbor_count)
            result = self.register(sources)
            self.trace.append(
                RetrievalStep(
                    tool=name,
                    chunk_ids=[s.evidence.id for s in sources],
                    returned_chunk_ids=[
                        self.sources[item["source_id"]].evidence.id for item in result
                    ],
                    returned_video_ids=list(
                        dict.fromkeys(
                            self.sources[item["source_id"]].evidence.video_id for item in result
                        )
                    ),
                )
            )
            return {"sources": result}
        raise ValueError("unknown tool")
