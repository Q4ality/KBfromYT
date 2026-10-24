# KBfromYT

A local YouTube transcript knowledge base with source timestamps, hierarchical
retrieval and a reproducible evaluation harness. Python 3.12+, no service or API
key needed for the offline baseline. Version 0.2.0 adds a local browser RAG chat.

For the validated 20-video Russian playlist, isolated runtime setup and ready-to-run
queries, see [the live environment guide](docs/LIVE_PLAYLIST.md).

For the browser chat, see [setup and usage](docs/CHAT.md). It uses your OpenAI
endpoint, remembers three recent exchanges, retrieves local transcripts and clearly
highlights missing support. [Specification](docs/CHAT_UI_SPEC.md) ·
[implementation and validation record](plans/07-rag-chat.md).

With the live environment and playlist already present:

```powershell
# Put OPENAI_API_KEY in .env beside this README (see .env.example).
.\scripts\start-chat.ps1
```

Open [the local chat](http://127.0.0.1:8000/). The default model is `gpt-6-luna`.
Chat questions make billable OpenAI requests. The API key stays on the server.

## Quick start (PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev,chat]"
.\.venv\Scripts\yt-kb import examples/demo.json
.\.venv\Scripts\yt-kb import examples/demo.json
.\.venv\Scripts\yt-kb stats
.\.venv\Scripts\yt-kb search "trajectory tool selection"
.\.venv\Scripts\yt-kb ask "What does trajectory evaluation check?"
.\.venv\Scripts\yt-kb evaluate examples/benchmark.json --k 5
```

On Linux/macOS use `.venv/bin/python` and `.venv/bin/yt-kb`. Or activate your
environment and run `python -m kbfromyt`. Global flags such as `--db` go **before**
the command: `yt-kb --db data/research.sqlite3 search "agent evaluation"`.

The example is synthetic: its video ID is a placeholder, so its timestamp links
do not lead to a real source. Its benchmark checks behavior, not research quality.
Real imports create links to the actual video and source start time.

## YouTube and audio

```powershell
yt-kb ingest "https://www.youtube.com/watch?v=VIDEO_ID_HERE" --languages en ru
yt-kb ingest "https://www.youtube.com/playlist?list=PLAYLIST_ID" --collection --limit 20
yt-kb ingest "https://www.youtube.com/@CHANNEL/videos" --collection --limit 20
python -m pip install -e ".[whisper]"
yt-kb ingest "VIDEO_ID_HERE" --whisper --whisper-model base
yt-kb transcribe recording.wav --video-id VIDEO_ID_HERE --title "My source video"
```

Replace placeholders with real 11-character IDs/URLs. Caption ingestion prefers
manual tracks across requested languages, then auto captions. Whisper fallback
applies only to missing/disabled captions; blocked/network requests remain errors.
Audio download/conversion requires ffmpeg. Whisper downloads model weights on first
use. Collection imports report per-video failures and return a nonzero exit code
if any fail. Repeated content is skipped; changed metadata/transcripts replace it.

## Optional semantic search

```powershell
python -m pip install -e ".[semantic]"
yt-kb index
yt-kb search "checking the sequence of an agent's actions" --semantic
yt-kb evaluate examples/benchmark.json --semantic
```

FastEmbed downloads an English BGE model on the first run. SQLite remains the source
of truth; Qdrant runs locally under `data/semantic`. Re-run `index` after imports.
Set `--embedding-model` before both index and search to use another supported model
(choose a multilingual model for multilingual semantic search). English-model
cross-language quality is not guaranteed. Empty, incomplete and stale indexes fail
with a rebuild instruction. Model/index storage is excluded from Git.

## Answers

`ask` returns original evidence and citations by default. For generated synthesis,
install/run Ollama separately, make a model available, then use
`yt-kb ask "How should agents be evaluated?" --model YOUR_LOCAL_MODEL`.
Only the local loopback endpoint is used. Every generated claim must cite retrieved
evidence IDs; invalid citations reject synthesis. This checks citation existence,
not factual entailment. Review claims against their source passages.

## Design and limits

Video → Chapter → Chunk → SubtitleSegment; SQLite FTS5 at video/chapter/chunk levels,
optional dense rankings, reciprocal rank fusion, lexical coverage reranking and
same-chapter neighbor context. Source chapters take priority. Timed chapterization
and lexical boundary heuristics are fallbacks; neural semantic chunking, abstractive
summaries and a cross-encoder reranker are future work. A single long subtitle
segment is kept intact even if it exceeds the nominal chunk word limit.
Dense representations are currently full extractive text; embedding models truncate
long video/chapter documents to their token window. Chunk search preserves the
independent detail path; pooled or summarized parent vectors are future work.
Caption segments spanning chapter boundaries belong to the chapter containing
their start; their full original interval is preserved.

SQLite FTS tokenization has no stemming and is strongest for space-delimited text.
Search loads the local hierarchy in memory; large-scale operation needs streaming,
server indexing and measured limits. Each video stores one selected language track.
Broad parent matches can retrieve irrelevant children; scores are ranking values.

Specs: [product](docs/PRODUCT_SPEC.md), [architecture](docs/ARCHITECTURE.md),
[data model](docs/DATA_MODEL.md), [retrieval](docs/RETRIEVAL.md),
[evaluation](docs/EVALUATION.md), [decisions](docs/DECISIONS.md).
Implementation milestones and recorded results: [plan](plans/00-mvp.md).

## Development

Install `.[dev,chat]` to run the full test suite. Provider tests use mock HTTP;
ordinary tests do not call OpenAI or download embedding models.

```powershell
python -m pytest
python -m ruff check .
python -m ruff format --check .
```

Tests require no external service/model. The optional Qdrant adapter test uses
deterministic test vectors, and skips when qdrant-client is not installed.
CI installs it and checks Windows/Linux on Python 3.12/3.13.
No license has been selected yet; publication does not grant an open-source license.

## Upstream API references

Adapters follow the documented [youtube-transcript-api](https://github.com/jdepoix/youtube-transcript-api),
[yt-dlp](https://github.com/yt-dlp/yt-dlp),
[Qdrant client](https://github.com/qdrant/qdrant-client),
[faster-whisper](https://github.com/SYSTRAN/faster-whisper) and
[Ollama chat API](https://docs.ollama.com/api/chat) interfaces.
