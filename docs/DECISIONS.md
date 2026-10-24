# Architecture review and decisions

1. Keep SQLite + optional Qdrant local from the discussion. Make lexical retrieval
   usable first so offline installation and evaluation do not require model downloads.
2. Do not assume hierarchy improves recall: keep direct chunk retrieval and measure
   the effect. Parent expansion may amplify irrelevant broad matches.
3. Start with source chapters and deterministic fallbacks. Neural chapterization,
   true embedding-based semantic chunking and abstractive summaries require model,
   language and cost decisions; v0.1 labels their absence explicitly.
4. Keep reranking replaceable. Lexical coverage is the baseline; a neural reranker
   needs quality evidence before adding its dependency/runtime cost.
5. Use evidence-only answers by default. Local Ollama synthesis is opt-in. No paid
   inference service, credentials or model download is silently enabled.
6. Caption absence alone enables Whisper fallback. IP blocking/network errors are
   surfaced rather than misreported as missing captions. Audio is downloaded only
   with explicit `--whisper`; ffmpeg must already be available.
7. Atomic per-video replacement plus a revision manifest prevents stale vectors
   from masquerading as current search results. A full index rebuild is acceptable
   for the first local version; incremental vector updates come later.
8. No live video was supplied. Synthetic fixtures verify the full local path; live
   YouTube reliability and downloaded-model quality are separate integration checks.

Requirements from the prior discussion about phase review gates were proposals.
The current user request authorizes specs, planning and the first implementation
in one pass. Deferred research features remain explicit future milestones.
