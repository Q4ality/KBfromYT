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
14. Remove only recognized non-speech annotations from derived caption text. Preserve
    unknown bracketed phrases and immutable raw inputs. Version the transformation
    and rebuild indexes after cleanup; do not silently alter source timestamps.
15. Persist local app state in a separate SQLite database. Saved source envelopes
    survive index changes; reusing a conversation still requires fresh retrieval.
    Browser owner cookies scope history, with no cloud synchronization in this phase.
16. Coordinate UI ingestion with chat through a shared operation lock and corpus
    lock. Reuse the resident embedding/index client for rebuilds. Durable job status
    exposes partial and interrupted imports; index failures require explicit repair.
17. Embedding context limits must be enforced before indexing. Index all overlapping
    source windows and group matches by original document; never silently embed only
    the opening of a video/chapter/chunk. Version the index representation separately.
18. Begin with deterministic extractive overviews linked to raw evidence. Select
    representative passages across the video rather than introducing paid generated
    summaries or unverified argument labels. Broad questions use generic facets and
    source diversity, with explicit limits and measured coverage.
19. Treat attributed source claims as claims about a speaker's position. Preserve
    independent support checking without demanding an external historical verdict
    before reporting that position. Abstention is scoped to retrieved excerpts.
20. Cross-video diversity must include content diversity. Search overview anchors
    independently and collapse repeated openings, so identical introductions do not
    occupy the evidence budget merely because they occur in different videos.

21. Keep candidate retrieval scores separate from human-reviewed answer quality.
    Reserve related question families together and record source/configuration
    versions. The prior 20-case results remain historical, not a current quality claim.
22. Scope belongs to a conversation and resolves for each new turn. Enforce it
    through retrieval and citation registration, not only the model prompt.
23. Persist an owner/request identity before provider calls; commit the recovered
    result with the saved turn. Replay saved results after connection loss, while
    treating interrupted external provider work as uncertain rather than retrying
    it automatically.

24. Verify the source/model/format and exact expected point IDs before reusing an
    unchanged semantic index during UI maintenance. Report preparation and embedding
    batch progress separately from import counts. Clear old points through Qdrant's
    public API before recreating collections, because local directory removal can
    fail on Windows. Remove positively identified obsolete IDs without re-embedding
    verified current windows; missing IDs still require a rebuild.

Requirements from the prior discussion about phase review gates were proposals.
The current user request authorizes specs, planning and the first implementation
in one pass. Deferred research features remain explicit future milestones.
