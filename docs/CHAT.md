# Local RAG chat

Version 0.5 serves a plain browser UI from FastAPI. The existing 20-video playlist
and multilingual index stay local. The configured OpenAI model handles query
planning, cited answer generation and a separate support assessment.

## Start on this device

For a new machine or library transfer, follow [LOCAL_DEPLOYMENT.md](LOCAL_DEPLOYMENT.md).
The portable bootstrap is `python scripts/setup_live.py`; the portable launcher is
`python scripts/start_chat.py`. Both Windows wrappers below use those scripts.

Run from the repository root, which contains `pyproject.toml` and `README.md`:

```powershell
.\scripts\setup-live.ps1
# For a new installation only; do not overwrite an existing .env:
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
# Edit .env and fill OPENAI_API_KEY, then:
.\scripts\start-chat.ps1
```

Open [http://127.0.0.1:8000/](http://127.0.0.1:8000/). This device already has the
playlist, index and configured key. The setup script installs the pinned Windows
Python 3.12 runtime dependencies into `.venv-live`. Another device can import the
playlist in Manage library or transfer a stopped instance's library following the
deployment guide; data is not stored in Git. Pass `--dev` to the Python setup
script (or `-Dev` to PowerShell) only when development tools are needed.

Keep `.env` at the **repository root**, beside `.env.example`. Both it and all local
data are ignored by Git. Existing process environment variables take precedence.
Restart the server after changing configuration. The server never sends the key
to the browser. Do not paste it into a question.

## Choose conversation sources and recover a request

**Chat sources** selects the entire library, one imported playlist or explicitly
selected videos. An empty or unavailable selection cannot silently expand to the
whole library. The server applies the selection to lexical/dense search, overview
anchors, context and final citations. Coverage shows selected and total library
counts. This control is separate from the overview-navigation selector.

Changing chat sources starts a new conversation and preserves the previous chat.
Reopening a saved chat restores its scope and only its recent memory. A playlist
scope uses its current imported membership for a new turn; each saved answer keeps
the original resolved video IDs and source snapshot. Previously saved answers retain
their citations even if the current library changes.

The browser establishes its owner cookie before enabling questions and retains a
pending request ID/payload in session storage. If a response is lost, it checks the
owner-scoped saved request and restores a completed answer without new model calls.
Reloading the tab can recover pending work too. An interrupted/cancelled request
may already have incurred provider work: **Prepare a new attempt** restores the
question for an explicit new submission rather than automatically calling again.
If no request record exists, **Resend same request** preserves the original ID.
Cleared owner cookies prevent recovery of that owner's requests or conversations.

Saved results, request records and history have the same indefinite local retention
in this release; there is no automatic purge or account synchronization. Failed or
cancelled attempts do not enter model memory. App-state schema version 2 migrates
legacy conversation scope to Entire library, with a pre-migration state backup.

## Configuration settings

| Setting | Default |
| --- | --- |
| `OPENAI_API_KEY` | Required for chat answers |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` |
| `OPENAI_MODEL` | `gpt-6-luna` |
| `OPENAI_REASONING_EFFORT` | `low` |
| `KB_DB` | `data/live/kb.sqlite3` |
| `KB_INDEX_DIR` | `data/live/semantic` |
| `KB_EMBEDDING_MODEL` | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` |
| `FASTEMBED_CACHE_PATH` | Set to `data/models/fastembed` in `.env.example` |
| `CHAT_MEMORY_TURNS` | 3 completed exchanges |
| `CHAT_STATE_DB` | `data/live/app.sqlite3`, saved chats and library jobs |
| `CHAT_SESSION_TTL` | 3600 seconds of inactivity |
| `CHAT_MAX_REQUESTS` | 4 provider requests per turn |
| `CHAT_DEADLINE` | 60 seconds per turn |
| `CHAT_HOST` / `CHAT_PORT` | `127.0.0.1` / `8000` |

The startup script explicitly uses loopback and reads `CHAT_PORT` (default 8000);
pass `--port 8002` (PowerShell wrapper: `-Port 8002`) to change its port.
Direct `python -m kbfromyt chat` reads host/port from the environment.
`--lexical-only` explicitly disables semantic search. Chat corpus paths come from
the settings above; the CLI's global demo `--db` option applies to other commands.

Standard OpenAI was tested with the user's configured account. Custom base URLs
must implement the Responses, strict function-tool and structured-output contracts;
Azure deployment adapters are not included. Missing access or incompatible settings
give explicit errors. The service never silently substitutes another model.

## Ask and inspect sources

Try: `Какая правовая система, по словам автора шестого выпуска, доминировала на
Нюрнбергском процессе?`, then `Как это связано с ролью судьи?`.
Click a numbered citation to expand the original passage and timestamp link.
Statements are attributed to the video; this corpus is not an independent fact check
of its historical claims. All current playlist captions are generated automatically.

Enter sends; Shift+Enter inserts a line break. New chat starts an empty conversation
and preserves earlier conversations in **Saved chats**.
The page may display older exchanges, while each model request receives at most the
last three completed pairs, trimmed further if necessary to fit the memory budget.
Follow-ups search again; old model answers never become source evidence. Failed or
cancelled requests do not enter memory. Transient sessions expire after inactivity;
saved conversations survive restarts in the separate local SQLite state database.
Click a saved title to reopen its messages, original citation envelopes and notices.
Long conversations have a Load older messages button; the saved-chat list also pages.
The reopened conversation restores only three accepted pairs for the next request,
trimmed further by the input budget. Durable completed request IDs prevent repeated
paid calls for a retried request after restart.

A year-long HttpOnly browser owner cookie scopes saved-chat access. The selected chat
ID is kept in local storage. Clearing browser cookies creates a different owner;
this version has no account synchronization or history recovery UI. Questions and
answers are stored unencrypted on this device under ignored `data/`. Back up the
state database to retain conversations. Viewing a saved answer does not call OpenAI;
its source card preserves the excerpt as it was when that answer was generated.

## Manage playlists and clean captions

Open **Manage library**, paste an HTTPS YouTube playlist URL (a watch URL with `list=`
also works), choose 1–100 videos and comma-separated caption languages, then select
Import playlist. The background job lists videos, fetches captions, processes chunks
and rebuilds the local index. Progress and per-video failures remain visible across
reloads. Partial imports retain usable videos. Duplicate video imports are idempotent;
playlist membership records the successfully imported selection from that run.

Recognized audio labels such as `[Music]`, `[музыка]`, `[applause]` and `[смех]` are
removed from derived searchable text. Music-note characters are removed while sung
words remain. Unknown bracketed content, dates and speaker labels stay intact.
Raw captions and timestamps remain stored; surviving segment IDs keep their original
positions. Standalone cue segments produce no evidence chunks. This is conservative
cue removal, not grammatical correction or ASR repair.

The first start after a processing-version change automatically backs up source
SQLite under `data/live/backups/`, reprocesses saved raw captions and rebuilds vectors.
**Clean and rebuild** repeats this operation without downloading videos. The existing
playlist was upgraded: 329 standalone cue segments omitted from search, 33,052 raw
segments retained, 20 videos and 1,416 cleaned chunks indexed.

Only one library job runs at a time. It waits for active questions and pauses new
ones until the index is ready. Interrupted jobs are marked failed after restart;
retry them from the panel. If an index rebuild fails, chat remains unavailable until
Clean and rebuild repairs it. Job metadata and playlist selections share the state
database with conversations; transcript content remains in the source database.

No-support and partial-support notices appear inside the answer and survive Copy
answer. Citation-validation failures suppress the draft. API/index failures have a
separate error state and are not presented as missing source evidence.

Broad questions such as `Кто убил польских офицеров в Катыни?` retrieve multiple
query facets and passages from several videos. The answer should explain the authors'
attributed positions with exact source quotes, distinguishing narrators from quoted
opponents. It does not establish a historical verdict independently of this library.
Expandable search details show the actual queries and excerpt coverage. A no-support
notice refers to these retrieved passages and acknowledges that other relevant
material may exist. Older saved answers preserve their original notices.

Under Manage library, open **Video and playlist overviews**. Select the whole library
or an imported playlist. Each extractive overview includes chapter topics and original
passages selected across the video's timeline, with source links. These are navigation
summaries; they are not generated factual conclusions or exhaustive argument maps.

The dense index now stores overlapping windows that fit the actual embedding
tokenizer, rather than truncating whole source chunks/chapters/videos. For the current
MiniLM that limit is 128 tokens including special tokens. The panel shows original
document count, embedding window count and limit. Window hits resolve to original
chunks for citation/context. Updating the index format automatically schedules a
local rebuild on restart, with no source downloads or paid generation.

For local diagnostics, `POST /api/library/search?broad=true` accepts the same search
body (`query`, `video_ids_or_null`, `k` between 1 and 8) and returns raw source results
and query facets without invoking OpenAI. It uses the resident index and maintenance
lock, so a separate diagnostic process does not contend for Qdrant's file lock.

## Limits and operation

The agent must search first. It can refine once or request bounded neighboring
context, within four provider calls including synthesis, correction and checking.
At most 12 source passages and three tool executions are allowed. Defaults budget
8,000 evidence tokens, 12,000 total input tokens and 1,800 output tokens per call.
Input budgets use a conservative tokenizer estimate; displayed usage comes from the
provider and is unknown if unavailable. Tokenizer data may download on first start.

Questions, bounded history and selected excerpts leave the device for the configured
endpoint. Embeddings and transcript storage remain local. Requests set `store=False`;
this does not promise general provider-side zero retention. Calls are billable.
Model-assisted support checking can miss errors; exact quote/provenance checks do
not prove that every claim follows from the source. Relevance review remains pending.

Use one process/worker without reload. One corpus owns the embedding model and local
Qdrant client; SQLite connections are created in their query threads. UI maintenance
serializes writes and indexing. Stop chat before using external CLI ingestion/indexing,
then restart. Missing, stale or mismatched indexes give an
explicit readiness error. This is a local application, without public-hosting auth.

## Verification

```powershell
.\.venv-live\Scripts\python -m pytest -q
.\.venv-live\Scripts\python -m ruff check .
.\.venv-live\Scripts\python -m ruff format --check .
# Offline retrieval measurements; no OpenAI requests:
.\.venv-live\Scripts\python scripts/evaluate_chat.py
# Optional billable comparison using the running real server:
.\.venv-live\Scripts\python scripts/evaluate_chat.py --live --server http://127.0.0.1:8000 --compare
# Restrict a follow-up run:
.\.venv-live\Scripts\python scripts/evaluate_chat.py --live --server http://127.0.0.1:8000 --cases d2 u1
```

The checked-in benchmark has 20 questions and gold source intervals. Transcript
excerpts, generated answers, usage logs and screenshots are kept under ignored
`data/live/`. The browser fixture on port 8001 is explicitly labeled synthetic and
must not be used as evidence that the real endpoint works. See
[evaluation](EVALUATION.md) for results and remaining review work.
