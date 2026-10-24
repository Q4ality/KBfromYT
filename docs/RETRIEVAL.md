# Retrieval

Default: Unicode-tokenized SQLite FTS5 BM25 candidate lists at video, chapter and
chunk levels. Query tokens are quoted literals joined by OR, so punctuation and
FTS syntax in user input cannot become operators. This baseline needs no model.

Optional: `index` creates FastEmbed vectors in local Qdrant for the three levels;
`search --semantic` fuses these dense rankings with the three lexical lists.
Model name and source revision must match the completion manifest.

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
