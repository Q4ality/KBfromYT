# Transcript cleaning, playlist management and saved conversations

Requested 2026-10-25. Status: implemented; final verification and push recorded below.

## Scope and decisions

1. Commit/push the working 0.2 chat before new changes: completed as `844248a`.
2. Remove recognized non-speech caption cues from derived segments/chunks. Preserve
   raw captions, original segment IDs and timestamps. Unknown bracketed content stays.
   Bump processing version and reprocess existing raw inputs, then rebuild vectors.
3. Add a local library panel with playlist URL, explicit item limit/languages, import
   progress, per-video failures, indexed video list and clean/rebuild action.
4. Persist conversations and citation envelopes in a separate ignored SQLite database.
   A durable browser owner cookie scopes access; new chat preserves older chats.
   Reopening a chat hydrates at most three accepted pairs for model memory. Persist
   request IDs to prevent duplicate paid calls after a restart.

Library maintenance shares an application lock with chat. It waits for active
questions, blocks new ones, writes/reprocesses source records, rebuilds the existing
Qdrant client and refreshes the corpus. No concurrent index readers/writers. On
failure, expose readiness/repair state rather than serving stale vectors. Persist
job status; interrupted jobs can be retried after restart. Back up source SQLite
before reprocessing. No new OpenAI calls are needed for cleanup/import/history.

## Acceptance and verification

- Known English/Russian audio labels disappear, literal bracketed speech remains,
  raw text/segment positions survive and reimport invalidates old derived indexes.
- Saved chats survive service/browser reload, remain owner-scoped, show older turns
  with pagination, preserve notices/citations and never expand model memory beyond
  three completed exchanges. Restarted retries reuse durable completed replies.
- Playlist input accepts canonical YouTube playlist URLs only, with bounded limits.
  Background progress distinguishes downloads, processing, indexing and completion;
  partial failures remain visible. Only one maintenance job runs at a time.
- Library and chat resource access are serialized; index failure fails readiness.
- Run required offline pytest/ruff checks and one browser UI check. Do not repeat
  the previous paid benchmark. Apply cleanup/reindex to the existing local corpus.
- Update architecture/data model/usage docs, commit and push final changes.

## Progress

- [x] Push working chat checkpoint.
- [x] Transcript cue cleaning and local corpus migration.
- [x] Durable conversation storage and bounded restoration.
- [x] Background library jobs and UI.
- [x] Offline verification and documentation.
- [x] Final implementation prepared for commit/push; Git history records the release.

## Recorded verification

- Offline suite: 83 tests pass. Ruff lint/format pass.
- Cue cleaning applied locally to all 20 existing videos. Search excludes 329
  standalone audio-cue segments; all 33,052 raw segments remain stored. Derived
  corpus now contains 1,416 chunks. Rebuilt the cached multilingual Qdrant index;
  the real UI reports ready. Source backup is under ignored `data/live/backups/`.
- The labeled synthetic browser fixture saved a cited answer, kept it after New
  chat, and reopened the same answer/citation after page reload. No OpenAI calls.
- Offline job tests cover bounded playlist URLs, partial caption failures, active
  maintenance rejection, metadata refresh, interrupted jobs and failed-index repair.
- Durable history tests cover restart retry deduplication, three-pair restoration,
  owner isolation, complete older-message pagination and preserved citation envelopes.
- No paid benchmark or fresh YouTube download was run. Existing ingestion adapters
  were exercised with deterministic fixtures; live import remains an optional check.
