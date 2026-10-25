# Playlist import failure diagnostics and backoff

Requested 2026-10-25 for playlist `PL9ybxsKzafo2qW8opDxQfGA62jUte-0vd`.
Status: fix implemented and verified; real playlist import remains externally blocked.

## Diagnosis

The playlist enumerates 17 videos. Multiple saved attempts marked all videos with
one generic error, obscuring the actual failure. A bounded first-video probe found
Russian auto captions but `youtube_transcript_api.IpBlocked` on caption fetch.
The independently advertised yt-dlp JSON3 caption URL returned HTTP 429 with no
Retry-After value. Normal browser transcript export reported no transcript.
The playlist URL, library index and OpenAI endpoint are not the failing stage.

## Scope and acceptance

- [x] Map upstream failures to stable, safe error codes/stages and actionable text.
  Distinguish blocking/rate limits, language mismatch, absent captions, network
  errors, metadata errors and invalid transcript processing.
- [x] Stop a collection after a global YouTube block; mark remaining items not
  attempted rather than claiming every video has missing captions.
- [x] Apply a persisted, local five-minute minimum retry cooldown after a block.
  Explain that this is application backoff and YouTube may require longer; never
  automatically change IPs, use credentials, download audio or call paid models.
- [x] Preserve prior usable library/index state and successes downloaded before
  a block; retain prior playlist membership on partial retries.
- [x] Show accurate checked/indexed/failed/not-attempted counts, the root cause,
  cooldown and retry controls in the library UI. Preserve original import settings.
- [x] Offline regression tests cover classification, fail-fast/cooldown across
  restart, partial success, membership, safe messages and no Whisper on blocks.
- [x] Required pytest/Ruff/JS checks pass, then restart the real app and perform at
  most one fresh import attempt to verify either completion or the classified
  external failure. Do not claim success if YouTube continues returning 429.

## Verification

- 138 offline tests passed (15 additional cases); Ruff check and format passed;
  Node JavaScript syntax check and pip dependency consistency passed.
- The README offline walkthrough passed against a separate synthetic database:
  import/idempotent re-import, stats, search, extractive ask and benchmark. The live
  source database was untouched by that walkthrough.
- Tests include first-video block, 16 unattempted items, source preservation,
  cooldown surviving restart and the ten-job display limit, repair during cooldown,
  partial success and prior playlist membership, language/caption error separation,
  safe messages, explicit Whisper-only fallback and retry after cooldown expiry.
- Restarted real semantic server at `http://127.0.0.1:8000/`. One fresh import job
  `3973b34e7bb8429ab438d4fb763ce47a` listed 17 videos and encountered `IpBlocked`
  on the first caption fetch. Result: blocked, 1 checked, 0 indexed, 1 failed,
  16 not attempted. Five-minute minimum backoff recorded durably.
- API and real browser show the classified cause, accurate counts, disabled retry
  during cooldown and available local rebuild. Existing library: 20 videos,
  semantic retrieval enabled, `ready=true`; no source/index rebuild was needed.
- Import is **not complete**. It remains blocked by YouTube caption access.
  No OpenAI requests, audio downloads, proxy changes or automatic retries occurred.
  Local evidence is saved under ignored `data/live/import-blocked-check.json` and
  `data/live/import-blocked-qa.jpg`.
