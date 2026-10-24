# 01 — ingestion
Goal: normalized, timestamp-preserving import from JSON, YouTube and optional Whisper.
Scope/modules: models.py, ingest.py, store.py, cli.py. Contracts: VideoInput and Segment.
Approach: manual-before-auto across requested languages; yt-dlp metadata/enumeration;
caption absence triggers optional audio fallback; per-video transaction replaces old rows.
Non-goals: account cookies, bypassing blocked requests, simultaneous alternate tracks.
Dependencies: phase 00 and installed adapters.
Tests: invalid times/IDs, caption selection, idempotency, metadata update and rollback.
Acceptance: fixture imports twice with one video, raw text and timestamps round-trip;
playlist errors are isolated and reported with a nonzero exit status.
