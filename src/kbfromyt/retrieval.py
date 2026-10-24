from __future__ import annotations

from collections import defaultdict

from kbfromyt.models import Evidence
from kbfromyt.processing import tokens
from kbfromyt.semantic import SemanticIndex
from kbfromyt.store import Store


def search(
    store: Store,
    query: str,
    k: int = 5,
    semantic: SemanticIndex | None = None,
    *,
    parent_child_limit: int | None = None,
    video_ids: list[str] | None = None,
) -> list[Evidence]:
    if k < 1:
        raise ValueError("k must be positive")
    if not tokens(query):
        return []
    rankings = [
        store.lexical(query, level, max(20, k * 4), video_ids)
        for level in ("video", "chapter", "chunk")
    ]
    documents = {d.id: d for d in store.documents()}
    if semantic:
        allowed = (
            [d.id for d in documents.values() if d.video_id in video_ids]
            if video_ids is not None
            else None
        )
        rankings.extend(semantic.search(store, query, max(20, k * 4), document_ids=allowed))
    videos = store.videos()
    chunks = {
        c.id: c for p in videos for c in p.chunks if video_ids is None or c.video_id in video_ids
    }
    parents = {c.id: c for p in videos for c in p.chapters}
    titles = {p.video.video_id: p.video.title for p in videos}
    scores: dict[str, float] = defaultdict(float)
    direct_ranks = {}
    for ranking in rankings:
        for rank, cid in enumerate(ranking, 1):
            if cid in chunks:
                direct_ranks[cid] = min(rank, direct_ranks.get(cid, rank))
    for ranking in rankings:
        credited = set()
        for rank, doc_id in enumerate(ranking, 1):
            doc = documents.get(doc_id)
            if doc is None or (video_ids is not None and doc.video_id not in video_ids):
                continue
            candidates = (
                [chunks[doc_id]]
                if doc.level == "chunk"
                else [
                    c
                    for c in chunks.values()
                    if c.video_id == doc.video_id
                    and (doc.level == "video" or c.chapter_id == doc.chapter_id)
                ]
            )
            if parent_child_limit is not None and doc.level != "chunk":
                candidates = sorted(
                    candidates,
                    key=lambda c: (
                        direct_ranks.get(c.id, 10000),
                        -len(tokens(query) & tokens(c.text)),
                        c.start,
                    ),
                )[:parent_child_limit]
            for chunk in candidates:
                if chunk.id not in credited:
                    scores[chunk.id] += 1 / (60 + rank)
                    credited.add(chunk.id)
    terms = tokens(query)
    for cid in scores:
        scores[cid] += 0.03 * len(terms & tokens(chunks[cid].text)) / len(terms)
    output = []
    for cid in sorted(scores, key=lambda c: (-scores[c], c))[:k]:
        chunk = chunks[cid]
        siblings = sorted(
            (c for c in chunks.values() if c.chapter_id == chunk.chapter_id),
            key=lambda c: (c.start, c.id),
        )
        position = next(i for i, c in enumerate(siblings) if c.id == cid)
        neighbors = [c.text for c in siblings[max(0, position - 1) : position + 2] if c.id != cid]
        output.append(
            Evidence(
                **chunk.model_dump(),
                video_title=titles[chunk.video_id],
                chapter_title=parents[chunk.chapter_id].title,
                score=scores[cid],
                context=neighbors,
            )
        )
    return output
