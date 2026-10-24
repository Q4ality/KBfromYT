# Evaluation

JSON benchmark contains `{query, relevant: [{video_id, start, end}]}` cases.
A hit is relevant when video IDs match and intervals overlap with positive length.
One evidence interval earns credit for at most one gold interval. Recall@k divides
unique gold intervals found by total gold intervals. MRR uses the first relevant
rank; binary NDCG uses unique relevant hits and ideal min(k, gold count).
Unanswerable cases have empty relevant lists: report abstention accuracy separately,
and exclude them from answerable retrieval metric means. Reject empty datasets.

The checked-in synthetic corpus is a regression/smoke fixture, not a quality claim.
Run `yt-kb evaluate examples/benchmark.json --k 5` after importing the demo.

Before production use, write 50 questions across 20–30 real videos, including
paraphrases, narrow details, cross-video questions and unanswerable queries. Keep
gold timestamps and split calibration/test sets. Compare fixed vs lexical vs
neural semantic boundaries; flat vs hierarchy; lexical vs hybrid; reranker off/on.
Measure latency, disk usage and ingestion cost alongside retrieval metrics.
Human review scores answer correctness, groundedness, citation entailment and
timestamp accuracy. Model-generated judgments cannot replace source review.
