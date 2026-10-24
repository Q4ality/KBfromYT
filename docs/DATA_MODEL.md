# Data model

Pydantic models in `src/kbfromyt/models.py` are the external JSON contracts.

- VideoInput: canonical YouTube ID, title, channel, language, duration,
  published_at, transcript_source (manual/auto/whisper/import), segments and chapters.
- RawSegment: start/end seconds (finite, ordered), raw text. Normalized Segment
  adds a deterministic ID and separate cleaned text while retaining raw text.
- Chapter: ID, video_id, title, start/end, source and member segment IDs.
- Chunk: ID, video_id, chapter_id, start/end, original normalized text and segment IDs.
- Document: ID, level (video/chapter/chunk), source video/chapter, text and time span.
- Evidence: original chunk, parent title, source video title, citation URL,
  start/end seconds, raw segment IDs, rank score and optional neighbor context.

IDs derive from video ID and ordered source position; replacement removes every
old child row before inserting a new processed hierarchy. Changing processing
parameters changes the content hash. One selected transcript per video is stored;
simultaneous alternative languages/tracks are a future schema extension.

SQLite tables: videos (raw input JSON, processed JSON, content hash), documents
(three resolution levels), documents_fts (FTS5 mirror), settings (schema/revision).
SQLite foreign keys remove documents with a deleted video. FTS deletion/insertion
is explicit in the same transaction. Embeddings live only in a rebuildable Qdrant
collection with model/revision metadata in a completion manifest.

Chat-only contracts live in `chat/contracts.py`: a request has a message and
idempotency ID (plus an optional single-pass comparison flag). The response has
typed claims, server-resolved citations, support status, deterministic notice,
unanswered parts, configured model and available usage. Citations include original
excerpts/quotes, video/chapter metadata, segment IDs, time bounds and generated URLs.
Source handles are valid only in their current request. In-memory sessions retain
the bounded model window; durable state is separate from the transcript database.

Version 0.3's `app.sqlite3` stores conversations (ID, hashed browser owner, title,
timestamps), turns (ordered question, complete answer envelope, status, request ID
and fingerprint), library jobs (durable progress/results) and playlist selections.
Conversation ID plus request ID is unique. Read access requires the matching browser
owner; restoring memory selects only the last configured accepted pairs. Failed
answers can appear in saved history but are excluded from model memory. Cancelled
requests are not committed as completed turns. Provider credentials are not stored
in this database.

Caption cleaning preserves `VideoInput` raw segments unchanged. Derived `Segment`
text excludes recognized audio cues; cue-only segments are omitted while surviving
segment IDs retain their original raw positions. Chunks are rebuilt from cleaned
segments; the processing-version hash invalidates previous vector manifests.

Version 0.4 adds a source-database `overviews` table keyed by video ID and overview
version. Each extractive card stores chapter topics and source-linked passages with
original chunk IDs, excerpts, raw segment IDs, time bounds and URLs. Deleting/replacing
a source cascades its overview; missing/old overview versions refresh during indexing.

Qdrant points now represent token windows rather than entire documents. Payloads map
each window back to its original document ID/level, with exact start/end character
offsets and token count. Grouped hits still return original IDs to existing retrieval.
Chat envelopes add retrieval steps and coverage with defaults, so old saved responses
remain readable. Traces contain queries and IDs, without hidden reasoning or keys.
