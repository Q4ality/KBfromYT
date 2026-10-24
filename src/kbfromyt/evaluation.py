from __future__ import annotations

import math

from pydantic import Field

from kbfromyt.models import Contract, Evidence, Interval
from kbfromyt.retrieval import search
from kbfromyt.semantic import SemanticIndex
from kbfromyt.store import Store


class Gold(Interval):
    video_id: str = Field(pattern=r"^[A-Za-z0-9_-]{11}$")


class Case(Contract):
    query: str = Field(min_length=1)
    relevant: list[Gold]


def metrics(hits: list[Evidence], relevant: list[Gold], k: int) -> dict[str, float]:
    if k < 1:
        raise ValueError("k must be positive")
    if not relevant:
        return {"abstention": float(not hits)}
    found = set()
    gains = []
    first = 0.0
    for rank, hit in enumerate(hits[:k], 1):
        match = next(
            (
                i
                for i, gold in enumerate(relevant)
                if i not in found
                and hit.video_id == gold.video_id
                and max(hit.start, gold.start) < min(hit.end, gold.end)
            ),
            None,
        )
        gains.append(float(match is not None))
        if match is not None:
            found.add(match)
            if not first:
                first = 1 / rank
    dcg = sum(g / math.log2(i + 2) for i, g in enumerate(gains))
    ideal = sum(1 / math.log2(i + 2) for i in range(min(k, len(relevant))))
    return {"recall": len(found) / len(relevant), "mrr": first, "ndcg": dcg / ideal}


def evaluate(
    store: Store, cases: list[Case], k: int = 5, semantic: SemanticIndex | None = None
) -> dict:
    if not cases:
        raise ValueError("benchmark must contain at least one case")
    rows = [
        {"query": case.query, **metrics(search(store, case.query, k, semantic), case.relevant, k)}
        for case in cases
    ]
    means = {
        key: sum(r[key] for r in rows if key in r) / sum(key in r for r in rows)
        for key in ("recall", "mrr", "ndcg", "abstention")
        if any(key in r for r in rows)
    }
    return {"k": k, "cases": rows, "means": means}
