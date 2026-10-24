from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

from kbfromyt.store import Store

DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"


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

    def close(self) -> None:
        self.client.close()

    def rebuild(self, store: Store) -> int:
        from qdrant_client import models

        self.manifest.unlink(missing_ok=True)
        docs = store.documents()
        if not docs:
            raise ValueError("import at least one video before indexing")
        vectors = self.embedder.embed([d.text for d in docs])
        if len(vectors) != len(docs) or not vectors[0]:
            raise ValueError("embedding provider returned incomplete vectors")
        if self.client.collection_exists("documents"):
            self.client.delete_collection("documents")
        self.client.create_collection(
            "documents",
            vectors_config=models.VectorParams(
                size=len(vectors[0]), distance=models.Distance.COSINE
            ),
        )
        points = [
            models.PointStruct(
                id=str(uuid5(NAMESPACE_URL, d.id)), vector=v, payload={"id": d.id, "level": d.level}
            )
            for d, v in zip(docs, vectors, strict=True)
        ]
        self.client.upsert("documents", points=points, wait=True)
        self.manifest.write_text(
            json.dumps(
                {"snapshot": store.snapshot_hash(), "model": self.embedder.name, "count": len(docs)}
            ),
            encoding="utf-8",
        )
        return len(docs)

    def search(
        self, store: Store, query: str, limit: int = 20, threshold: float = 0.45
    ) -> list[list[str]]:
        from qdrant_client import models

        if not self.manifest.exists():
            raise ValueError("semantic index is missing/incomplete; run yt-kb index")
        metadata = json.loads(self.manifest.read_text(encoding="utf-8"))
        if metadata["snapshot"] != store.snapshot_hash() or metadata["model"] != self.embedder.name:
            raise ValueError("semantic index is stale or model changed; run yt-kb index")
        vector = self.embedder.embed([query], query=True)[0]
        lists = []
        for level in ("video", "chapter", "chunk"):
            points = self.client.query_points(
                "documents",
                query=vector,
                query_filter=models.Filter(
                    must=[models.FieldCondition(key="level", match=models.MatchValue(value=level))]
                ),
                limit=limit,
                score_threshold=threshold,
            ).points
            lists.append([p.payload["id"] for p in points])
        return lists
