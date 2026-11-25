# Goal
- Hypothesis under test: a history-dependent policy can exceed the open-loop baseline value 1 in scenario A
- Falsification: no correct candidate scores above 1
- Edit only `src/program.py`. It must write `policy.json` with the fixed protocol fields and a policy mapping each reachable history key ("" then "a1:r1", "a1:r1|a2:r2", ...) to an action in {0,1}.
- Maximize `combined_score` = exact expected return in scenario A (horizon 2, P(theta=1)=1/2), computed by the evaluator from the policy; `correct.json` must report `correct: true`.
- Each evaluation takes under one second on one CPU core.
- Implement ONE policy per evaluation. Do NOT run sweeps or multiple variants inside one program.

# Constraints
- The program must not write score, value, return or metrics fields; the evaluator computes the score.
- The protocol fields (scenario, horizon, p) are frozen.

# Rubrics
- `beats_baseline`: combined_score > 1.0
- `evidence`: every evaluated candidate produces `metrics.json` and `correct.json`.
