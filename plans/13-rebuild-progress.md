# Rebuild progress and avoiding unchanged embedding work

User reported a rebuild apparently running forever on 2026-10-25.

## Diagnosis

Job `0866602496104714a5b4e7def10c37d6` was a requested Clean and rebuild
(`POST /api/library/rebuild`), separate from the blocked YouTube import. It completed
in 286.43 seconds, with 20 videos and 9,533 embedding windows. The source change
count was zero. CPU and index writes continued; the job was slow, not deadlocked.
Its UI showed a static message and no embedding progress.

Read-only inspection also found more stored point IDs than the completion manifest
declared. Local Qdrant collection deletion ignores directory removal errors; use
public point deletion before recreating a collection, and verify exact expected IDs
before reusing a current index. Do not remove filesystem directories manually.

## Acceptance

- [x] Show preparation and durable batch progress, elapsed time and last update.
  Keep video-download counts separate from embedding-window counts; no invented ETA.
- [x] Reuse an unchanged index only after source/model/format and expected point ID
  verification; remove obsolete extras without recomputing existing vectors. Missing
  points, stale metadata or invalid manifests must rebuild.
- [x] Full rebuild clears old points through the public client before collection
  recreation; completion marker appears only after verified successful writes.
- [x] Tests cover monotonic progress, skipped embedding work, missing points,
  changed source/model/format and collection directory removal failure.
- [x] Required checks pass; restart after the original rebuild completes and verify
  the real library maintenance finishes without fresh embedding work. No YouTube
  requests, OpenAI calls or source transcript changes.

## Verification

- 147 offline tests passed, including 9 added cases for batch progress, reuse,
  missing/stale indexes, obsolete points and failed collection directory removal.
  Ruff check/format and Node JavaScript syntax checks passed.
- Original rebuild completed successfully in 286.43 seconds before server restart.
- Real maintenance job `4fbe7095c55e4810863d541778c79e22` completed in 12.11 seconds:
  verified 1,835 source documents and 9,533 expected window IDs, removed 1,841
  obsolete extra points, reused all expected embeddings, zero videos changed.
- Actual stored point count now exactly matches the completion manifest: 9,533.
  API reports `ready=true`, 20 videos, semantic enabled, no active job.
- Real UI verified completed progress (9,533/9,533, 100%), elapsed time and the
  explicit reuse message. Evidence: ignored `data/live/rebuild-reuse-check.json`
  and `data/live/rebuild-progress-qa.jpg`.
- No YouTube or OpenAI requests were made by this investigation. The user's new
  caption retry remains blocked, separately from successful local maintenance.
  The UI now explicitly says rebuilding saved videos cannot restore YouTube access.
