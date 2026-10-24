# Local RAG chat

Version 0.2 serves a plain browser UI from FastAPI. The existing 20-video playlist
and multilingual index stay local. The configured OpenAI model handles query
planning, cited answer generation and a separate support assessment.

## Start on this device

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
Python 3.12 dependencies into `.venv-live`. Another device must first ingest/index
the playlist using [LIVE_PLAYLIST.md](LIVE_PLAYLIST.md); data is not stored in Git.
For other platforms, install `pip install -e '.[semantic,chat,dev]'` and run
`python -m kbfromyt chat` from the root.

Keep `.env` at the **repository root**, beside `.env.example`. Both it and all local
data are ignored by Git. Existing process environment variables take precedence.
Restart the server after changing configuration. The server never sends the key
to the browser. Do not paste it into a question.

## Configuration

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
| `CHAT_SESSION_TTL` | 3600 seconds of inactivity |
| `CHAT_MAX_REQUESTS` | 4 provider requests per turn |
| `CHAT_DEADLINE` | 60 seconds per turn |
| `CHAT_HOST` / `CHAT_PORT` | `127.0.0.1` / `8000` |

The startup script explicitly uses loopback and port 8000; pass `-Port 8002` to
change its port. Direct `python -m kbfromyt chat` reads host/port from the environment.
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

Enter sends; Shift+Enter inserts a line break. New chat clears the page and session.
The page may display older exchanges, while each model request receives at most the
last three completed pairs, trimmed further if necessary to fit the memory budget.
Follow-ups search again; old model answers never become source evidence. Failed or
cancelled requests do not enter memory. Sessions are isolated, expire after inactivity
and disappear on restart. There is no saved conversation history. A bounded cache
of completed request IDs prevents duplicated replies when a request is retried.

No-support and partial-support notices appear inside the answer and survive Copy
answer. Citation-validation failures suppress the draft. API/index failures have a
separate error state and are not presented as missing source evidence.

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
Qdrant client; SQLite connections are created in their query threads. Stop chat before
ingesting/reindexing, then restart. Missing, stale or mismatched indexes give an
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
