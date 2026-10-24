# Full-text embeddings and source-linked broad retrieval

Requested 2026-10-25. Status: implemented and verified; release recorded in Git history.

## Problem and implementation

The installed embedder truncates at 128 tokens. Existing chunks, chapters and videos
were embedded once each, hiding their tails from dense search. Broad questions also
lack useful overviews and can be misinterpreted as demanding an independent verdict.

- Index overlapping tokenizer-sized windows of every document, with exact character
  offsets and parent IDs. Aggregate window matches back to original documents and
  cite original chunks/segment timestamps. Version manifests and rebuild old indexes.
- Persist deterministic extractive video summaries: topics and representative original
  argument passages across the video, each linked to its chunk. Build library/playlist
  overview pages from these summaries. They are navigation, never fabricated quotes
  or claims of complete coverage. No paid summary generation is needed.
- For broad questions, retrieve multiple generic facets and diversify across videos.
  Expose coverage and bounded retrieval traces. Keep narrow/follow-up retrieval usable.
- Explain the videos' attributed positions without requiring them to independently
  prove a historical conclusion. Check attribution and exact quotes as before.
- Abstention describes insufficient retrieved evidence, not absence from all videos.

## Acceptance

- An embedding-tail regression retrieves a term beyond the old limit. Every stored
  window fits the actual tokenizer limit; overlap covers all non-whitespace text.
  Video/chapter windows cover their entire documents; stale index versions fail closed.
- Extractive summary passages resolve to original chunks and timestamps; no synthetic
  summary is accepted as a citation. Overview APIs preserve playlist membership and
  report actual coverage, with bounded pagination.
- Broad retrieval uses bounded multi-query search and returns diverse videos when
  relevant candidates exist. Missing evidence and rejected claims remain explicit.
- Required offline pytest/ruff checks, local index rebuild, representative local
  retrieval probes, and one narrowly scoped real answer to the reported failing
  question. Do not rerun the full paid benchmark.
- Update documentation, commit and push, leave the app running.

## Progress

- [x] Windowed index and migration.
- [x] Extractive overviews and broad retrieval.
- [x] Attribution policy, traces and scoped abstention.
- [x] Verification, live index migration and release documentation.
- [x] Changes prepared for commit/push; Git history records the release.

## Recorded verification

- 90 offline tests pass, including tokenizer-bound Unicode coverage, tail retrieval,
  distinct grouped source IDs, stale-format rejection, overview provenance, broad
  facets/diversity, repeated-intro filtering, playlist filtering and no-model previews.
- Ruff lint/format, dependency consistency and the offline README walkthrough pass.
- Existing 20-video corpus rebuilt locally: 1,835 original documents map to 9,533
  overlapping embedding windows. Actual token limit and maximum window size are both
  128. Original 1,416 chunks/segment IDs/timestamps are unchanged. Twenty extractive
  video overviews contain 120 original source-linked passages.
- Local Russian/English probes exposed repeated introductions occupying results.
  Overview anchors now have their own candidate path and repeated openings collapse.
  The local Russian probe surfaced the explicit position passage `YRpYiiF3Bmw:k2`.
- Two focused real-answer checks used the original failing Russian question, not a
  full benchmark. Manual review caught a conditional/sarcastic passage in the first
  answer; policy/checking now explicitly preserve such qualifications and separate
  compound assertions. The final answer reports an attributed position with a valid
  original citation, status partial, 5 retrieved passages from 4/20 videos, 4 provider
  requests, 9,955 input / 912 output tokens, and 20,359 ms latency.
- The partial label and limitations remain visible; no claim of an independent
  historical verdict or a complete 20-video review. Model-assisted entailment still
  requires human review. This single regression is not a general quality score.
- Real UI displays source-linked overviews/timestamps and index window counts without
  console errors. Full reports/screenshots remain under ignored `data/live/`.
