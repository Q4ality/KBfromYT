# 04 — retrieval and answering
Goal: source-grounded evidence across videos.
Scope/modules: retrieval.py, answering.py, cli.py. Contracts: Evidence and cited claims.
Approach: independent level rankings; RRF; parent expansion; lexical coverage bonus;
same-chapter neighbor context; evidence default, optional Ollama synthesis.
Non-goals: neural reranking and guaranteed entailment verification.
Dependencies: phases 01–03 and optional index.
Tests: direct detail recall, parent expansion, bounded context, unknown/empty queries,
timestamp links, malformed model JSON, missing and unknown citation IDs.
Acceptance: returned evidence maps to raw segments, unmatched lexical query abstains,
and generated claims without valid citations are rejected.
