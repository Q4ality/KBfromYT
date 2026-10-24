# 05 — evaluation and delivery
Goal: regression harness and reproducible repository.
Scope/modules: evaluation.py, tests/, examples/, CI and README.
Contracts: benchmark query with gold video/time intervals.
Approach: unique gold matching; Recall@k/MRR/NDCG and separate abstention score.
Non-goals: asserting quality from synthetic data.
Dependencies: phases 01–04.
Tests: hand-computed metrics, duplicate relevant hits, no-answer and invalid gold cases;
full CLI fixture lifecycle in a fresh temp database; lint and editable install.
Acceptance: tests/lint pass, offline walkthrough works, main is committed and remote
SHA matches local. Report unrun external/model integrations and remaining roadmap.
