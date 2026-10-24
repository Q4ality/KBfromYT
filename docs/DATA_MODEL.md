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
