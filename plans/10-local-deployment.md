# Portable local deployment

Goal: make a fresh checkout installable and diagnosable without copying this
machine's virtual environment or exposing its credentials.

## Scope and acceptance

- [x] One Python bootstrap handles Windows and POSIX virtual-environment paths;
  preserves existing `.env`; checks Python, architecture and SQLite FTS5.
- [x] Windows CPython 3.12 x64 uses the recorded dependency constraints. Other
  platforms explicitly use portable ranges, without claiming an identical lock.
- [x] Portable launcher and offline doctor need no shell activation or paid calls.
- [x] Guide covers new installs, existing-library transfer, backups, upgrades,
  troubleshooting, network requirements and honest platform validation limits.
- [x] Verify a separate clean runtime on this Windows machine, required offline
  tests/lint, and preservation of the existing live installation.

No new ingestion, paid model benchmark, public hosting or installer packaging is
included. Linux/macOS execution requires separate machines/runners to validate.

## Verification

Recorded 2026-10-25 on Windows x64 / CPython 3.12.10:

- Created a separate `.venv-repro-clean` using the portable bootstrap. Runtime-only
  install succeeded with the recorded constraints; `pip check` passed. Packages
  reused this machine's pip cache; this was a clean venv, not a new physical machine.
  The existing `.env` was preserved and no credentials were printed.
- Imported FastEmbed, ONNX Runtime, Qdrant client, tokenizers and tiktoken from the
  clean runtime. Fresh-library FastAPI lifespan/UI/status/library/history smoke
  checks passed using isolated paths and no provider key. Tokenizer cache was reused.
- The full offline README walkthrough passed in that runtime with an isolated demo
  database. No YouTube fetch, embedding-model redownload or paid chat was performed.
- 103 offline tests pass. After tightening existing-venv compatibility checks, all
  13 deployment-script tests passed again. Ruff lint/format and `git diff --check`
  passed. Tests cover credential preservation, no-write preflight, profile/path
  selection, interpreter mismatch, install arguments and root-relative launching.
- Python and PowerShell preflight commands passed. Strict offline doctor passed
  from both the live and clean runtimes against the current 20-video library.
- Original server remained running; HTTP status still reports ready and 20 videos.
- Initial sandbox-only venv/test attempts failed because Windows temporary-folder
  writes were denied. Retrying with normal temporary-folder access passed.
- CI now runs bootstrap preflight alongside its existing Windows/Linux Python
  3.12/3.13 checks. No complete Linux/macOS install or ARM validation was run locally.
