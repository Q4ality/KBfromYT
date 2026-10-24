# 02 — processing
Goal: traceable Video → Chapter → Chunk → Segment hierarchy.
Scope/modules: processing.py and Pydantic contracts.
Approach: normalize whitespace/HTML; source chapter starts partition segments;
otherwise use time windows. Bounded chunks split at sentence ends or lexical drift.
Non-goals: neural topic labeling and embedding-based semantic boundary detection.
Dependencies: phase 01 contracts.
Tests: every segment appears in a chunk, no chunk crosses chapters, source intervals,
blank/duplicate captions, huge individual segments and invalid chapter starts.
Acceptance: deterministic IDs and source membership; original raw text remains stored.
