# Executable plan: first version

## Goal
Deliver a reproducible local CLI and private GitHub repository based on the project chat.

## Scope and contracts
Use docs/PRODUCT_SPEC.md and Pydantic contracts in docs/DATA_MODEL.md.
Dependencies: Python 3.12, SQLite FTS5, public Python packages; model adapters optional.
Non-goals: UI, cloud, knowledge graph, neural processing research and quality claims.

## Architecture review
See docs/DECISIONS.md for risks and decisions. Preserve direct chunk recall,
raw provenance and index invalidation. Do not hide heuristic limitations.

## Milestones
- [x] Inspect workspace and source project chat; initialize main branch.
- [x] Write specs, architecture review and phased acceptance criteria.
- [x] Implement ingestion and transactional hierarchy persistence (01).
- [x] Implement processing, indexing and search (02–04).
- [x] Implement evaluation, test offline lifecycle, lint and package install (05).
- [x] Prepare validated v0.1.0 for the initial local main-branch commit.
- [ ] Create private Q4ality/KBfromYT and push main; verify remote SHA (blocked).

## Verification and outcomes
2026-10-24, Windows, Python 3.12:
- `python -m pip install -e ".[dev]"`: editable package built and installed.
- `python -m pytest -q`: 30 passed, including real Qdrant local storage with
  deterministic test vectors and mocked YouTube adapter contracts.
- `python -m ruff check .` and `python -m ruff format --check .`: passed.
- Installed `yt-kb` CLI: import twice (`true`, then `false`), stats (one video,
  five documents), search with citation, no-match ask with abstention, evaluate:
  all successful. Synthetic benchmark Recall@5/MRR/NDCG/abstention = 1.0.
  These scores are regression checks, not real-world quality measurements.
- Initial sandbox pytest invocation could not access Windows temporary folders;
  unrestricted run passed. Standard isolated pip build succeeded after a failed
  no-build-isolation attempt without setuptools in the fresh venv.
- Not run: live YouTube requests, actual FastEmbed model inference/download,
  Whisper model/audio inference, Ollama synthesis or remote CI at this checkpoint.

## Delivery blocker
GitHub CLI authentication succeeds as Q4ality, but `gh repo create Q4ality/KBfromYT
--private ...` was rejected by GitHub GraphQL: “Trade controls restricted owner
can't create repositories., Trade controls restricted creator can't create
repositories.” No remote repository was created and no push is possible to that
nonexistent destination. This is a GitHub account restriction, not a local test
failure. Resolve the restriction with GitHub before retrying the remote delivery.

### Existing SSH setup verified
The chat “Clone repo and configure SSH” identifies a repository-local SSH setup
under `C:/Users/q4ali/Documents/Codex/2026-07-23/l/work/ssh/`.
The standard user-profile `.ssh` directory is not used. The existing Ed25519 key
authenticates successfully to GitHub as Q4ality, and SSH `ls-remote` succeeds for
Q4ality/draft_room_intelligence. SSH `ls-remote` for Q4ality/KBfromYT returns
“Repository not found.” No private key content was displayed or copied.
This checkout now reuses that key and existing known_hosts with strict host checking
and has the intended SSH origin configured. Authentication is verified; remote
repository creation remains the outstanding blocker.
