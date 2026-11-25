# Research note — hierarchical_world_model

Scope: this note uses only computations executed by this run and their audited claims. Literature, novelty and decision material from fixtures are excluded by construction.

## Toy check: nested solution dependence vs. alternating updates (clarification pilot)

**Status:** clarification pilot on a quadratic toy problem; it is not evidence about world models.

With y*(x) = a x / (1+λ) (a=1.0, λ=0.5, c=1.0), nested training converges to x = 1.615385, alternating two-loss training to x = 1.000000; upper-objective gap 0.547009. Numerical runs match the closed forms: True. So 'multiple losses with alternating updates' and 'nested solution dependence' are different problems and must be distinguished before any world-model claim. Artifact: `artifacts/act_18eb277ff1bd13ec/nested_vs_alternating.json`.

## Audited claims

| claim | scope | status | proof status | evidence |
|---|---|---|---|---|
| On a two-level quadratic instance, nested (solution-dependent) training and alternating two-loss training reach different solutions, so the two readings of multi-level optimisation are distinct problems | finite_instance | supported | draft | lnk_18eb277ff2d19489 |
| Alternating multi-loss updates reach the same solution as nested training, so nested optimisation adds nothing | general | refuted | disproved | lnk_18eb277ff2d58137 |

Finite-instance support never upgrades a general statement to proven; refutations rest on verified counterexamples that satisfy the statement's assumptions.

- `ev_18eb277ff2ce0e09` (counterexample, protocol proto_W1@1): toy quadratic (a=1, lam=0.5, c=1): nested x*=1.615385, alternating x=1.000000, upper-objective gap=0.547009; numerical runs match closed forms: True [artifact `artifacts/act_18eb277ff1bd13ec/nested_vs_alternating.json`]
