# Product specification

## Goal and source
Build a local knowledge base from YouTube transcripts, based on the project chat
“Сбор базы знаний субтитров” (three exchanges, October 2026). The user should find
and compare evidence across videos and return to the exact source passage.

## Version 0.1
- CLI accepts a video URL/ID, playlist or channel URL with an explicit item limit.
- Prefer manual captions across requested languages, then generated captions.
- Preserve raw segments, language, transcript source and metadata.
- Support local JSON transcript import for reproducible, network-free operation.
- Optional local audio transcription with faster-whisper when captions are missing.
- Build Video → Chapter → Chunk → SubtitleSegment hierarchy.
- Use supplied chapters; otherwise bounded timed chapters. Chunk on segment and
  sentence boundaries with lexical topic drift and bounded size; preserve provenance.
- Store metadata and lexical indexes in SQLite. Optional FastEmbed + Qdrant local
  indexes original video/chapter/chunk representations for dense retrieval.
- Search all three levels, merge with reciprocal rank fusion, expand parents and
  same-chapter neighbors, and apply a transparent lexical coverage reranker.
- Default answer is an evidence report with quotations and video timestamps.
  Optional local Ollama synthesis must return a distinct synthesis field and
  references to retrieved evidence, with citation validation.
- Reimport is atomic and idempotent. Updates replace obsolete hierarchy/index rows.
- Evaluate retrieval with Recall@k, MRR and NDCG, including unanswerable cases.

## Acceptance
The documented offline commands import a fixture twice without duplication,
retrieve its expected passage, output source timestamps, abstain on an unmatched
query and run the fixture benchmark. Unit/integration checks cover persistence,
provenance, caption preference, hierarchy, retrieval and evaluation. Tests and
lint pass on Python 3.12. No API key is required for offline use.

## Version 0.2

Local browser chat uses an explicitly configured OpenAI endpoint, bounded retrieval
tools, the last three completed exchanges and claim-level timestamp citations.
Unsupported questions receive a prominent fixed notice. Partial support, citation
verification failures and infrastructure failures have distinct states. See the
[chat specification](CHAT_UI_SPEC.md) and [usage guide](CHAT.md).

## Non-goals and subsequent work
No public multi-user service, cloud deployment or knowledge graph.
Neural chapterization, embedding-based semantic boundary detection, abstractive
summaries, cross-encoder reranking and a human-authored 20–30-video/50-question
benchmark are later phases. Do not claim the offline lexical heuristic is neural
semantic chunking or that synthetic fixture metrics measure real-world quality.

## Version 0.3

- Remove known non-speech cues from derived captions/chunks; preserve raw inputs,
  stable surviving segment IDs and timestamps. Reprocess/version/reindex existing data.
- Browser playlist imports have explicit limits/languages, background progress,
  per-video failures and serialized index updates; users can trigger clean/rebuild.
- Persist conversations locally with original citation envelopes and notices.
  New chat preserves older conversations. Reload/restoration keeps model memory
  limited to three accepted pairs. A browser owner cookie scopes history access.
