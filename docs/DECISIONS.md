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
8. Initial synthetic fixtures verified the offline path. The subsequent live playlist
   imported 20 videos and built a multilingual index; see LIVE_PLAYLIST.md.
9. Use FastAPI and plain static HTML/CSS/JavaScript for local chat. Reuse the Python
   retrieval stack without a frontend build or agents framework. Keep chat optional.
10. Use the configured standard OpenAI Responses endpoint and `gpt-6-luna` with low
    reasoning. Account access was verified live. No automatic model substitution.
11. Interpret memory as three completed user/assistant pairs, bounded by input size.
    Keep it in process memory, with fresh retrieval for every question.
12. Force initial retrieval and cap the agent at four provider requests. Exact source
    validation and a separate model check precede display. Keep no-support, partial,
    verification failure and API failure distinct; never fall back to uncited facts.
13. Treat automated citation validity and model support judgments as separate from
    human entailment review. Benchmark results remain preliminary until reviewed.

Requirements from the prior discussion about phase review gates were proposals.
The current user request authorizes specs, planning and the first implementation
in one pass. Deferred research features remain explicit future milestones.
