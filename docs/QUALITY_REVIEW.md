# Review and reproduce the quality baseline

`examples/chat-playlist-benchmark.json` contains 50 candidate questions, source
intervals, scope, required-point prompts and qualifications. The original 20-case
file is retained unchanged as `examples/chat-playlist-benchmark-v1.json`.

**No case is human-reviewed yet.** The new annotations and negative/partial labels
are proposals. In particular, required-point prompts need to be replaced or
confirmed with expected, attributed answer points during human source review.
Do not interpret candidate scores as reviewed answer accuracy.

The development/reserved split is 35/15 and keeps related topic families together.
It shares a source playlist and includes historically examined legacy cases, so
the reserved split is not a pristine blind test. Its query rankings have not been
run in this implementation cycle. Review labels without tuning against its results.

## Prepare and review

From the repository root, with the project runtime:

```powershell
.\.venv-live\Scripts\python scripts/evaluate_quality.py --validate-only --output data/live/quality-source-validation.json
.\.venv-live\Scripts\python scripts/evaluate_quality.py --review-sheet --output data/live/quality-review-sheet.json
```

The first command checks all source IDs, declared selections and gold bounds
without ranking reserved questions. The second exports a review template. Neither
makes provider calls. Review/report files stay under ignored `data/`.

For each case:

1. Inspect the indicated video/time intervals and their surrounding discussion.
   Check who is speaking and whether a passage quotes an opponent, uses a
   conditional argument, or is sarcastic. Correct ambiguous or inaccurate gold.
2. Write the expected supported points and their qualifications. List equivalent
   evidence in one `alternative_groups` group; use separate groups for independent
   required points. A literal quotation does not by itself establish entailment.
3. Check that gold lies inside the declared scope. For negative cases, inspect
   enough of that selection to justify the absence label; otherwise retain a
   provisional label. An unrelated retrieval result does not prove absence.
4. Record reviewer identity and notes. Set a case to `human_reviewed` only after a
   person performs that review. Keep provisional cases out of reviewed-score claims.
5. Review saved model answers separately for claim support, attribution, completeness,
   false abstention and unsupported assertions. Assign a failure category:
   retrieval miss, ranking/context failure, interpretation error, verification
   over-rejection, infrastructure failure, or annotation error.

Reopening a saved report does not call the model. Historical event accuracy is
separate from whether an answer faithfully reports the source author's position.

## Retrieval evaluation

```powershell
# Works while chat is running; no embedding model/provider calls:
.\.venv-live\Scripts\python scripts/evaluate_quality.py --output data/live/quality-lexical-development.json

# Stop chat first: Qdrant local allows only one process to own the index.
# Uses local embeddings; may download the model if its cache is missing:
.\.venv-live\Scripts\python scripts/evaluate_quality.py --hybrid --output data/live/quality-hybrid-development.json
```

The report identifies source snapshot, benchmark hash/split, Git revision, prompt
hash, processing/index/overview versions, model/settings and budgets. It compares
Recall@5/10, MRR and NDCG using one-to-one matching of gold groups and passages.
Alternative passages cannot earn duplicate credit. Candidate and human-reviewed
aggregates are separate; an empty reviewed subset produces null metrics.

Queries concatenate at most three setup questions with the final question; this
is a deterministic retrieval baseline, not model-generated query reformulation.
Detail/broad routes and server-equivalent source restrictions are exercised.
Neighbor expansion and required-point entailment are not automatically scored by
this runner. Scope violations and per-case retrieval latency are recorded.
Only run the reserved split (`--split heldout`) after fixing development choices
and recording the quality target. Do not automatically treat interval-overlap
recall as broad-answer completeness.

For explicit paid answer checks, `scripts/evaluate_chat.py --live --server
http://127.0.0.1:8000 --cases CASE_IDS --compare` uses the running server and compares
simple and bounded-agent paths. It sends the case's scope and setup turns. This is
optional integration work; it is not part of CI and has not been rerun for this
release. The direct `--live` mode requires stopping chat before opening Qdrant.
Recorded labels/status agreement remain distinct from human answer judgments.

## Recorded development baseline

The current 35-case **candidate** lexical baseline has Recall@5 0.4643, Recall@10
0.5000, MRR@5 0.3208 and NDCG@5 0.3559, with zero scope violations. The original
20-case lexical comparison remains 0.5882 Recall@5; these datasets and routes
differ and their aggregate numbers must not be read as a quality regression.
Current reports and review sheets remain in `data/live/`. Human-reviewed metrics
and numerical answer-quality acceptance targets remain pending.

On the same 35 development candidates, cached local hybrid retrieval measured
Recall@5 0.5357, Recall@10 0.6071, MRR@5 0.3833 and NDCG@5 0.4213, with zero scope
violations. This compares retrieval modes on candidate annotations, not final-answer
accuracy or a human-validated improvement. No OpenAI calls were made.
