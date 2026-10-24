# Repository instructions

Read docs/PRODUCT_SPEC.md, docs/ARCHITECTURE.md, docs/DATA_MODEL.md,
docs/RETRIEVAL.md and docs/EVALUATION.md before architectural changes.
Keep an executable plan in plans/ for substantial work, with acceptance criteria
and recorded verification. Update the plan as scope changes.

Use Python 3.12+, typed interfaces, Pydantic contracts, pytest and ruff.
Keep ingestion, processing, persistence, indexing and retrieval decoupled.
Preserve raw subtitle text and source timestamps. Derived evidence must retain
segment IDs. Never present generated summaries as quotations or invent citations.
Keep vector backends replaceable. Record architectural deviations in docs/DECISIONS.md.
Keep credentials, downloaded transcripts, models and databases out of Git.

Validate with `python -m pytest` and `python -m ruff check .` in the project venv.
Run the offline README walkthrough after changing CLI behavior. Network/model
checks are optional integrations; report whether they actually ran.
