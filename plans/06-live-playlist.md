# Live playlist validation

## Goal and scope
Create an isolated Python runtime, ingest one user-selected YouTube playlist into
a separate database, build the real semantic index, and verify source citations.
Keep the demo database unchanged. Do not commit transcripts, audio, databases,
downloaded model weights or credentials. No paid services are required.

## Approach
1. Create `.venv-live` with the package's semantic dependencies.
2. Check dependency consistency and save the resolved environment locally.
3. Enumerate the selected playlist and record a local manifest of expected IDs.
4. Fetch one video first to expose real API issues before the full playlist run.
5. Ingest all accessible playlist videos, recording per-video failures explicitly.
6. Build FastEmbed/Qdrant indexes in `data/live/`; test lexical and semantic queries
   against actual transcript passages and verify video/timestamp provenance.
7. Reingest to check idempotency, report coverage and any unavailable items.

## Acceptance criteria
The isolated environment passes `pip check`; a real playlist is enumerated; every
enumerated item is either imported or has a recorded reason for failure. At least
one imported source is retrievable through both lexical and real model-backed
search, with segment IDs and timestamp URLs. Report what actually ran, including
service restrictions or model-download failures. Fix discovered defects with
targeted tests and run repository checks if source behavior changes.

## Progress
- [x] Isolated environment ready.
- [x] User-selected playlist and expected-item manifest recorded.
- [x] Live ingestion completed and coverage audited.
- [x] Real semantic indexing and source-grounded queries verified.
- [x] Idempotency checked and outcome recorded.

## Recorded outcome
Playlist `PLHfd11lpeE2ij70tf2a7V2fNko7zeSx6B`: 20/20 sources imported, no failures;
24.92 hours, 33,052 normalized segments, 399 chapters, 1,422 chunks. All captions
are Russian auto-generated tracks. Real multilingual MiniLM embeddings produced
384-dimensional vectors; Qdrant contains all 1,841 expected records. Russian and
English search probes returned evidence whose text/segment IDs/timestamps matched
the source database. A repeat runner pass reused all 20 records without changes.

`pip check`: passed. `python -m pytest -q`: 32 passed (includes new runner resume and
failure-accounting tests). `ruff check .` and `ruff format --check .`: passed.
No core ingestion defect prevented the live run. The yt-dlp runtime warning did
not block caption acquisition. Broad parent expansion can hurt relevance; probes
are not a labeled quality benchmark. Whisper and generated synthesis were not run.
See docs/LIVE_PLAYLIST.md for reproducible commands and local report locations.
