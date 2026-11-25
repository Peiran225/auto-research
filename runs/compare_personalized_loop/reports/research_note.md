# Research note — mdp_uncertainty

Scope: this note uses only computations executed by this run and their audited claims. Literature, novelty and decision material from fixtures are excluded by construction.

## Two-step MDP: fixed vs. per-step parameter uncertainty (validation example)

**Status:** problem-clarification / falsification demonstration. It is a validation example with known values, not a novel contribution, and it does not show that all forms of MDP uncertainty are non-equivalent.

**Setting.** Horizon 2, actions a_t ∈ {0,1}, reward r_t = 1[a_t = θ_t] observed immediately, P(θ=1)=1/2. A: θ drawn once and fixed for the episode. B: θ_t drawn i.i.d. each step. Both scenarios use the same policy class: deterministic maps from the agent's own past actions and rewards to the next action (randomised policies cannot exceed the best deterministic one because the value is linear in the mixture weights). A history-independent (open-loop) class is the control.

**Computed values** (exhaustive enumeration of 8 history policies and 4 open-loop policies, exact rational arithmetic):

| quantity | value |
|---|---|
| V*_A, history policies | 3/2 |
| V*_B, history policies | 1 |
| V*_A, open-loop policies | 1 |
| V*_B, open-loop policies | 1 |

Independent cross-checks: belief-state DP for A gives 3/2; per-step DP for B gives 1. Optimal A policies: `∅->0; a1=0/r1=0->1; a1=0/r1=1->0`; `∅->1; a1=1/r1=0->0; a1=1/r1=1->1`.

**Short derivation.** In A the first reward reveals θ exactly (r_1 = 1 means θ = a_1, r_1 = 0 means θ = 1 − a_1), so a history policy earns 1/2 at step 1 and 1 at step 2. In B, θ_2 is independent of (a_1, r_1), so history carries no information about the future and every policy earns 1/2 per step. Without history, A also earns 1/2 per step. The difference therefore comes from the temporal dependence of the hidden parameter and the information the history carries about it, not from restricting B's memory: both scenarios were given the same history access.

Artifacts: `artifacts/act_18eb278081cc8be3/mdp_values.json` (values) and the per-policy CSV next to it. Reproduce: `python -m personal_research_agent.research.mdp_demo --out <dir>`.

## Audited claims

| claim | scope | status | proof status | evidence |
|---|---|---|---|---|
| For finite-horizon MDPs with a hidden reward parameter, fixed-per-episode and i.i.d.-per-step parameter uncertainty with the same marginal give the same optimal value under the same history-dependent policy class | general | refuted | disproved | lnk_18eb2780831f1ebf |
| In the binary-action family with immediately observed rewards r_t = 1[a_t = theta_t], V*_B(history) equals V*_A(open-loop), so the gap V*_A(history) - V*_B(history) equals the value of using history in A | general | unproven | draft | lnk_18eb278087dcbc73 |
| Under history-independent (open-loop) policies, fixed-per-episode and i.i.d.-per-step parameter uncertainty with the same marginal give the same optimal value | general | unproven | draft | lnk_18eb27808e81911e |

Finite-instance support never upgrades a general statement to proven; refutations rest on verified counterexamples that satisfy the statement's assumptions.

- `ev_18eb2780831b66cf` (counterexample, protocol proto_CAND-A@1): exact enumeration (H=2, p=1/2): V*_A(history)=3/2, V*_B(history)=1, V*_A(open-loop)=1 [artifact `artifacts/act_18eb278081cc8be3/mdp_values.json`]
- `ev_18eb278087d76046` (computation, protocol proto_CAND-B@1): claim voi_identity holds on all 12 instances of the finite family (H in [1, 2, 3], p in ['1/2', '1/3', '2/3', '1/4']); finite-instance support only [artifact `artifacts/act_18eb2780846906e3/counterexample_search_voi_identity.json`]
- `ev_18eb27808e7d532e` (computation, protocol proto_CAND-A@2): claim eq_open holds on all 12 instances of the finite family (H in [1, 2, 3], p in ['1/2', '1/3', '2/3', '1/4']); finite-instance support only [artifact `artifacts/act_18eb27808b87e172/counterexample_search_eq_open.json`]
