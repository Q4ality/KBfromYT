from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

from kbfromyt.store import Store

DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"
INDEX_VERSION = "token-windows-v2"
IndexProgress = Callable[[str, int, int], None]


@dataclass(frozen=True)
class TextWindow:
    start: int
    end: int
    text: str
    tokens: int


def token_windows(text: str, tokenizer, limit: int, overlap: int | None = None) -> list[TextWindow]:
    """Exact original substrings; every window is rechecked against the real tokenizer."""
    offsets = tokenizer.encode(text, add_special_tokens=False).offsets
    if not offsets:
        return []
    special = len(tokenizer.encode("").ids)
    capacity = limit - special - 2  # Boundary re-tokenization can add a token.
    if capacity < 4:
        raise ValueError("embedding token window is too small")
    overlap = min(overlap if overlap is not None else capacity // 4, capacity // 2)
    windows, first = [], 0
    while first < len(offsets):
        stop = min(first + capacity, len(offsets))
        start = 0 if first == 0 else offsets[first][0]
        while stop > first:
            end = len(text) if stop == len(offsets) else offsets[stop - 1][1]
            part = text[start:end]
            size = len(tokenizer.encode(part).ids)
            if part.strip() and size <= limit:
                break
            stop -= 1
        if stop <= first:
            raise ValueError("a source span cannot fit the embedding tokenizer")
        windows.append(TextWindow(start, end, part, size))
        if stop == len(offsets):
            break
        first = max(first + 1, stop - overlap)
    return windows


class Embedder(Protocol):
    name: str

    def embed(self, texts: list[str], *, query: bool = False) -> list[list[float]]: ...


class FastEmbedder:
    def __init__(self, name: str = DEFAULT_MODEL):
        try:
            from fastembed import TextEmbedding
        except ImportError as exc:
            raise RuntimeError("install kbfromyt[semantic] to use semantic search") from exc
        self.name = name
        self.model = TextEmbedding(model_name=name)
        from tokenizers import Tokenizer

        backend = self.model.model
        backend._ensure_tokenizer()
        source = backend.tokenizer
        self.token_limit = source.truncation["max_length"]
        self.tokenizer = Tokenizer.from_str(source.to_str())
        self.tokenizer.no_truncation()
        self.tokenizer.no_padding()

    def windows(self, text: str) -> list[TextWindow]:
        return token_windows(text, self.tokenizer, self.token_limit)

    def embed(self, texts: list[str], *, query: bool = False) -> list[list[float]]:
        method = self.model.query_embed if query else self.model.passage_embed
        return [v.tolist() for v in method(texts)]


class SemanticIndex:
    def __init__(self, path: Path, embedder: Embedder):
        try:
            from qdrant_client import QdrantClient
        except ImportError as exc:
            raise RuntimeError("install kbfromyt[semantic] to use Qdrant") from exc
        path.mkdir(parents=True, exist_ok=True)
        self.client = QdrantClient(path=str(path / "qdrant"))
        self.manifest = path / "complete.json"
        self.embedder = embedder
        self._query_vectors: dict[str, list[float]] = {}

    def close(self) -> None:
        self.client.close()

    def rebuild(
        self, store: Store, *, progress: IndexProgress | None = None, skip_current: bool = False
    ) -> int:
        from qdrant_client import models

        def report(stage: str, done: int, total: int) -> None:
            if progress:
                progress(stage, done, total)

        store.refresh_overviews()
        docs = store.documents()
        if not docs:
            raise ValueError("import at least one video before indexing")
        report("preparing", 0, len(docs))
        windows = []
        for number, doc in enumerate(docs, 1):
            parts = (
                self.embedder.windows(doc.text)
                if hasattr(self.embedder, "windows")
                else [TextWindow(0, len(doc.text), doc.text, 0)]
            )
            windows.extend((doc, window) for window in parts)
            if number % 32 == 0 or number == len(docs):
                report("preparing", number, len(docs))
        expected_ids = {str(uuid5(NAMESPACE_URL, f"{d.id}:{w.start}:{w.end}")) for d, w in windows}
        if skip_current and self.reuse_current(store, expected_ids, report):
            report("current", len(windows), len(windows))
            return len(docs)
        self.manifest.unlink(missing_ok=True)
        self._query_vectors.clear()
        created = False
        report("embedding", 0, len(windows))
        for first in range(0, len(windows), 128):
            batch = windows[first : first + 128]
            vectors = self.embedder.embed([w.text for _, w in batch])
            if len(vectors) != len(batch) or not vectors or not vectors[0]:
                raise ValueError("embedding provider returned incomplete vectors")
            if not created:
                if self.client.collection_exists("documents"):
                    # Windows may retain the directory despite delete_collection.
                    # Clear through the public API so stale points cannot reappear.
                    self.client.delete(
                        "documents", models.FilterSelector(filter=models.Filter()), wait=True
                    )
                    self.client.delete_collection("documents")
                self.client.create_collection(
                    "documents",
                    vectors_config=models.VectorParams(
                        size=len(vectors[0]), distance=models.Distance.COSINE
                    ),
                )
                created = True
            points = [
                models.PointStruct(
                    id=str(uuid5(NAMESPACE_URL, f"{d.id}:{w.start}:{w.end}")),
                    vector=v,
                    payload={
                        "id": d.id,
                        "level": d.level,
                        "start_char": w.start,
                        "end_char": w.end,
                        "tokens": w.tokens,
                    },
                )
                for (d, w), v in zip(batch, vectors, strict=True)
            ]
            self.client.upsert("documents", points=points, wait=True)
            report("embedding", min(first + len(batch), len(windows)), len(windows))
        if self.client.count("documents", exact=True).count != len(expected_ids):
            raise ValueError("semantic index point count does not match completed windows")
        self.manifest.write_text(
            json.dumps(
                {
                    "snapshot": store.snapshot_hash(),
                    "model": self.embedder.name,
                    "index_version": INDEX_VERSION,
                    "count": len(windows),
                    "documents": len(docs),
                    "token_limit": getattr(self.embedder, "token_limit", None),
                    "max_window_tokens": max(w.tokens for _, w in windows),
                }
            ),
            encoding="utf-8",
        )
        return len(docs)

    def reuse_current(self, store: Store, expected_ids: set[str], report: IndexProgress) -> bool:
        try:
            metadata = json.loads(self.manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        if (
            metadata.get("snapshot") != store.snapshot_hash()
            or metadata.get("model") != self.embedder.name
            or metadata.get("index_version") != INDEX_VERSION
            or metadata.get("count") != len(expected_ids)
            or not self.client.collection_exists("documents")
        ):
            return False
        actual: set[str] = set()
        offset = None
        report("checking", 0, len(expected_ids))
        while True:
            points, offset = self.client.scroll(
                "documents", limit=256, offset=offset, with_payload=False, with_vectors=False
            )
            actual.update(str(p.id) for p in points)
            report("checking", len(actual & expected_ids), len(expected_ids))
            if offset is None:
                break
        if not expected_ids.issubset(actual):
            return False
        extra = list(actual - expected_ids)
        if extra:
            from qdrant_client import models

            # An older collection recreation could leave obsolete IDs on disk.
            # Preserve all expected vectors; remove only positively identified extras.
            self.manifest.unlink(missing_ok=True)
            report("pruning", 0, len(extra))
            for first in range(0, len(extra), 256):
                batch = extra[first : first + 256]
                self.client.delete("documents", models.PointIdsList(points=batch), wait=True)
                report("pruning", first + len(batch), len(extra))
            if self.client.count("documents", exact=True).count != len(expected_ids):
                raise ValueError("semantic index cleanup did not finish")
            self.manifest.write_text(json.dumps(metadata), encoding="utf-8")
        return True

    def search(
        self,
        store: Store,
        query: str,
        limit: int = 20,
        threshold: float = 0.45,
        document_ids: list[str] | None = None,
    ) -> list[list[str]]:
        from qdrant_client import models

        if not self.manifest.exists():
            raise ValueError("semantic index is missing/incomplete; run yt-kb index")
        metadata = json.loads(self.manifest.read_text(encoding="utf-8"))
        if metadata.get("index_version") != INDEX_VERSION:
            raise ValueError("semantic index format is stale; run yt-kb index")
        if metadata["snapshot"] != store.snapshot_hash() or metadata["model"] != self.embedder.name:
            raise ValueError("semantic index is stale or model changed; run yt-kb index")
        if query not in self._query_vectors:
            if len(self._query_vectors) >= 32:
                self._query_vectors.pop(next(iter(self._query_vectors)))
            self._query_vectors[query] = self.embedder.embed([query], query=True)[0]
        vector = self._query_vectors[query]
        lists = []
        for level in ("video", "chapter", "chunk"):
            conditions = [models.FieldCondition(key="level", match=models.MatchValue(value=level))]
            if document_ids is not None:
                if not document_ids:
                    lists.append([])
                    continue
                conditions.append(
                    models.FieldCondition(key="id", match=models.MatchAny(any=document_ids))
                )
            groups = self.client.query_points_groups(
                "documents",
                query=vector,
                query_filter=models.Filter(must=conditions),
                limit=limit,
                group_by="id",
                group_size=1,
                score_threshold=threshold,
            ).groups
            lists.append([group.hits[0].payload["id"] for group in groups])
        return lists
