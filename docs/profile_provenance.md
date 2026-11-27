# Profile provenance (profiles/peiran.yaml)

| Field | Source | Status | Needs calibration by |
|---|---|---|---|
| Researcher name and directions (optimization, bilevel, nonconvex minimax, convergence analysis, optimization for ML, multimodal learning) | User context given with CODEX_IMPLEMENTATION_PLAN v1.1 (2026-11-24) | stated by user, not checked against full text (`verified: false`) | reading the papers' full text, or user confirmation |
| Supporting titles for bilevel / minimax / convergence | `research/profile/scholar_papers.json` (Google Scholar listing fetched 2026-11-20; titles, venues, years; 9 arXiv abstracts) | metadata only | full-text reading |
| Multimodal learning | User context only | no publication metadata found in the Scholar listing | user confirmation |
| Recent explorations (hierarchical world models, MDP uncertainty, personalized research agents) | User context | stated by user | — |
| Taste rules TR1–TR4 | Inferred from the discussion that produced the plan (`inferred_from_discussion`) | conditional, not trained, not confirmed rule by rule | user feedback on concrete decisions |

Not stored as preferences: one-off deadline decisions (fewer experiments, shorter paper).
Compute resources are a run-config matter (`configs/*.yaml`); no GPU count is inferred from past
conversations.
