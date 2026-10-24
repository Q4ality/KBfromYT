# 03 — indexing
Goal: three resolution lexical and optional dense indexes.
Scope/modules: store.py, semantic.py. Contracts: Document, embedding protocol.
Approach: FTS5 transactional mirror; FastEmbed adapter; UUID Qdrant point IDs;
revision/model manifest committed after successful full rebuild.
Non-goals: distributed indexing and incremental vector updates.
Dependencies: phases 01–02; optional semantic extra for real embeddings.
Tests: lexical replacement removes obsolete text, Qdrant local round-trip with
deterministic test vectors, stale/missing manifests fail closed.
Acceptance: video/chapter/chunk documents searchable and stale dense index rejected.
