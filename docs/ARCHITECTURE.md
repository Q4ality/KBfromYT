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

Version 0.2 adds `web` (FastAPI plus static assets) and `chat` (configuration,
sessions, provider, bounded tools, agent and validation). One process owns the
embedding model/Qdrant client for its lifetime and serializes retrieval access.
SQLite connections are opened in the query worker thread. Stop chat before external
CLI index maintenance. UI maintenance is serialized inside the service.

Browser requests receive server-issued session cookies. Per-session locks order
turns and deduplicate completed requests; a TTL and capacity limit bound process
memory. Each new question sends an explicit three-pair history window. Provider
response items are retained only inside the current tool loop, with `store=False`.

The OpenAI Responses adapter is separate from CLI Ollama synthesis. A forced search
registers request-scoped evidence handles. Typed claims must contain exact original
quotes and valid source bounds; a separate model assessment checks support before
the server derives status and renders claims. A correction can use the remaining
request budget. Draft output is never streamed to the UI. Tool and transcript text
cannot authorize new tools or alter this policy.

Version 0.3 introduces `chat/history.py` for separate durable app state and
`web/library.py` for background ingestion/index jobs. The browser owner token is
hashed in conversation records; SQLite connections are short-lived and thread-local.
Conversation reads are owner-scoped, and durable request IDs deduplicate retries.
Full saved transcripts are paginated for display; only three accepted pairs hydrate
model memory. New chat clears transient session state, preserving durable history.

An application operation lock serializes chat and library maintenance. A job marks
maintenance immediately, waits for active chat, fetches/validates requested captions,
backs up source SQLite, reprocesses raw inputs, imports usable videos and rebuilds
the existing Qdrant client under its corpus lock. Corpus metadata refreshes only
after successful indexing. Failures retain a repair state, never a ready stale index.
Restart marks interrupted jobs failed. Processing-version changes automatically
schedule cleanup from saved raw captions; no OpenAI calls are required.

Version 0.4 separates embedding windows from citation chunks. The embedder's real
tokenizer creates checked overlapping source substrings for all document resolutions;
Qdrant groups window matches back to distinct original IDs. A format-version check
triggers a serialized upgrade even when raw transcript hashes have not changed.

`overviews.py` builds deterministic extractive video summaries from across each
timeline. Store owns their persistence and versioning. The library API groups these
source-linked cards by the selected playlist or whole library. Broad retrieval uses
overviews as routing hints, generic query facets and video diversity, then supplies
original evidence to the same quote/provenance/support checks. Response traces and
excerpt coverage make the difference between retrieved support and whole-corpus
knowledge visible. No external summary generation or agents framework is needed.
