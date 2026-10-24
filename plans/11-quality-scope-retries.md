# Quality baseline, chat source scope and retry protection

Created 2026-10-25. Status: planned; implementation has not started.

This plan covers the three items selected at the end of the gap analysis:
quality measurement, explicit chat source scoping, and safe recovery of chat
requests. It does not cover all three longer-term milestones from that analysis.

## Outcome and boundaries

Users can choose which sources a conversation may use, recover a completed answer
after a lost response without another model call, and evaluate changes against a
reviewed set of real questions. Source citations and the last-three-exchanges
memory limit remain enforced.

Deferred: full-playlist research mode, language-aware query expansion, new embedding
models/rerankers, resumable ingestion, background index swapping, chat export/import,
packaged installers and additional OS validation. Evaluation should expose these
limitations rather than expanding implementation scope automatically.

Planning itself does not run new paid evaluations, reingest YouTube, alter the
source/index databases or restart the running application. During implementation,
keep ordinary tests offline and run any explicitly selected live checks separately.

## Current baseline

- Version 0.4 indexes 1,835 source documents as 9,533 embedding windows, with 20
  extractive video overviews. The source corpus contains 20 Russian-caption videos.
- The existing 20-case benchmark has assistant-inspected gold intervals; human
  relevance and entailment review remains pending. Its paid results predate the
  latest retrieval changes. Status agreement is not an answer-correctness score.
- Chat has no explicit library scope. Overview filtering does not filter chat.
  Tools can request video filters, but those are not a user-enforced source boundary.
- Completed turns deduplicate by conversation/request ID. The browser generates
  a new request ID on every submission, and a first request may create a
  conversation before the browser learns its ID.
- There are 103 passing offline tests in the recorded deployment baseline.

## Workstream A: establish the quality baseline

### A1. Dataset and review contract

Extend `examples/chat-playlist-benchmark.json` and the evaluation contracts in
`scripts/evaluate_chat.py`. Keep existing case IDs and their historical results.
Target 50 cases using this initial allocation:

| Category | Count | Purpose |
| --- | ---: | --- |
| Direct details | 12 | Names, dates and explicit statements with source intervals. |
| Paraphrases | 8 | Different wording and English questions about Russian sources. |
| Broad/cross-video | 8 | Author positions, competing arguments and qualified conclusions. |
| Follow-ups | 8 | Pronouns, remembered context and the three-exchange memory boundary. |
| Hard negatives | 6 | Plausible in-topic questions not supported by the selected sources. |
| Partial support | 4 | Realistic multipart questions with some unsupported details. |
| Scope contrasts | 4 | Evidence inside one selection but outside another. |

Tags may overlap categories: sarcasm, conditional arguments, quoted opponents,
caption errors, ambiguous names and repeated introductions. Include the originally
reported broad question and narrower formulations about what the author argues.

Each case records question/setup turns, intended scope, expected support state,
gold video/time intervals, required answer points, acceptable qualifications and
review status. Alternative valid passages are grouped so retrieval is not penalized
for finding an equivalent source. Broad cases can require several distinct points;
interval overlap alone cannot establish that those points were covered.

Expected answers describe what the sources support or attribute to speakers; they
do not encode an independently established historical verdict. Review hard-negative
labels against the declared scope and mark uncertain labels provisional. An
assistant-authored candidate is not labeled human-reviewed.

Keep questions, annotations and source IDs/timestamps in Git. Keep downloaded
transcripts, full answer reports, credentials and runtime artifacts under ignored
`data/`. A reviewer should inspect each relevant source passage in context.

### A2. Reproducible evaluation

- Reserve 35 cases for development and 15 for a held-out check. Split related
  paraphrases/setup chains together to avoid leaking their answers across the split.
  Record category and source overlap where a single playlist prevents independence.
- Record Git revision, benchmark version/split, source snapshot, processing/index
  versions, embedding model, retrieval settings, prompt version, provider model and
  budgets in every report. Never include the API key.
- Compare lexical and hybrid retrieval on the same frozen questions. Exercise the
  actual detail/broad routes, selected scope and context expansion. Use the existing
  application process or stop it before opening its Qdrant directory; never open a
  competing local client against the live index.
- Keep deterministic retrieval evaluation separate from model-generated query
  reformulation and final-answer evaluation. Label which query inputs each used.
- Report Recall@5/10, MRR and NDCG for answerable cases; broad required-point coverage;
  scope violations; and latency. Account for alternative gold intervals without
  double-counting credit. Retrieval metrics do not measure final answer correctness.
- For selected live runs compare the existing simple and bounded-agent paths. Report
  human-rated claim support/attribution, answer completeness, false abstentions,
  unsupported answers, structural citation validity, provider requests, tokens and
  median/p95 latency. Describe small sample sizes; do not claim a quality gain from
  a status-label match alone.
- Separate retrieval misses, ranking/context failures, interpretation errors,
  verification over-rejection and infrastructure failures in the review report.
- Prefer stored answers for human review; re-reading a report must not call a model.
  Capture a current baseline before changing retrieval behavior. If a live run is
  not performed, record it as pending rather than reusing old results as current.

### A3. Acceptance

- [ ] All 50 cases have valid IDs, scopes, source bounds and explicit review status.
- [ ] Human review of relevance, qualifications and expected support is recorded;
  provisional cases remain excluded from claims about reviewed quality.
- [ ] Versioned development/held-out splits and current retrieval baseline exist.
- [ ] A report distinguishes retrieval quality, answer quality and support labels.
- [ ] Failure categories identify the next retrieval experiments; no model/reranker
  change is made solely to improve a few handpicked demonstrations.

Set any numerical answer-quality target after reviewing development results and
before inspecting the held-out result. Record that decision. Structural source
validity and scope isolation are unconditional requirements, not tunable averages.

## Workstream B: enforce chat source scope

### B1. User and data contract

Add a typed scope to chat conversations and requests:

| Scope | Meaning |
| --- | --- |
| Entire library | All currently indexed videos. Default for legacy conversations. |
| Playlist | Imported video IDs belonging to one selected playlist. |
| Selected videos | A nonempty, canonical set of known video IDs. |

The chat composer gets its own visible scope selector and selected-source count;
the overview selector remains clearly separate. Save the scope with each
conversation and restore it when reopening. Changing scope starts a new conversation
so previous answers from another source set cannot silently enter model memory.
Keep the old conversation in Saved chats.

Store scope intent (playlist ID or video IDs), and record the actual resolved
video selection/source snapshot on each new turn. Playlist membership resolves
against current imported membership for a new turn; changes are visible to the
user. A replay of an already completed request returns its original saved answer
and original selection, even if the library has since changed.

Unknown/deleted playlists, unknown videos or an empty resolved selection produce
an explicit validation/unavailable state. They never fall back to the whole library.
Shared videos may belong to several playlists. Scope is a retrieval restriction,
not a new account/authorization system; existing owner checks still apply.

### B2. Retrieval enforcement

- Resolve scope server-side before calling the model. A supplied conversation
  scope must match the saved scope; reject mismatches.
- Pass allowed video IDs through a request-local retrieval context; do not mutate
  the resident shared Corpus or global configuration between requests.
- Apply the restriction to lexical and dense candidates, overview anchors, parent
  expansion and neighboring context. Intersect tool-requested filters with the
  allowed selection; reject explicit out-of-scope IDs instead of broadening search.
- Validate registered evidence and final citations against the resolved selection.
  A model instruction is not sufficient enforcement.
- Coverage distinguishes videos in the selected scope from total library videos,
  and still describes retrieved excerpts rather than complete videos reviewed.
- Preserve three accepted recent exchanges from that conversation only. Missing
  evidence is reported relative to the selected sources.
- Add backward-compatible defaults for old conversations and saved envelopes;
  version/migrate app-state schema without deleting existing history. Back up state
  before the first migration and test repeated startup.

### B3. Acceptance

- [ ] Two contrasting fixture playlists cannot leak evidence into each other through
  any retrieval route, tool-filter override, parent/neighbor expansion or citation.
- [ ] Entire-library behavior remains available and legacy history opens correctly.
- [ ] Selected videos, overlapping playlists, empty/deleted selections and changed
  playlist membership have explicit, tested behavior.
- [ ] Saved conversation scope restores after reload/restart; switching it starts
  a new conversation and prevents cross-scope memory.
- [ ] Citation links, raw segment IDs and source timestamps remain unchanged.

## Workstream C: recover requests without accidental resubmission

### C1. Identity and persistence

Create one client request ID per intentional user submission. Preserve it and its
payload while the result is uncertain; use the same ID when reconnecting/retrying.
Create a new ID for a genuinely new question or an explicitly chosen new attempt.

Establish the browser owner cookie before enabling submission. Add an owner-scoped
durable request record, unique on `(owner_hash, request_id)`, that maps a first turn
to its conversation before provider work starts. This closes the lost-first-response
gap where the browser does not yet know the conversation ID. Request lookup must
not create a conversation, expose another owner's record or call a provider.

The canonical fingerprint includes normalized message, declared scope and answer
mode, plus other user-controlled generation inputs if introduced. It must not
depend on mutable current library membership or a current source revision. Resolve
and store the source snapshot for execution separately. Reusing an ID with a
different payload returns a conflict, with no provider call.

Suggested durable states: queued, running, completed, failed before provider work,
cancelled, and interrupted/unknown. Persist request completion and the saved turn
in one transaction. Existing completed turns remain readable and can be resolved
without duplicate inserts. Serialize duplicate in-flight submissions; a second
caller observes the existing work/result rather than starting another model loop.

### C2. Browser recovery and honest failure handling

- Keep the pending ID, conversation/scope and payload in session storage until a
  terminal result is reconciled; avoid credentials or hidden model reasoning.
- On a lost response, reload or reconnect, query the owner-scoped request status
  first. Display a completed saved answer, wait for existing work, or explain the
  interrupted state. Disable a second independent submit while the first is pending.
- A recoverable lost HTTP response is different from a provider timeout or process
  crash. A request may have incurred provider work even if no final answer was saved.
  Mark that state uncertain and require an explicit new attempt; do not silently
  replay it or promise exactly-once billing across an external provider boundary.
- After restart mark abandoned running work interrupted/unknown; do not automatically
  call the provider again. Keep failed/cancelled attempts out of model memory.
- Expose a clear retry/recover action. Recovered results must render once, retain
  their original citations/scope, and add neither another history turn nor another
  memory pair. Keep drafts hidden until source verification is complete.
- Define request retention and align it with saved history. Missing owner cookies
  retain the existing ownership boundary; do not recover another owner's work by ID.

### C3. Acceptance

- [ ] A completed response lost before reaching the browser is recovered with zero
  additional provider calls, one saved turn and one displayed answer.
- [ ] First-turn loss, page reload, concurrent duplicates and replay after restart
  resolve to the same conversation/result when completion was persisted.
- [ ] Same ID with changed question/scope/mode conflicts without a provider call.
- [ ] A different owner cannot inspect or recover the request.
- [ ] Interrupted or ambiguous provider work never restarts automatically and is
  not described as a guaranteed free retry.
- [ ] Library changes after completion do not invalidate replay of the original
  answer; a new intentional submission uses the current resolved source selection.
- [ ] Existing durable-history and cancellation regressions continue to pass.

## Implementation order and expected files

| Step | Deliverable | Main files |
| --- | --- | --- |
| 1 | Dataset contract, review rubric, frozen current baseline | `examples/chat-playlist-benchmark.json`, `scripts/evaluate_chat.py`, `docs/EVALUATION.md` |
| 2 | Scope contract/state migration and retrieval enforcement | `chat/contracts.py`, `chat/history.py`, `chat/service.py`, `chat/tools.py`, `retrieval.py` |
| 3 | Scope selector, saved scope and scope regressions | `web/app.py`, `web/static/index.html`, `web/static/chat.js`, tests |
| 4 | Durable owner/request identity, states and recovery API | `chat/history.py`, `chat/service.py`, `web/app.py`, tests |
| 5 | Stable browser IDs, reconnect/recover behavior and UI checks | `web/static/chat.js`, `web/static/index.html`, tests |
| 6 | Re-evaluate, review results and document release behavior | evaluation reports, `docs/CHAT.md`, `docs/DATA_MODEL.md`, `docs/ARCHITECTURE.md`, `docs/DECISIONS.md`, this plan |

Source paths in this table are relative to `src/kbfromyt/` unless explicitly under
`examples/`, `scripts/`, `docs/` or tests. Scope must land before the final request
fingerprint/recovery contract so a retry cannot accidentally change its source set.
Steps can be separate reviewable commits, with the baseline recorded before behavior
changes. A live baseline/re-evaluation remains a separately reported integration run.

## Verification and completion

Use isolated fixture databases/indexes and mock providers for the new scope/recovery
tests. Assert provider-call counts and persisted turn counts, not only HTTP status.
Simulate response loss after commit separately from cancellation before completion,
and simulate restart between request claim, provider work and result persistence.
Use two playlists with contrasting evidence plus one shared video; test both
lexical and deterministic-vector paths without model downloads.

Required implementation checks from the project venv:

```powershell
.\.venv-live\Scripts\python -m pytest
.\.venv-live\Scripts\python -m ruff check .
.\.venv-live\Scripts\python -m ruff format --check .
```

Run the offline README walkthrough if evaluation/CLI behavior changes. Inspect the
browser with fixtures for source selection, saved scope, pending recovery, duplicate
rendering, prominent support notices and working source links. Run source-based
evaluation against a recorded snapshot; separately identify any live provider calls,
their usage and whether human review was completed. Do not require a paid benchmark
inside ordinary CI.

- [ ] Workstream A acceptance recorded; pending human/live checks remain explicit.
- [ ] Workstream B and C offline/API/browser acceptance passes.
- [ ] No regression in provenance, support notices, history ownership or memory bounds.
- [ ] Required tests/lint pass; migration backup/recovery is checked on fixtures.
- [ ] Current baseline and final results are comparable; regressions are explained.
- [ ] Product/data/architecture/usage docs reflect actual implementation, and changes
  are committed/pushed through the existing repository workflow.

## Verification record

Planning only: repository instructions, architecture/data/retrieval/evaluation specs
and current chat/history/request contracts were reviewed. No implementation tests,
paid requests, source/index modifications or service restarts were performed for
this planning change. Implementation and live/human validation are pending.
