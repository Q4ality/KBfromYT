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

## Preliminary chat results, 2026-10-25

The 20-case playlist benchmark contains 8 direct, 4 paraphrased, 3 follow-up,
3 unanswerable and 2 partially answerable questions. Gold intervals were inspected
by the assistant; human relevance and entailment review remains pending.

| Run using standard OpenAI `gpt-6-luna`, low | Expected statuses matched | Correct unanswerable labels | Median answer latency | Provider requests including follow-up setup |
| --- | --- | --- | --- | --- |
| Initial single-pass comparison | 17/20 | 3/3 | 5.63 s | 64 |
| Initial bounded agent | 15/20 | 3/3 | 6.62 s | 67 |
| Agent after bounded quotation correction | 17/20 | 3/3 | 5.96 s | 69 |

No returned citation failed the structural provenance check. The final run had three
false abstentions (`d7`, `d8`, `p3`), all follow-ups matched, and both multipart cases
were labeled partial. This is status agreement, not human-rated correctness. The
final run used 102,111 input / 6,239 output tokens including follow-up setup. These
samples do not establish an agentic quality improvement or a latency guarantee.

The offline lexical comparison on 17 answerable cases measured Recall@5 0.5882,
MRR 0.5147 and NDCG 0.5330 for both parent-expansion variants. It is separate from
the live hybrid agent. Full answers, excerpts and reports remain under ignored
`data/live/`. These measurements preceded version 0.3 cue cleaning and must not be
presented as post-cleaning quality measurements.

Version 0.3 adds offline regression checks for cue removal/raw provenance, durable
history restoration/deduplication, owner isolation, pagination, partial ingestion,
maintenance coordination, index repair and interrupted jobs. No new paid benchmark
or live YouTube import was run for this change. The existing corpus was cleaned and
reindexed locally, and the saved-chat UI was checked using the labeled offline fixture.
