from __future__ import annotations

import re
from collections import defaultdict

from kbfromyt.models import Evidence
from kbfromyt.overviews import content_terms
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
    max_per_video: int | None = None,
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
    output, counts = [], defaultdict(int)
    for cid in sorted(scores, key=lambda c: (-scores[c], c)):
        chunk = chunks[cid]
        if max_per_video is not None and counts[chunk.video_id] >= max_per_video:
            continue
        counts[chunk.video_id] += 1
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
        if len(output) == k:
            break
    return output


def broad_search(
    store: Store,
    query: str,
    k: int = 8,
    semantic: SemanticIndex | None = None,
    video_ids: list[str] | None = None,
) -> tuple[list[Evidence], list[dict]]:
    """Generic facets, original source evidence and bounded cross-video coverage."""
    queries = [query, f"выводы позиция автора {query}", f"аргументы доказательства версии {query}"]
    scores, evidence, steps = defaultdict(float), {}, []
    preferred = {
        p.chunk_id
        for overview in store.overviews()
        for p in overview.passages
        if video_ids is None or overview.video_id in video_ids
    }
    videos = store.videos()
    parents = {chapter.id: chapter for video in videos for chapter in video.chapters}
    anchors = {
        chunk.id: Evidence(
            **chunk.model_dump(),
            video_title=video.video.title,
            chapter_title=parents[chunk.chapter_id].title,
            score=0,
        )
        for video in videos
        for chunk in video.chunks
        if chunk.id in preferred
    }
    for facet in queries:
        hits = search(
            store,
            facet,
            max(24, k * 3),
            semantic,
            parent_child_limit=2,
            video_ids=video_ids,
            max_per_video=3,
        )
        steps.append({"query": facet, "chunk_ids": [e.id for e in hits]})
        for rank, hit in enumerate(hits, 1):
            scores[hit.id] += 1 / (40 + rank)
            evidence[hit.id] = hit
        if semantic:
            anchor_ids = semantic.search(store, facet, limit=24, document_ids=sorted(preferred))[2]
        else:
            terms = content_terms(facet)
            anchor_ids = sorted(
                (key for key, hit in anchors.items() if terms & content_terms(hit.text)),
                key=lambda key: (-len(terms & content_terms(anchors[key].text)), key),
            )[:24]
        steps[-1]["chunk_ids"] = list(dict.fromkeys([*steps[-1]["chunk_ids"], *anchor_ids]))
        for rank, key in enumerate(anchor_ids, 1):
            scores[key] += 1.2 / (40 + rank)
            evidence[key] = anchors[key]
    terms = content_terms(query)
    for key, hit in evidence.items():
        # An overview is only a routing hint; claims still cite the full source chunk.
        if key in preferred and terms & content_terms(hit.text):
            scores[key] += 0.003
    selected, counts = [], defaultdict(int)
    for key in sorted(scores, key=lambda item: (-scores[item], item)):
        hit = evidence[key]
        if counts[hit.video_id] >= (k if video_ids and len(video_ids) == 1 else 2):
            continue
        if any(near_duplicate(hit.text, previous.text) for previous in selected):
            continue
        counts[hit.video_id] += 1
        selected.append(hit)
        if len(selected) == k:
            break
    return selected, steps


def near_duplicate(left: str, right: str) -> bool:
    """Detect repeated openings despite auto-caption spelling/punctuation differences."""

    def shingles(text):
        words = re.findall(r"\w+", text.casefold())[:64]
        return {tuple(words[i : i + 3]) for i in range(max(0, len(words) - 2))}

    a, b = shingles(left), shingles(right)
    return bool(len(a) >= 12 and len(b) >= 12 and len(a & b) / min(len(a), len(b)) >= 0.65)
