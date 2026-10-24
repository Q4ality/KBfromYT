# Install or move a local KBfromYT instance

The application is ready for a single-user local pilot. The full playlist and
OpenAI chat have run on Windows x64 / CPython 3.12.10. Setup and startup scripts
also handle Linux/macOS paths, but a complete install, model download and real
playlist import have **not** been validated on those operating systems. This is
a Python application checkout, not a packaged desktop installer.

On 2026-10-25 a separate clean Windows venv was installed with this bootstrap;
dependency consistency, native imports, fresh-library UI startup and the offline
README walkthrough passed. All 103 offline tests passed. Existing package and
tokenizer caches were reused; this does not constitute a test on another machine.

## What you need

- Git access to the repository (currently private; authenticate with your own
  GitHub credentials or SSH key).
- 64-bit CPython **3.12 recommended**, or 3.13. The bootstrap checks the interpreter
  and SQLite FTS5. It deliberately rejects other interpreter versions until tested.
  On Linux, install your distribution's Python venv/pip components if absent.
- Internet access for Python packages, initial embedding/tokenizer downloads,
  YouTube ingestion and OpenAI answers. No GPU, Node, Docker or separate database
  server is required for the caption-based workflow. Whisper/audio conversion is
  optional and has additional requirements described in the README.
- Your own OpenAI API key and access to the model configured in `.env`.
  Chat calls incur API charges; setup and the offline doctor make no paid calls.

Allow disk space for a Python environment, model downloads, source/index data and
backups. Corpus and index are loaded locally; RAM and indexing time grow with the
library. Hardware minimums and large-library limits have not been benchmarked.
Start with the existing 20-video workload when assessing a new machine.

## 1. Clone and install

Windows PowerShell:

```powershell
git clone https://github.com/Q4ality/KBfromYT.git
cd KBfromYT
py -3.12 scripts/setup_live.py --check
py -3.12 scripts/setup_live.py
```

Linux/macOS shell (use `python3.13` instead if that is your selected interpreter):

```sh
git clone https://github.com/Q4ality/KBfromYT.git
cd KBfromYT
python3.12 scripts/setup_live.py --check
python3.12 scripts/setup_live.py
```

Setup creates `.venv-live`, installs runtime extras, runs `pip check`, and creates
`.env` from `.env.example` **only when it does not exist**. It leaves an existing
key/configuration intact. No activation is necessary. Run setup and start under
your normal user account. Keep the checkout in a writable local folder; avoid
simultaneous cloud-sync access to open database/index files.

On Windows, `scripts/setup-live.ps1 -Python python` is a convenience wrapper when
`python` resolves to your selected interpreter. If script execution is restricted,
use the Python commands above without changing PowerShell policy.

**Dependency reproducibility:** Windows CPython 3.12 x64 uses
`requirements/live-windows-py312.txt` as constraints. These pins capture the tested
environment; developer packages are installed only with `--dev`. Other OSs, CPU
architectures and Python 3.13 resolve the ranges in `pyproject.toml`; setup labels
this as a portable, unlocked profile. Native dependency wheels may differ or be
unavailable on some architectures. An unsupported wheel/build failure means that
machine still needs compatibility work; do not copy a Windows venv to it.

Every successful setup records package versions and platform details under
`data/environments/<venv-name>/`. The freeze includes the editable checkout path;
it is a diagnostic record, not a portable installer. For a repeatable deployment,
also record `git rev-parse HEAD` and use that commit on the destination. Pinning
Python packages does not freeze upstream model artifacts or YouTube transcripts.

## 2. Configure your endpoint

Edit **`.env` at the repository root**, beside `README.md` and `.env.example`:

```dotenv
OPENAI_API_KEY=YOUR_KEY_HERE
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-6-luna
OPENAI_REASONING_EFFORT=low
```

Keep the remaining template paths for the standard layout. Do not paste the key
into chat, commit it or include it in a support report. Process environment
variables override `.env`; restart after changing configuration. The configured
model must be available to your own account; setup does not test model access or
silently substitute a model.

## 3. Choose a library

### Fresh import

Start the UI with the commands in step 4. An empty library is expected on a new
checkout. In **Manage library**, paste the playlist URL, choose a video limit and
caption languages, and run **Import playlist**. For our current workload use:

```text
https://www.youtube.com/playlist?list=PLHfd11lpeE2ij70tf2a7V2fNko7zeSx6B
Video limit: 20
Languages: ru,en
```

The job downloads captions and the embedding model, processes source-linked chunks
and builds the index. Wait for completion and inspect any per-video failures.
YouTube availability, captions and rate limits may have changed since our import;
a fresh ingestion is not guaranteed to reproduce the exact same source corpus.

### Transfer the existing 20-video library

1. Stop the source server with Ctrl+C and wait until it exits. Stop any CLI import
   or indexing process too. Never copy live SQLite/Qdrant files or let two servers
   open the same index directory.
2. Copy the source machine's **entire `data/live/` directory** to the same relative
   path in the destination checkout. This retains source captions, library jobs,
   saved conversations, index metadata, vector files and any SQLite sidecar files.
   Copy `data/models/` as well to reuse cached embedding/tokenizer downloads.
   If using custom `.env` paths, transfer those locations instead.
3. Recreate the venv with step 1 and configure a separate destination `.env`.
   Do not transfer `.venv*` directories or machine-specific Git SSH settings.
4. Start the destination. Inspect library counts and maintenance status. On a
   different OS/architecture, or if Qdrant cannot open a copied index, stop the app
   and move `data/live/semantic/` aside as a backup. Restart; with the source DB
   present the app schedules index rebuilding. Sources remain in `kb.sqlite3`.

The source database is the authority; the semantic index can be regenerated.
Matching commit, model configuration and copied source data provide a closer
reproduction than fetching the playlist again. Model caches may still need to be
downloaded on the destination. After successful transfer, keep only one active
writer per copied instance; these databases have no cross-machine synchronization.

Saved chats are scoped to a browser owner cookie. Copying `app.sqlite3` preserves
their records, but a new browser/machine will **not** automatically show the old
owner's chats. There is no account sync or history recovery/import UI yet.

## 4. Start and check

Windows:

```powershell
py -3.12 scripts/start_chat.py
# In another terminal, from the checkout:
.\.venv-live\Scripts\python scripts/doctor.py
```

Linux/macOS:

```sh
python3.12 scripts/start_chat.py
# In another terminal, from the checkout:
.venv-live/bin/python scripts/doctor.py
```

Open [the local chat](http://127.0.0.1:8000/). The launcher runs from the project
root, so paths and `.env` resolve correctly even when launched from another
directory. It binds to `127.0.0.1`, reads `CHAT_PORT` (default 8000), and accepts
`--port 8002` to override it. Keep the terminal open; Ctrl+C stops the app.

The doctor is read-only and offline: it checks interpreter/FTS5, installed package
metadata, configuration, source count and index format/model metadata. It does not
open Qdrant, download models, test native dependency loading, compare the index
with source contents, check network/model permissions or prove answer quality.
Missing key/library/index produces a warning; `--strict` makes warnings fail too.

For a complete acceptance check on a new machine:

- Confirm the UI opens and library import/rebuild finishes without errors.
- Confirm the expected source count (20 for a successful copy of our library).
- Inspect [runtime status](http://127.0.0.1:8000/api/status): `ready` must be true.
- Ask one question and inspect its source excerpt/timestamp. This step makes paid
  OpenAI requests and verifies model access that the offline doctor cannot check.
- Reload the page and reopen the conversation from Saved chats.

The first startup may download tokenizer files; first semantic indexing/retrieval
may download model files. Cached local search can work without YouTube, but OpenAI
chat still needs network access. Neither setup nor the doctor guarantees offline
startup when caches are empty.

## Back up, upgrade and recover

Stop all writers first. Back up `.env` separately as a secret and copy `data/live/`
(or configured DB/index locations). `data/models/` is optional for recovery with
network access. Record the Git commit and environment profile. Restore into a
stopped instance at the same layout, recreate its venv, then run the doctor and
start it. Browser-owner limitations still apply to restored chats.

For upgrades: stop the app, make that backup, `git pull --ff-only`, rerun setup
with the same interpreter, then start. Startup may reprocess derived documents
and rebuild an outdated index; let maintenance finish. Before downgrading, restore
the matching database backup as well as the old code; older code is not guaranteed
to read a newer schema/index. Automatic pre-maintenance source backups do not
replace your complete source/state backup.

## Troubleshooting and deployment limits

| Symptom | Action |
| --- | --- |
| Python/FTS5 preflight fails | Select 64-bit CPython 3.12/3.13 with SQLite FTS5; check venv/pip availability. |
| Existing venv uses another Python | Create a separate runtime with `setup_live.py --venv .venv-new`; start with `start_chat.py --venv .venv-new`. Do not reuse/copy an incompatible venv. |
| Package download/build fails | Check package-index access and native wheel availability. Windows pins apply only to Windows x64 / Python 3.12. Save the error and environment profile. |
| Model/tokenizer cannot load | Check internet/cache permissions and restart. Setup installs packages, not model artifacts. |
| Port already in use | Stop the other instance or pass `--port 8002`; use the corresponding browser URL. |
| Index locked | Stop the other process using that index; changing only the port does not resolve a Qdrant file lock. |
| Missing/stale index | Use Manage library to rebuild; if a copied index cannot open, move it aside while stopped, then restart. |
| No key / unauthorized model | Check the root `.env`, environment overrides and account/model access, then restart. Never include the key in logs you share. |
| Playlist import partially fails | Inspect job failures, wait for rate limits if relevant, then retry. Imported sources remain usable. |

This release serves one local user with one server process. It has no public
authentication, remote-user management, service auto-start, packaged installer,
container deployment, cross-machine history sync or measured hardware minimum.
Those are separate deployment work. The current readiness claim covers a
developer-assisted local installation, with Windows validated and other platforms
requiring the acceptance check above.
