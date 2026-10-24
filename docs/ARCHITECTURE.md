# Architecture

`YouTube / JSON / local audio → Pydantic input → normalized segments → chapters
→ chunks → SQLite source of truth + FTS5 → optional FastEmbed/Qdrant → retrieval
→ parent/neighbor context → evidence report / optional local synthesis`

Modules are deliberately independent: models, ingest, processing, store, semantic,
retrieval, answering, evaluation and cli. SQLite owns raw records and all provenance.
Vector indexes are derived and replaceable. No orchestration framework is required.

Search runs independent video, chapter and chunk candidate paths. A narrow detail
can enter through a chunk even if a parent representation misses it. Parent hits
expand to their chunks; reciprocal rank fusion merges candidates. Reranking adds
query-token coverage without replacing original evidence. Context expansion never
crosses a video or chapter boundary.

Source chapters take priority. Timed chapters and lexical topic drift are explicit
baseline fallbacks; they allow evaluation before paying for neural processing.
Representations currently use titles and extractive text, never fabricated summaries.

SQLite ingestion is transactional. Content hashes include all imported metadata,
segments and processing version. An ingestion revision invalidates the optional
vector index. Semantic search refuses a stale or mismatched model index and tells
the caller to rebuild. Vector rebuilding writes its completion marker only after
all uploads succeed. It never silently serves an incomplete index.

Local CLI is single-writer. Qdrant local has an exclusive lock; concurrent indexing
and searching is outside v0.1. Large corpora will need batched/streamed indexing,
server-mode Qdrant and job scheduling. Transcript text is untrusted input to models.
