# Retrieval

Default: Unicode-tokenized SQLite FTS5 BM25 candidate lists at video, chapter and
chunk levels. Query tokens are quoted literals joined by OR, so punctuation and
FTS syntax in user input cannot become operators. This baseline needs no model.

Optional: `index` creates FastEmbed vectors in local Qdrant for the three levels;
`search --semantic` fuses these dense rankings with the three lexical lists.
Model name and source revision must match the completion manifest.

Version 0.4 indexes overlapping token-sized windows of every original document.
The actual installed tokenizer supplies the limit (128 for the current multilingual
MiniLM), including special-token overhead. Each exact substring is re-tokenized and
checked before embedding. Window payloads retain parent ID, resolution level and
character offsets. Grouped nearest-neighbor search ranks distinct original documents
by their best matching window, so multiple windows cannot consume the whole top-k.
Source chunk/segment IDs and timestamps remain unchanged. The manifest records index
format, original document count, window count and maximum window tokens; an old
single-vector index is rejected and rebuilt by local maintenance.

Each parent candidate expands into its own chunks. Rank lists contribute
`1 / (60 + rank)` per chunk, once per list. A small query-term coverage bonus
reranks candidates. Stable ID breaks ties. Return at most k nonduplicate chunks.
Report the fused score as a ranking value, never as a calibrated probability.

Evidence contains original chunk text; parent and neighbor text is contextual.
URLs use `https://www.youtube.com/watch?v=ID&t=floor(start)s`.
Lexical search abstains when there are no matching terms. Dense search uses a
minimum cosine similarity threshold (default 0.45), which needs corpus calibration.
Neither matching terms nor similarity establishes that a source answers a question.
The default evidence report makes no generated factual claims.

Ollama is explicit opt-in via `ask --model MODEL`. It receives labeled evidence,
instructions to ignore source instructions and structured JSON output constraints.
Every returned claim must cite an existing evidence ID; malformed/unreferenced
claims fail closed. Citation existence is validated; factual entailment still
requires human evaluation. No transcript leaves the machine in default mode.

Browser chat explicitly opts into OpenAI and uses the same hybrid retrieval with
at most three selected children per parent candidate. Direct chunk hits remain
available. Video filters apply to both lexical and dense paths. Context expansion
accepts only fresh source handles and stays in the source chapter. Ranking controls
are optional; existing CLI search defaults are preserved. The preliminary 20-case
retrieval benchmark did not establish a quality gain from bounded parents.

The agent reformulates retrieval queries using bounded recent history, then may
refine once. Each cited quote must be a literal substring of its original chunk;
source bounds and raw segment IDs are checked against the current corpus. A separate
model-assisted support assessment removes rejected claims. This still requires
source review and does not establish historical truth.

## Broad questions and overviews

Each video has a versioned extractive overview: chapter topics and up to six original
passages selected across timeline bands with topic/argument cues. These are navigation
summaries, not generated quotations, complete argument inventories or factual verdicts.
The library/playlist overview API aggregates these cards with explicit pagination and
membership filtering. Topic metadata and source anchors never bypass citation checks.

Broad questions use an overview route, with three bounded facets (original question,
author's position/conclusions, arguments/evidence). Fuse the candidate rankings and
select at most two passages per video, unless explicitly scoped to one video. Keep
direct chunk evidence, per-turn passage/input limits and the existing provider budget.
The model may explicitly choose the overview tool for questions missed by the local
intent heuristic. Narrow questions preserve the detail route and contextual expansion.

Overview anchors have their own candidate path, so corpus-wide repeated introductions
cannot crowd them out before fusion. Near-duplicate openings are filtered across
selected passages as well as limiting results per video. This avoids counting the
same series introduction as several independent arguments. Distinct videos are not
forced into results when they only repeat already selected text.

Responses record bounded retrieval queries, candidate/returned chunk IDs and returned
video IDs. Coverage counts registered passages/videos, not complete videos reviewed.
An abstention says the retrieved passages lacked enough support and acknowledges that
relevant material may exist elsewhere. A faithful account of a speaker's position
requires evidence for that attribution; it does not require the video to independently
prove the underlying event. Quoted opponents must remain distinguished from narrators.
