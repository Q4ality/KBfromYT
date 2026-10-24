# Live playlist environment

Validated locally on 2026-10-24 with Windows and Python 3.12.10.

Playlist: [Катынь. Расследование — ПЛОХОЙ СИГНАЛ](https://www.youtube.com/playlist?list=PLHfd11lpeE2ij70tf2a7V2fNko7zeSx6B).

## Results

- 20 of 20 enumerated videos imported; zero failures.
- 24.92 hours; 33,052 normalized caption segments; 399 chapters; 1,422 chunks.
- All selected tracks are Russian auto-generated captions.
- Real local Qdrant index contains 1,841 video/chapter/chunk records.
- Model: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, 384 dimensions.
- Russian lexical and hybrid queries and an English hybrid query returned passages.
  Returned text, source segment IDs and timestamp URLs were verified against storage.
- A second runner pass resumed all 20 videos as unchanged. Stored-record reimport
  was also idempotent. Resume reuses stored inputs; it does not check YouTube for
  transcript updates. Use the main `ingest` CLI to refetch updated sources.
- `pip check`, 32 tests, lint and formatting passed in `.venv-live`.

The query probes verify the live pipeline and provenance, not retrieval relevance
or historical answer correctness. In particular, broad parent matches can promote
weakly related chunks. A human-labeled retrieval benchmark and ranking improvements
remain next steps. No generated synthesis or Whisper transcription was run.

## Local files

Everything below is intentionally excluded from Git:

- `.venv-live/`: isolated runtime, separate from the original `.venv`.
- `data/live/kb.sqlite3`: real-source database, separate from `data/kb.sqlite3` demo.
- `data/live/playlist.json`: full yt-dlp playlist manifest.
- `data/live/ingestion-report.json`: initial per-video outcomes and coverage.
- `data/live/resume-report.json`: repeat-run results.
- `data/live/environment.freeze.txt`: exact installed environment, including local package path.
- `data/live/semantic/`: Qdrant index and completion manifest.
- `data/live/search-validation.json`: complete query results and provenance checks.
- `data/models/fastembed/`: downloaded model cache.

Only scripts, package pins, plans and documentation are versioned. To use another
machine, rebuild the environment and reingest the playlist; Git does not carry the
captions or model files.

## Setup and query (PowerShell, repository root)

```powershell
.\scripts\setup-live.ps1

# Lexical search, no model initialization needed:
.\.venv-live\Scripts\yt-kb --db data/live/kb.sqlite3 search "Нюрнбергский процесс документы" --k 3

# Multilingual hybrid search:
$env:FASTEMBED_CACHE_PATH = Join-Path (Get-Location) 'data/models/fastembed'
.\.venv-live\Scripts\yt-kb --db data/live/kb.sqlite3 --index-dir data/live/semantic --embedding-model sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 search "эксгумация польских офицеров" --semantic --k 3
```

`setup-live.ps1` installs the validated Windows/Python-3.12 dependency pins from
`requirements/live-windows-py312.txt` and the editable project with semantic/dev extras.
If running CLI commands in a new shell, set `FASTEMBED_CACHE_PATH` again to reuse
the same cache.

## Recreate or resume the import

```powershell
New-Item -ItemType Directory -Path data/live -Force | Out-Null
.\.venv-live\Scripts\python -m yt_dlp --flat-playlist --dump-single-json --skip-download "https://www.youtube.com/playlist?list=PLHfd11lpeE2ij70tf2a7V2fNko7zeSx6B" | Set-Content -Encoding utf8 data/live/playlist.json
.\.venv-live\Scripts\python -u scripts/validate_playlist.py
.\.venv-live\Scripts\yt-kb --db data/live/kb.sqlite3 --index-dir data/live/semantic --embedding-model sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 index
```

The manifest runner saves its report after every entry and keeps failures visible.
It resumes existing videos and retries failed/missing ones. Run it against the same
manifest to resume, or enumerate again to discover playlist changes. Rebuild the
semantic index after any imports that change source records. Custom datasets can
use the runner's `--manifest`, `--db`, `--report` and `--languages` arguments.

yt-dlp warned that its default JavaScript runtime was unavailable. This did not
prevent metadata/caption ingestion. Audio extraction and ffmpeg were not exercised.
