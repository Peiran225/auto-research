"""Build the offline fixtures (synthetic papers and fixture model responses).

Everything written here is SYNTHETIC TEST DATA. It exists only to exercise the decision flow
offline; it is never a literature finding, a novelty judgement or a research result.
Re-run after changing a template's questions:  python tests/fixtures/build_fixtures.py
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SYN = "[SYNTHETIC FIXTURE] "


# ----------------------------------------------------------------------------- answer helpers
def given(q, s):
    return {"question_id": q, "statement": s, "epistemic_status": "fact", "basis_type": "input_given"}


def reported(q, s, pid, loc, scope="partial_text"):
    return {"question_id": q, "statement": s, "epistemic_status": "fact", "basis_type": "source_report",
            "source_refs": [{"source_id": pid, "locator": loc, "read_scope": scope}]}


def observed(q, s, ref, loc):
    return {"question_id": q, "statement": s, "epistemic_status": "fact", "basis_type": "tool_observation",
            "source_refs": [{"source_id": ref, "locator": loc}]}


def infer(q, s, premises=(), src=None, scope=None):
    a = {"question_id": q, "statement": s, "epistemic_status": "inference", "premise_ids": list(premises)}
    if src:
        a["source_refs"] = [{"source_id": src[0], "locator": src[1], "read_scope": "partial_text"}]
    if scope:
        a["scope"] = scope
    return a


def hyp(q, s, pred, fals):
    return {"question_id": q, "statement": s, "epistemic_status": "hypothesis", "prediction": pred, "falsification": fals}


def unk(q, missing):
    return {"question_id": q, "statement": None, "epistemic_status": "unknown", "missing_information": missing}


def write(task: str, key: str, answers: list, payload: dict) -> None:
    d = ROOT / "llm" / task
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{key}.json").write_text(json.dumps({"answers": answers, "payload": payload}, indent=2, ensure_ascii=False) + "\n",
                                   encoding="utf-8")


def asm(key, dim, state, judgment, refs, why, stype="candidate"):
    return {"subject_key": key, "subject_type": stype, "dimension": dim, "state": state, "judgment": judgment,
            "evidence_refs": refs, "rationale": why}


# ============================================================================= MDP uncertainty
T = "mdp_uncertainty"
PB, PR, PI = "paper_fixture_mdp_bayes_adaptive", "paper_fixture_mdp_robust_rectangular", "paper_fixture_mdp_iid_marginalization"


def mdp_literature():
    papers = [
        {"canonical_id": "fixture:mdp_bayes_adaptive", "title": SYN + "Value of information in Bayes-adaptive MDPs",
         "authors": ["Synthetic Author A"], "year": 2026, "text_status": "partial_text", "version": "fixture-v1",
         "keywords": ["bayes", "adaptive", "parameter", "uncertainty", "value", "information", "fixed", "episode", "belief"],
         "abstract": SYN + "Persistent parameter uncertainty and the value of history.",
         "units": {"§1": SYN + "Problem. An agent faces an MDP whose reward parameter theta is unknown but fixed within an episode. It maintains a posterior over theta and acts on the belief state (Bayes-adaptive MDP).",
                   "§2": SYN + "Proposition 1. With a parameter fixed per episode, history-dependent policies can exceed history-independent policies; the excess equals the value of the information that past observations carry about theta. Assumptions: finite horizon, observed rewards, a prior shared by all policies.",
                   "§3": SYN + "Computation. Small finite instances are solved exactly by enumerating deterministic history policies; the cost grows doubly exponentially in the horizon."}},
        {"canonical_id": "fixture:mdp_robust_rectangular", "title": SYN + "Rectangular robust MDPs as per-step games",
         "authors": ["Synthetic Author B"], "year": 2025, "text_status": "partial_text", "version": "fixture-v1",
         "keywords": ["robust", "rectangular", "uncertainty", "set", "minimax", "adversarial", "game"],
         "abstract": SYN + "Worst-case treatment of model uncertainty.",
         "units": {"§1": SYN + "Robust MDPs choose a policy against the worst transition model in an uncertainty set.",
                   "§2": SYN + "Theorem 2. Under (s,a)-rectangular uncertainty sets the robust MDP equals a zero-sum game in which nature picks the model adversarially at every step; the robust value is a minimax value.",
                   "§3": SYN + "Limitation. Without rectangularity the per-step game formulation does not hold and the problem can be computationally hard."}},
        {"canonical_id": "fixture:mdp_iid_marginalization", "title": SYN + "Marginalising per-step i.i.d. parameters",
         "authors": ["Synthetic Author C"], "year": 2024, "text_status": "partial_text", "version": "fixture-v1",
         "keywords": ["iid", "per-step", "independent", "noise", "marginal", "transition", "aleatoric"],
         "abstract": SYN + "Per-step randomness integrated into the dynamics.",
         "units": {"§1": SYN + "When the parameter is redrawn independently at every step it can be integrated out of the dynamics.",
                   "§2": SYN + "Observation 3. Per-step i.i.d. parameters yield an ordinary MDP with averaged transitions and rewards; past observations carry no information about future parameters.",
                   "§3": SYN + "Scope. The statement concerns i.i.d. redraws only; it says nothing about parameters that persist over time."}},
    ]
    (ROOT / "literature").mkdir(exist_ok=True)
    (ROOT / "literature" / f"{T}.json").write_text(json.dumps(papers, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


CLAIM_A1 = {"id": "C1", "scope": "general", "check_key": "eq_history",
            "statement": "For finite-horizon MDPs with a hidden reward parameter, fixed-per-episode and i.i.d.-per-step parameter uncertainty with the same marginal give the same optimal value under the same history-dependent policy class"}
CLAIM_A2 = {"id": "C1", "scope": "general", "check_key": "eq_open",
            "statement": "Under history-independent (open-loop) policies, fixed-per-episode and i.i.d.-per-step parameter uncertainty with the same marginal give the same optimal value"}
CLAIM_B1 = {"id": "C1", "scope": "general", "check_key": "voi_identity",
            "statement": "In the binary-action family with immediately observed rewards r_t = 1[a_t = theta_t], V*_B(history) equals V*_A(open-loop), so the gap V*_A(history) - V*_B(history) equals the value of using history in A"}
CLAIM_B2 = {"id": "C2", "scope": "general", "check_key": "b_no_history_gain",
            "statement": "Under i.i.d. per-step parameters, history-dependent policies gain nothing over open-loop policies"}


def mdp_llm():
    write(T, "clarify_problem", [
        given("q1", "The idea names 'different forms of uncertainty' in MDPs and asks whether they are equivalent. It fixes neither the uncertainty object, its temporal dependence, the information available to the policy, the decision objective, the policy class, nor the notion of equivalence."),
        infer("q2", "Three terms change the problem: the uncertainty form (persistent parameter, per-step noise, adversarial set), 'equivalent' (equal optimal value, same optimal policy, or the same decision problem) and the policy class (history-dependent or open-loop).", ["q1"]),
        infer("q3", "For interpretation I1 the variables are the hidden parameter theta, actions a_t and rewards r_t = 1[a_t = theta_t]; the observable information is the agent's own history. Working assumption (not given by the input): both scenarios use the same history-dependent policy class.", ["q2"]),
        given("q4", "The input does not state the target conclusion; branches are kept: equivalence conditions (I1, I2) or a counterexample to the broad reading (I3)."),
        hyp("q5", "A small instance where fixed and per-step parameters give different optimal values under the same policy class would refute the broad equivalence reading.",
            "exact enumeration of a two-step binary instance gives unequal optimal values",
            "equal optimal values on every small instance of the family"),
        unk("q6", "The intended equivalence definition (value, policy or problem). A working assumption (equal optimal value) is used for pilots only; formal verification waits for this definition."),
        infer("q7", "Search terms: Bayes-adaptive MDP / value of information (persistent parameter), rectangular robust uncertainty sets (worst case), per-step i.i.d. marginalisation (possible refutation of equivalence), minimax games (link to the user's methods).", ["q2"]),
    ], {
        "interpretations": [
            {"id": "I1", "description": "Same hidden reward parameter, fixed per episode (A) vs redrawn i.i.d. per step (B); compare optimal values under the same history-dependent policy class.",
             "objects": ["hidden parameter theta (uncertainty_object)", "history-dependent policy"], "variables": ["theta", "a_t", "r_t"],
             "information_conditions": ["information_available_to_policy: own actions and rewards, identical in A and B", "temporal_dependence: fixed vs i.i.d."],
             "working_assumptions": ["policy_class: deterministic history-dependent (randomised cannot do better)", "decision_objective: expected return"],
             "target_conclusion": "equivalence_conditions_or_counterexample", "status": "kept"},
            {"id": "I2", "description": "Bayesian (expected) vs robust (worst-case) treatment of the same uncertainty set.",
             "objects": ["uncertainty set", "prior"], "information_conditions": ["decision_objective differs: expectation vs worst case"],
             "target_conclusion": "equivalence_conditions", "status": "open"},
            {"id": "I3", "description": "All forms of MDP uncertainty are equivalent.", "status": "rejected_too_broad",
             "rejection_reason": "no uncertainty object, policy class or equivalence_definition is fixed; not testable as stated"}],
        "concepts": [
            {"canonical_name": "Bayes-adaptive MDP", "aliases": ["belief MDP"], "role": "model of persistent parameter uncertainty", "search_terms": ["bayes adaptive"]},
            {"canonical_name": "robust MDP", "aliases": ["rectangular uncertainty set"], "role": "worst-case treatment of model uncertainty", "search_terms": ["robust rectangular"]},
            {"canonical_name": "minimax optimization", "aliases": ["zero-sum game"], "role": "solution concept for rectangular robust MDPs", "search_terms": ["minimax"]},
            {"canonical_name": "value of information", "aliases": [], "role": "quantity that separates fixed from i.i.d. parameters", "search_terms": ["value information"]}],
        "unknowns": [
            {"key": "equivalence_definition", "question": "Which equivalence notion is intended: equal optimal value, same optimal policy, or the same decision problem?",
             "affects": ["CAND-A", "CAND-B"], "importance": "high", "available_checks": [],
             "missing_material": "the user's intended definition; pilots use 'equal optimal value' as an explicit working assumption"},
            {"key": "decision_objective", "question": "Is the comparison under expected return or worst-case return?", "affects": [], "importance": "medium",
             "available_checks": [], "missing_material": "user intent"}],
        "metrics_status": "undecided",
        "search_queries": [{"query": "bayes adaptive parameter uncertainty value information", "purpose": "nearest"},
                           {"query": "robust rectangular uncertainty set minimax", "purpose": "bottleneck"},
                           {"query": "iid per-step independent marginal transition", "purpose": "refuting"},
                           {"query": "minimax adversarial game robust", "purpose": "user_method_link"}]})

    for pid, main, obs in [
        (PB, "§2", "History-dependent policies can exceed history-independent ones when the parameter is fixed per episode; the excess is attributed to the information history carries about theta (Proposition 1, synthetic)."),
        (PR, "§2", "Under (s,a)-rectangular sets the robust MDP equals a per-step zero-sum game against nature; robust value = minimax value (Theorem 2, synthetic)."),
        (PI, "§2", "Per-step i.i.d. parameters can be integrated out; past observations carry no information about future parameters (Observation 3, synthetic)."),
    ]:
        write(T, f"read_paper__{pid}", [
            reported("q1", "The paper's problem is stated in §1 of the retrieved text.", pid, "§1"),
            reported("q2", "The key statement, its variables and assumptions are in §2.", pid, "§2"),
            reported("q3", "The claimed contribution is the statement in §2; it is supported by a proposition/theorem, not by experiments.", pid, "§2"),
            reported("q4", "The statement's scope and limitations are given in §3; conditions outside them cannot be carried over directly.", pid, "§3"),
            unk("q5", "No experiments appear in the retrieved units §1-§3; whether the paper has experiments is unknown (read scope: partial text)."),
            infer("q6", "The statement bears on the candidates as background or as a nearest neighbour; links are made per candidate in later checks.", ["q2"]),
            reported("q7", "The paper states its own limitation in §3; any further limitation would be an inference.", pid, "§3"),
            infer("q8", "Reading the full proof section (not retrieved) would settle whether the assumptions can be weakened.", ["q4"]),
        ], {"paper_id": pid, "reading_status": "partial",
            "evidence": [{"locator": "§1", "observation": "Problem setting as stated in §1 (synthetic)."},
                         {"locator": main, "observation": obs},
                         {"locator": "§3", "observation": "Scope / limitation stated in §3 (synthetic)."}],
            "remaining_questions": ["proof details (not in the retrieved units)"]})

    write(T, "map_field", [
        reported("q1", "Three problems appear, each in one synthetic source: when persistent parameters make history valuable (Bayes-adaptive), when robust formulations reduce to per-step games, and when per-step randomness can be marginalised.", PB, "§2"),
        infer("q2", "The sources state propositions rather than benchmarks; metrics are optimal values under a fixed policy class, which matches an equivalence question.", ["q1"]),
        infer("q3", "No source contradicts another; each problem rests on a single (synthetic) source, so none counts as consensus.", ["q1"]),
        infer("q4", "The idea maps to the first and third problems (persistent vs i.i.d. parameters); the second matters only for interpretation I2.", ["q1"]),
    ], {"field_problems": [
        {"id": "FP1", "problem": "When does persistent parameter uncertainty make history valuable?", "evidence_refs": [f"{PB}#§2"], "metrics": ["optimal value under a fixed policy class"], "baselines": ["open-loop policy"], "status": "single_source"},
        {"id": "FP2", "problem": "When do robust (worst-case) formulations reduce to per-step games?", "evidence_refs": [f"{PR}#§2"], "metrics": ["robust value"], "baselines": [], "status": "single_source"},
        {"id": "FP3", "problem": "When can per-step randomness be marginalised into an ordinary MDP?", "evidence_refs": [f"{PI}#§2"], "metrics": ["optimal value"], "baselines": [], "status": "single_source"}],
        "idea_maps_to": ["FP1", "FP3"], "missing_for_link": None})

    write(T, "link_background", [
        given("q1", "The profile states bilevel optimization, nonconvex minimax optimization, convergence analysis and optimization for ML (stated by the user, not verified against full text)."),
        reported("q2", "A bottleneck in the field map is deciding when history carries decision-relevant information (single synthetic source).", PB, "§2"),
        infer("q3", "Minimax structure maps onto rectangular robust MDPs: nature's per-step model choice is the inner maximisation, the policy the outer minimisation.", src=(PR, "§2")),
        infer("q4", "The mapping needs (s,a)-rectangularity; without it the per-step game fails.", src=(PR, "§3")),
        hyp("q5", "If the link holds, the robust value equals a minimax value computable step by step.",
            "per-step game value equals robust value on rectangular instances", "a rectangular instance where they differ"),
        infer("q6", "The source already states the minimax link for rectangular sets, so this link may be covered rather than new.", src=(PR, "§2")),
        infer("q7", "The value-of-information view of Bayes-adaptive MDPs is not in the profile and must be learned; its learning cost is recorded apart from its scientific value.", ["q1"]),
        given("q8", "Taste rules TR1-TR4 are inferred from discussion and not confirmed; they act only as tie-breakers under their stated conditions."),
    ], {"correspondences": [
        {"profile_item": "nonconvex minimax optimization", "mechanism_map": "outer policy minimisation vs nature's per-step maximisation in rectangular robust MDPs", "conditions": ["(s,a)-rectangularity"], "status": "supported", "evidence_refs": [f"{PR}#§2"]},
        {"profile_item": "bilevel optimization", "mechanism_map": "outer policy optimisation over an inner belief update in Bayes-adaptive planning", "conditions": ["belief update is a solution map of an inner problem"], "status": "hypothesis", "evidence_refs": []}],
        "assessments": [
            asm("value of information", "field_importance", "known", "high", [f"{PB}#§2"], "core quantity of FP1 (synthetic source)", "concept"),
            asm("robust MDP", "field_importance", "known", "medium", [f"{PR}#§2"], "relevant only for interpretation I2", "concept"),
            asm("minimax optimization", "field_importance", "known", "medium", [f"{PR}#§2"], "solution concept for FP2", "concept")],
        "learning_tasks": [{"topic": "value of information / Bayes-adaptive MDPs", "importance": "high", "affects": ["CAND-B"], "why": "core quantity of FP1; no matching profile record"}],
        "taste_rules_applied": []})

    write(T, "propose_candidates", [
        infer("q1", "Open questions: whether the broad equivalence survives a small counterexample, whether the value gap is exactly the value of history, and whether the minimax link adds anything beyond the stated theorem.", src=(PB, "§2")),
        infer("q2", "Each candidate below lists its hypothesis, mechanism, nearest neighbours, a falsifiable prediction, the cheapest check and an abandon condition.", ["q1"]),
        hyp("q3", "All three candidates are hypotheses until checked.", "the cheapest checks decide at least one of them", "all checks remain inconclusive within budget"),
        infer("q4", "CAND-C uses a different mechanism (worst-case objective) and is kept as an alternative; no further alternative has an evidence-based reason.", src=(PR, "§2")),
    ], {"candidates": [
        {"key": "CAND-A", "title": "Equivalence of fixed and i.i.d. parameter uncertainty under one history-dependent policy class",
         "problem_scope": "finite-horizon MDPs with a hidden reward parameter; same marginal; same history-dependent policy class",
         "hypothesis": CLAIM_A1["statement"], "mechanism": "marginalising the parameter gives the same decision problem",
         "increment": "a clean equivalence statement linking FP1 and FP3", "nearest_neighbors": [PI, PB], "claims": [CLAIM_A1],
         "validation_protocol": {"equivalence": "equal optimal value (working assumption)"},
         "abandon_conditions": ["an exact counterexample satisfying the assumptions"], "research_branch": "theoretical",
         "cheapest_check": {"action_type": "cpu_pilot", "inputs": {"pilot_id": "mdp_exact_enumeration"}}},
        {"key": "CAND-B", "title": "The value gap between fixed and i.i.d. parameters is the value of history",
         "problem_scope": "binary actions, rewards r_t = 1[a_t = theta_t] observed immediately, any horizon and prior",
         "hypothesis": CLAIM_B1["statement"], "mechanism": "history informs future decisions only when the parameter persists",
         "increment": "an exact characterisation of when the two uncertainty forms differ", "nearest_neighbors": [PB, PI],
         "claims": [CLAIM_B1, CLAIM_B2], "validation_protocol": {"equivalence": "equal optimal value (working assumption)"},
         "abandon_conditions": ["an instance in the family where V*_B(history) differs from V*_A(open-loop)"],
         "research_branch": "theoretical",
         "cheapest_check": {"action_type": "counterexample_search", "inputs": {"pilot_id": "mdp_counterexample", "claim": "voi_identity"}}},
        {"key": "CAND-C", "title": "Rectangular robust MDPs as minimax games (link to the user's minimax work)",
         "problem_scope": "(s,a)-rectangular robust MDPs", "hypothesis": "Robust value under rectangular sets equals a per-step minimax game value",
         "mechanism": "nature's per-step adversarial choice", "increment": "re-use of minimax analysis tools", "nearest_neighbors": [PR],
         "claims": [{"id": "C1", "scope": "general", "statement": "Robust value under (s,a)-rectangular sets equals a per-step minimax game value"}],
         "validation_protocol": {}, "abandon_conditions": ["the statement is already established"], "research_branch": "theoretical",
         "cheapest_check": {"action_type": "check_candidate", "inputs": {}}}],
        "no_alternative_reason": None,
        "unknowns": [
            {"key": "cex_A", "question": "Does a small exact instance refute CAND-A C1?", "affects": ["CAND-A"], "importance": "high",
             "available_checks": [{"action_type": "cpu_pilot", "purpose": "preliminary_check", "inputs": {"pilot_id": "mdp_exact_enumeration"},
                                   "cost": {"pilots": 1}, "can_disqualify": True,
                                   "branches": [{"if": "optimal values differ", "then": "CAND-A C1 refuted"}, {"if": "equal", "then": "finite support only"}]}]},
            {"key": "voi_B", "question": "Does V*_B(history) = V*_A(open-loop) hold across the finite family?", "affects": ["CAND-B"], "importance": "high",
             "available_checks": [{"action_type": "counterexample_search", "purpose": "preliminary_check",
                                   "inputs": {"pilot_id": "mdp_counterexample", "claim": "voi_identity"}, "cost": {"pilots": 1}, "can_disqualify": True,
                                   "branches": [{"if": "counterexample", "then": "CAND-B C1 refuted"}, {"if": "holds", "then": "finite support; proof still needed"}]}]},
            {"key": "proof_B", "question": "Do the proof obligations for CAND-B C1 go through beyond the finite family?", "affects": ["CAND-B"], "importance": "medium",
             "available_checks": [{"action_type": "check_theory", "purpose": "preliminary_check", "inputs": {"review": "derivation"}, "cost": {"llm_calls": 1}}]},
            {"key": "cex_A2", "question": "Does the open-loop restriction of CAND-A hold on the finite family?", "affects": ["CAND-A"], "importance": "medium",
             "available_checks": [{"action_type": "counterexample_search", "purpose": "preliminary_check",
                                   "inputs": {"pilot_id": "mdp_counterexample", "claim": "eq_open"}, "cost": {"pilots": 1}, "can_disqualify": True}]},
            {"key": "novelty_A", "question": "Is the (narrowed) CAND-A statement already known in the literature?", "affects": ["CAND-A"], "importance": "high",
             "available_checks": [{"action_type": "search_literature", "purpose": "information_gathering",
                                   "inputs": {"query": "fixed versus iid parameter uncertainty open-loop policy equivalence", "requires_live": True, "purpose": "nearest"},
                                   "cost": {"search_queries": 1}}]},
            {"key": "novelty_B", "question": "Is the value-of-history characterisation already known?", "affects": ["CAND-B"], "importance": "high",
             "available_checks": [{"action_type": "search_literature", "purpose": "information_gathering",
                                   "inputs": {"query": "value of information history Bayes-adaptive versus iid parameters", "requires_live": True, "purpose": "nearest"},
                                   "cost": {"search_queries": 1}}]}]})

    common_check = lambda q6: [
        reported("q1", "Nearest synthetic sources: Proposition 1 (persistent parameters) and Observation 3 (i.i.d. marginalisation).", PB, "§2"),
        reported("q2", "The i.i.d. source covers marginalisation only; it says nothing about persistent parameters.", PI, "§3"),
        infer("q3", "The difference is not a renaming: it concerns which information the policy can exploit.", src=(PB, "§2")),
        unk("q4", "Only three synthetic fixture papers were 'searched'; whether the statement is new needs a live literature search."),
        infer("q5", "The candidate depends on the working equivalence definition (equal optimal value), which is not yet confirmed by the user.", ["q4"]),
        q6,
        infer("q7", "The cheapest decisive check is an exact enumeration / finite-family counterexample search.", ["q6"]),
        infer("q8", "Keep the claim pending that check; do not widen its scope.", ["q7"]),
    ]
    write(T, "check_candidate__rev_CAND-A_v1",
          common_check({"question_id": "q6", "statement": "A counterexample is plausible because history reveals a persistent parameter but not an i.i.d. one; it has not been constructed yet.",
                        "epistemic_status": "hypothesis", "prediction": "two-step binary instance gives unequal optimal values",
                        "falsification": "equal optimal values on all small instances"}),
          {"candidate_key": "CAND-A", "claim_checks": [{"claim_id": "C1", "status": "unresolved", "source_refs": [f"{PI}#§2", f"{PB}#§2"],
                                                         "conditions": ["same history-dependent policy class"], "counterexample_status": "construction_to_check",
                                                         "checked_scope": "three synthetic fixture papers; no live search"}],
           "assessments": [asm("CAND-A", "scientific_value", "known", "medium", [f"{PB}#§1"], "would connect FP1 and FP3 if true"),
                           asm("CAND-A", "novelty", "unknown", None, [], "no live search was run; unknown is not low"),
                           asm("CAND-A", "feasibility", "known", "high", [f"{PB}#§3"], "small instances are solved exactly by enumeration")]})
    write(T, "check_candidate__rev_CAND-B_v1",
          common_check(hyp("q6", "No counterexample to C1 is known; the finite family has not been checked.", "C1 holds on every instance of the family", "an instance where V*_B(history) differs from V*_A(open-loop)")),
          {"candidate_key": "CAND-B", "claim_checks": [
              {"claim_id": "C1", "status": "unresolved", "source_refs": [f"{PB}#§2"], "conditions": ["rewards reveal theta after one step"],
               "counterexample_status": "insufficient_evidence", "checked_scope": "three synthetic fixture papers; no live search"},
              {"claim_id": "C2", "status": "covered", "source_refs": [f"{PI}#§2"], "conditions": ["i.i.d. redraws"],
               "counterexample_status": "none_found_in_scope", "checked_scope": "three synthetic fixture papers"}],
           "assessments": [asm("CAND-B", "scientific_value", "known", "high", [f"{PB}#§2"], "addresses FP1 directly"),
                           asm("CAND-B", "novelty", "unknown", None, [], "C2 appears covered; C1 needs a live search"),
                           asm("CAND-B", "feasibility", "known", "medium", [f"{PB}#§3"], "finite family is cheap; a general proof is harder")]})
    write(T, "check_candidate__rev_CAND-C_v1", [
        reported("q1", "Theorem 2 (synthetic) states the rectangular robust MDP / per-step game equivalence.", PR, "§2"),
        reported("q2", "Under the same rectangularity assumption the source already covers the candidate's statement.", PR, "§2"),
        infer("q3", "The candidate restates Theorem 2 in minimax language; the difference is terminological.", src=(PR, "§2")),
        infer("q4", "Within the searched (synthetic) scope no substantive difference remains.", ["q3"]),
        reported("q5", "The non-rectangular case is outside the statement and is flagged as hard.", PR, "§3"),
        infer("q6", "No counterexample is needed: the claim is covered, not refuted.", ["q2"]),
        infer("q7", "Nothing cheaper than the reading already done would change this.", ["q4"]),
        infer("q8", "Do not pursue CAND-C as stated; a non-rectangular variant would be a different candidate.", ["q5"]),
    ], {"candidate_key": "CAND-C", "claim_checks": [{"claim_id": "C1", "status": "covered", "source_refs": [f"{PR}#§2"],
                                                      "conditions": ["(s,a)-rectangularity"], "counterexample_status": "none_found_in_scope",
                                                      "checked_scope": "synthetic fixture paper on rectangular robust MDPs (partial text)"}],
        "assessments": [asm("CAND-C", "novelty", "known", "low", [f"{PR}#§2"], "statement covered by Theorem 2 (synthetic)")]})
    write(T, "check_candidate__rev_CAND-A_v2", [
        reported("q1", "The i.i.d. source (Observation 3) is nearest to the open-loop statement.", PI, "§2"),
        reported("q2", "Marginalisation covers the i.i.d. side; the persistent side under open-loop policies is not discussed.", PI, "§3"),
        infer("q3", "Under open-loop policies the per-step marginal alone determines the value, so the narrowed claim may be a direct consequence of linearity.", src=(PI, "§2")),
        unk("q4", "Whether this narrowed statement is stated anywhere needs a live search."),
        infer("q5", "The narrowed claim no longer depends on the information structure; its interest is limited.", ["q3"]),
        hyp("q6", "No counterexample expected under open-loop policies.", "equal open-loop values on the finite family", "an instance with unequal open-loop values"),
        infer("q7", "A finite-family counterexample search would check it cheaply.", ["q6"]),
        infer("q8", "Keep as a narrow, low-value statement; useful mainly as a control for CAND-B.", ["q5"]),
    ], {"candidate_key": "CAND-A", "claim_checks": [{"claim_id": "C1", "status": "possibly_distinct", "source_refs": [f"{PI}#§2"],
                                                      "conditions": ["open-loop policies"], "counterexample_status": "insufficient_evidence",
                                                      "checked_scope": "synthetic fixture papers"}],
        "assessments": [asm("CAND-A", "scientific_value", "known", "low", [f"{PI}#§2"], "close to a direct consequence of marginalisation"),
                        asm("CAND-A", "novelty", "unknown", None, [], "needs a live search"),
                        asm("CAND-A", "feasibility", "known", "high", [f"{PB}#§3"], "finite check is cheap")]})

    spec = lambda key, hyp_, fals, stmt, check: {
        "candidate_key": key, "study_stage": "pilot", "research_branch": "theoretical", "hypothesis": hyp_, "falsification": fals,
        "baselines": ["open-loop (history-independent) policy class"], "environment": {"family": "binary actions, rewards observed, H<=3, p in {1/2,1/3,2/3,1/4}"},
        "evaluation": {"method": check, "equivalence": "equal optimal value (working assumption)"},
        "resources": {"cpu_seconds": 30, "gpu": 0}, "continue_criteria": ["no counterexample in the family"],
        "abandon_criteria": ["a counterexample satisfying all assumptions"], "theorem_statement": stmt,
        "assumptions": ["same marginal of theta", "rewards observed immediately", "same policy class in A and B"],
        "policy_information_class": "deterministic policies over own past actions and rewards (identical in A and B); randomised policies cannot do better",
        "proof_obligations": [], "counterexample_search_plan": None, "review_method": "exact enumeration with belief-DP cross-check", "missing": []}
    spec_answers = [
        infer("q1", "The pilot tests the stated claim; an instance satisfying all assumptions with a different outcome refutes it.", ["q3"]),
        given("q2", "Baseline: the open-loop policy class; environment: the finite family in the input plan; no data; CPU only."),
        given("q3", "Frozen: claim, family, policy class, working equivalence definition. Nothing required for the pilot is missing."),
        infer("q4", "Continue if no counterexample; a counterexample abandons the claim. Finite support never proves the general statement.", ["q3"]),
        given("q5", "Not a v3 task: a registered local theory pilot (exact computation)."),
    ]
    write(T, "make_research_spec__pilot__rev_CAND-A_v1", spec_answers,
          spec("CAND-A", CLAIM_A1["statement"], "unequal optimal values on an instance satisfying the assumptions", CLAIM_A1["statement"], "exact enumeration (H=2, p=1/2)"))
    write(T, "make_research_spec__pilot__rev_CAND-B_v1", spec_answers,
          spec("CAND-B", CLAIM_B1["statement"], "an instance in the family with V*_B(history) != V*_A(open-loop)", CLAIM_B1["statement"], "finite-family counterexample search"))
    write(T, "make_research_spec__pilot__rev_CAND-A_v2", spec_answers,
          spec("CAND-A", CLAIM_A2["statement"], "an instance with unequal open-loop optimal values", CLAIM_A2["statement"], "finite-family counterexample search"))

    write(T, "check_theory__rev_CAND-B_v1", [
        infer("q1", "Quantifiers: for all horizons H >= 1 and priors p in (0,1); binary actions; the same deterministic history-dependent policy class in A and B.", ["q2"]),
        infer("q2", "Obligations: O1 in A one reward reveals theta; O2 in B history is independent of future theta_t; O3 extension beyond binary actions with revealing rewards.", ["q1"]),
        observed("q3", "The finite-family computation agrees with O1 and O2 on every checked instance; it does not discharge the general case.", "artifact:counterexample_search_voi_identity.json", "instances"),
        observed("q4", "No counterexample was found in the computed family.", "artifact:counterexample_search_voi_identity.json", "instances"),
        infer("q5", "Proof status: draft (LLM review of the derivation sketch); numbers support instances only; O3 is open.", ["q3"]),
    ], {"candidate_key": "CAND-B", "quantifiers": "for all H >= 1, p in (0,1)", "policy_information_class": "deterministic history-dependent, identical in A and B",
        "obligations": [
            {"id": "O1", "statement": "In A the first reward reveals theta exactly", "depends_on": [], "status": "discharged_by_derivation", "evidence_refs": []},
            {"id": "O2", "statement": "In B the history is independent of future theta_t", "depends_on": [], "status": "discharged_by_derivation", "evidence_refs": []},
            {"id": "O3", "statement": "Extension beyond binary actions with revealing rewards", "depends_on": ["O1"], "status": "open", "evidence_refs": []}],
        "proof_status": "draft", "review_method": "llm", "counterexample_status": "none_found_in_scope"})

    def ud(round_, answers, payload):
        write(T, f"update_decision__r{round_}", answers, payload)

    base_tail = lambda q8, q9: [infer("q8", q8, ["q5"]), infer("q9", q9, ["q8"])]
    ud(1, [
        infer("q1", "No computation has run yet; all material is the initial (synthetic) reading.", src=(PB, "§2")),
        infer("q2", "It applies to CAND-A v1 and CAND-B v1; CAND-C was rejected as covered.", src=(PR, "§2")),
        unk("q3", "No judgement has changed in this round; novelty remains unknown for A and B."),
        infer("q4", "A and B stay unresolved (novelty unknown); no forced order.", ["q3"]),
        infer("q5", "The unknown most likely to change the choice is whether CAND-A survives a small exact instance; the exact enumeration pilot checks it.", ["q4"]),
        infer("q6", "Run the registered exact enumeration (H=2, p=1/2); unequal values refute CAND-A C1, equal values give finite support only; cost: one pilot.", ["q5"]),
        infer("q7", "Not a duplicate: no pilot has run.", ["q1"]),
        *base_tail("Continue investigating.", "No stop.")],
        {"new_evidence_refs": [], "duplicate_evidence_refs": [], "assessment_updates": [], "ranking_changes": [],
         "next_action": {"action_type": "cpu_pilot", "purpose": "preliminary_check", "target_unknown_key": "cex_A", "candidate_keys": ["CAND-A"],
                         "inputs": {"pilot_id": "mdp_exact_enumeration"},
                         "expected_branches": [{"if": "values differ", "then": "reject CAND-A v1; consider a narrower revision"}, {"if": "equal", "then": "finite support only"}],
                         "cost_cap": {"pilots": 1}, "why_now": "cheapest check that can disqualify a candidate"},
         "stop_recommendation": {"stop": False}, "revision_proposals": []})
    ud(2, [
        observed("q1", "New: the exact enumeration artifact reports unequal optimal values for A and B under the same history-dependent class.", "artifact:mdp_values.json", "values"),
        infer("q2", "It applies to CAND-A v1 C1 (refuted); a narrowed revision must re-check this evidence before using it.", ["q1"]),
        infer("q3", "CAND-A v1 is refuted; B's judgements are unchanged.", ["q1"]),
        infer("q4", "A v1 leaves the ranking; B stays unresolved on novelty.", ["q3"]),
        infer("q5", "For B the decisive unknown is whether the value-of-history identity survives the finite family; a counterexample search checks it.", ["q4"]),
        infer("q6", "Run the voi_identity counterexample search; a failure refutes B C1, success gives finite support; cost: one pilot.", ["q5"]),
        infer("q7", "Not a duplicate: different claim and inputs.", ["q6"]),
        *base_tail("Continue: B has a cheap disqualifying check.", "No stop.")],
        {"new_evidence_refs": ["artifact:mdp_values.json"], "duplicate_evidence_refs": [], "assessment_updates": [], "ranking_changes": [],
         "next_action": {"action_type": "counterexample_search", "purpose": "preliminary_check", "target_unknown_key": "voi_B", "candidate_keys": ["CAND-B"],
                         "inputs": {"pilot_id": "mdp_counterexample", "claim": "voi_identity"},
                         "expected_branches": [{"if": "counterexample", "then": "reject CAND-B"}, {"if": "holds", "then": "finite support; theory check next"}],
                         "cost_cap": {"pilots": 1}, "why_now": "only remaining cheap disqualifying check for an active candidate"},
         "stop_recommendation": {"stop": False},
         "revision_proposals": [{"candidate_key": "CAND-A", "change_reason": "C1 refuted by an exact counterexample under history-dependent policies; narrowed to the open-loop policy class",
                                 "changes": {"title": "Equivalence of fixed and i.i.d. parameter uncertainty under open-loop policies",
                                             "hypothesis": CLAIM_A2["statement"], "claims": [CLAIM_A2],
                                             "problem_scope": "finite-horizon MDPs with a hidden reward parameter; same marginal; open-loop policies",
                                             "validation_protocol": {"equivalence": "equal optimal value (working assumption)",
                                                                     "cheapest_check": {"action_type": "counterexample_search", "inputs": {"pilot_id": "mdp_counterexample", "claim": "eq_open"}}}},
                                 "recheck_evidence_refs": ["artifact:mdp_values.json"]}]})
    ud(3, [
        observed("q1", "New: the voi_identity search reports that the identity holds on every instance of the finite family.", "artifact:counterexample_search_voi_identity.json", "instances"),
        infer("q2", "It applies to CAND-B v1 C1 as finite-instance support only.", ["q1"]),
        infer("q3", "B C1 gains finite support; its general status stays unproven.", ["q2"]),
        infer("q4", "No ranking change: novelty remains unknown.", ["q3"]),
        infer("q5", "The next informative step for B is checking the proof obligations behind the identity.", ["q3"]),
        infer("q6", "Run check_theory on CAND-B; outcome updates proof status (draft or gap_found), never formally_verified.", ["q5"]),
        infer("q7", "Not a duplicate.", ["q6"]),
        *base_tail("Continue.", "No stop.")],
        {"new_evidence_refs": ["artifact:counterexample_search_voi_identity.json"], "duplicate_evidence_refs": [], "assessment_updates": [], "ranking_changes": [],
         "next_action": {"action_type": "check_theory", "purpose": "preliminary_check", "target_unknown_key": "proof_B", "candidate_keys": ["CAND-B"],
                         "inputs": {"review": "derivation"}, "expected_branches": [{"if": "gap", "then": "narrow B"}, {"if": "draft", "then": "keep"}],
                         "cost_cap": {"llm_calls": 1}, "why_now": "general claim needs proof obligations, not more numbers"},
         "stop_recommendation": {"stop": False}, "revision_proposals": []})
    ud(4, [
        infer("q1", "The theory check is a model review of the derivation; it adds no independent evidence beyond the computation.", ["q2"]),
        infer("q2", "It applies to CAND-B v1 C1 (draft proof status).", ["q1"]),
        unk("q3", "Novelty of A v2 and B remains unknown; nothing changed it."),
        infer("q4", "No ranking change.", ["q3"]),
        infer("q5", "The narrowed CAND-A v2 still has a cheap open-loop check.", ["q4"]),
        infer("q6", "Run the eq_open counterexample search for CAND-A v2; cost: one pilot.", ["q5"]),
        infer("q7", "Not a duplicate: the revision changed the claim.", ["q6"]),
        *base_tail("Continue.", "No stop.")],
        {"new_evidence_refs": [], "duplicate_evidence_refs": [], "assessment_updates": [], "ranking_changes": [],
         "next_action": {"action_type": "counterexample_search", "purpose": "preliminary_check", "target_unknown_key": "cex_A2", "candidate_keys": ["CAND-A"],
                         "inputs": {"pilot_id": "mdp_counterexample", "claim": "eq_open"}, "expected_branches": [{"if": "holds", "then": "finite support"}],
                         "cost_cap": {"pilots": 1}, "why_now": "last cheap check before novelty becomes the only decisive unknown"},
         "stop_recommendation": {"stop": False}, "revision_proposals": []})
    ud(5, [
        observed("q1", "New: the open-loop equivalence holds on every instance of the finite family.", "artifact:counterexample_search_eq_open.json", "instances"),
        infer("q2", "It applies to CAND-A v2 C1 as finite support only.", ["q1"]),
        unk("q3", "The decisive dimension (novelty of A v2 and B) is still unknown."),
        infer("q4", "A v2 and B both remain unresolved; no forced winner.", ["q3"]),
        infer("q5", "The remaining decisive unknowns need a live literature search or the user's equivalence definition; neither is available offline.", ["q4"]),
        unk("q6", "No allowed action in offline_local can check novelty; the next check is a live nearest-neighbour search."),
        infer("q7", "Repeating pilots or queries with unchanged inputs would add no information.", ["q5"]),
        infer("q8", "Stop as inconclusive within the offline budget; do not relax the gates.", ["q5"]),
        infer("q9", "Known: CAND-A v1 refuted by exact counterexample; B C1 finite support with draft proof. Unknown: novelty, equivalence definition. Next: live search for the value-of-history characterisation.", ["q8"]),
    ], {"new_evidence_refs": ["artifact:counterexample_search_eq_open.json"], "duplicate_evidence_refs": [], "assessment_updates": [], "ranking_changes": [],
        "next_action": None,
        "stop_recommendation": {"stop": True, "planning_outcome": "inconclusive", "reason": "decisive unknowns need live search / user input"},
        "revision_proposals": []})
    write(T, "check_claim_evidence", [
        observed("q1", "Each audited claim cites a computation artifact produced in this run.", "artifact:mdp_values.json", "values"),
        infer("q2", "The artifacts were produced under the pilot protocols frozen for the same revisions.", ["q1"]),
        infer("q3", "Finite-family support does not cover the general statements; refutations rest on exact counterexamples.", ["q1"]),
        unk("q4", "Missing: general proofs (O3) and a live novelty check."),
    ], {"checked": "all claims", "overreach": "general claims are not marked supported"})


# ============================================================================= world model
W = "hierarchical_world_model"
WT, WB, WA = "paper_fixture_wm_temporal_hierarchy", "paper_fixture_wm_bilevel_meta", "paper_fixture_wm_multiloss_alternating"


def wm_literature():
    papers = [
        {"canonical_id": "fixture:wm_temporal_hierarchy", "title": SYN + "Temporal abstraction in hierarchical world models", "authors": ["Synthetic Author D"],
         "year": 2026, "text_status": "partial_text", "version": "fixture-v1",
         "keywords": ["hierarchical", "world", "model", "temporal", "abstraction", "planning", "long-horizon"],
         "abstract": SYN + "Temporal hierarchies for long-horizon planning.",
         "units": {"§1": SYN + "A high-level model predicts over abstract time steps while a low-level model predicts primitive steps.",
                   "§2": SYN + "Reported result. Long-horizon planning return improves with temporal abstraction; prediction error alone did not track planning return.",
                   "§3": SYN + "Limitation. Both levels are trained with separate losses and alternating updates; no solution dependence between levels is modelled."}},
        {"canonical_id": "fixture:wm_bilevel_meta", "title": SYN + "Bilevel training of latent dynamics", "authors": ["Synthetic Author E"],
         "year": 2025, "text_status": "partial_text", "version": "fixture-v1",
         "keywords": ["bilevel", "nested", "optimization", "world", "model", "latent", "dynamics", "hypergradient"],
         "abstract": SYN + "Nested optimisation for latent dynamics.",
         "units": {"§1": SYN + "The upper problem trains a representation; the lower problem fits latent dynamics given the representation.",
                   "§2": SYN + "Method. Hypergradients through the lower-level solution map are approximated with a finite number of inner steps.",
                   "§3": SYN + "Limitation. No planning benchmark is reported; only one-step prediction error."}},
        {"canonical_id": "fixture:wm_multiloss_alternating", "title": SYN + "Multi-loss world-model training with alternating updates", "authors": ["Synthetic Author F"],
         "year": 2024, "text_status": "partial_text", "version": "fixture-v1",
         "keywords": ["multi-loss", "alternating", "updates", "world", "model", "training", "losses"],
         "abstract": SYN + "Several losses, alternating updates.",
         "units": {"§1": SYN + "Reconstruction, dynamics and reward losses are minimised by alternating gradient updates.",
                   "§2": SYN + "Claim. Alternating updates are reported to match joint training on the tested tasks.",
                   "§3": SYN + "Scope. Only single-level models were tested."}},
    ]
    (ROOT / "literature" / f"{W}.json").write_text(json.dumps(papers, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


W1C1 = {"id": "C1", "scope": "finite_instance", "check_key": "nested_differs_from_alternating", "expects_holds": True,
        "statement": "On a two-level quadratic instance, nested (solution-dependent) training and alternating two-loss training reach different solutions, so the two readings of multi-level optimisation are distinct problems"}
W1C2 = {"id": "C2", "scope": "general",
        "statement": "Training the high-level world model through the low-level solution map improves long-horizon planning return over alternating multi-loss training at matched compute"}
W2C1 = {"id": "C1", "scope": "general", "check_key": "nested_differs_from_alternating", "expects_holds": False,
        "statement": "Alternating multi-loss updates reach the same solution as nested training, so nested optimisation adds nothing"}


def wm_llm():
    write(W, "clarify_problem", [
        given("q1", "The idea names hierarchical world models and multi-level optimization; it fixes neither which hierarchy, which levels are optimised, nor the decision signal."),
        infer("q2", "'Hierarchical' may mean representation, temporal, policy or planning hierarchy; 'multi-level optimization' may mean several losses, alternating updates, or nested solution dependence (bilevel).", ["q1"]),
        infer("q3", "For the nested reading: upper variables x (high-level model), lower variables y (low-level model), lower solution map y*(x), finite-step approximation of y*; for the multi-loss reading there is no y*(x).", ["q2"]),
        given("q4", "The target conclusion is not given; branches: mechanism (nested dependence matters) vs empirical improvement claim."),
        hyp("q5", "If nested dependence matters, nested and alternating training reach different solutions already on a toy two-level problem.", "different fixed points on a quadratic instance", "identical fixed points"),
        unk("q6", "The decision signal (planning return vs prediction error), the baseline and whether cross-task reuse is claimed are unspecified; they require the user's goal and a live baseline check."),
        infer("q7", "Search terms: temporal abstraction world model, bilevel/nested world model training, multi-loss alternating world model training.", ["q2"]),
    ], {"interpretations": [
            {"id": "H1", "description": "Temporal hierarchy: high-level model over abstract time, low-level over primitive steps (distinguish_representation_temporal_policy_and_planning_hierarchies).", "status": "kept",
             "target_conclusion": "mechanism"},
            {"id": "M1", "description": "Nested solution dependence: the high level is trained through the low level's solution map (distinguish_multiple_losses_alternating_updates_and_nested_solution_dependence).", "status": "kept",
             "variables": ["x", "y", "y*(x)"], "working_assumptions": ["finite-step approximation of y*(x)"], "target_conclusion": "mechanism"},
            {"id": "M2", "description": "Several losses minimised with alternating updates (no solution dependence).", "status": "kept", "target_conclusion": "baseline"},
            {"id": "X", "description": "Every hierarchical world model is a multi-level optimisation problem.", "status": "rejected_too_broad",
             "rejection_reason": "conflates network hierarchy with nested optimisation"}],
        "concepts": [
            {"canonical_name": "bilevel optimization", "aliases": ["nested optimization"], "role": "candidate mechanism (solution dependence)"},
            {"canonical_name": "temporal abstraction", "aliases": ["options"], "role": "type of hierarchy"},
            {"canonical_name": "world model", "aliases": ["learned dynamics model"], "role": "object of study"}],
        "unknowns": [
            {"key": "decision_signal", "question": "Which decision signal and baseline decide success (identify_decision_signal_and_baseline): planning return, not prediction error?",
             "affects": ["W1"], "importance": "high",
             "available_checks": [{"action_type": "search_literature", "purpose": "information_gathering",
                                   "inputs": {"query": "hierarchical world model long-horizon planning baseline", "requires_live": True}, "cost": {"search_queries": 1}}],
             "missing_material": "a runnable baseline and the user's target task"},
            {"key": "cross_task", "question": "Is cross-task reuse claimed (evaluate_cross_task_reuse_if_claimed)? If so, which tasks are held out from method selection?",
             "affects": ["W1"], "importance": "medium", "available_checks": [], "missing_material": "user intent"}],
        "metrics_status": "undecided",
        "search_queries": [{"query": "hierarchical world model temporal abstraction planning", "purpose": "bottleneck"},
                           {"query": "bilevel nested world model latent dynamics", "purpose": "nearest"},
                           {"query": "multi-loss alternating updates world model training", "purpose": "refuting"},
                           {"query": "bilevel nested hypergradient", "purpose": "user_method_link"}]})
    for pid, obs in [(WT, "Planning return improved with temporal abstraction; prediction error did not track it (synthetic report, not reproduced)."),
                     (WB, "Hypergradients through the lower-level solution map with finite inner steps (synthetic)."),
                     (WA, "Alternating updates reported to match joint training on single-level models (synthetic).")]:
        write(W, f"read_paper__{pid}", [
            reported("q1", "Problem stated in §1.", pid, "§1"),
            reported("q2", "Method / result in §2.", pid, "§2"),
            reported("q3", "Contribution is the §2 statement; support type is a reported result, not reproduced here.", pid, "§2"),
            reported("q4", "Scope and limitations in §3.", pid, "§3"),
            unk("q5", "Baselines, compute and exact numbers are not in the retrieved units (partial text)."),
            infer("q6", "Relevant as nearest neighbour or background; per-candidate links come later.", ["q2"]),
            reported("q7", "The limitation is stated in §3.", pid, "§3"),
            infer("q8", "The experiments section (not retrieved) would give baselines and compute.", ["q5"]),
        ], {"paper_id": pid, "reading_status": "partial",
            "evidence": [{"locator": "§2", "observation": obs}, {"locator": "§3", "observation": "Limitation stated in §3 (synthetic)."}],
            "remaining_questions": ["baselines and compute (not retrieved)"]})
    write(W, "map_field", [
        reported("q1", "Long-horizon planning with learned models is the bottleneck in the synthetic temporal-hierarchy source.", WT, "§2"),
        reported("q2", "That source reports planning return and notes that prediction error did not track it, so prediction error alone would not support a planning claim.", WT, "§2"),
        infer("q3", "The alternating-updates source and the bilevel source disagree in scope (single-level vs two-level) rather than in results.", src=(WA, "§3")),
        infer("q4", "The idea maps to whether nested dependence between levels matters for planning; no source tests that directly.", src=(WB, "§3")),
    ], {"field_problems": [
        {"id": "WP1", "problem": "Learned models for long-horizon planning", "evidence_refs": [f"{WT}#§2"], "metrics": ["planning return"], "baselines": ["flat world model"], "status": "single_source"},
        {"id": "WP2", "problem": "How to train coupled levels (nested vs alternating)", "evidence_refs": [f"{WB}#§2", f"{WA}#§2"], "metrics": ["prediction error (insufficient for planning claims)"], "baselines": [], "status": "disputed"}],
        "idea_maps_to": ["WP1", "WP2"], "missing_for_link": "no source tests nested training on planning return"})
    write(W, "link_background", [
        given("q1", "Profile: bilevel optimization and convergence analysis (stated, not verified against full text)."),
        reported("q2", "Bottleneck: training coupled levels; the bilevel source approximates hypergradients with finite inner steps.", WB, "§2"),
        infer("q3", "Bilevel structure maps to: x = high-level model, y = low-level model, y*(x) = low-level fit; hypergradient methods from the user's work apply.", src=(WB, "§2")),
        infer("q4", "Needs an actual solution dependence; a network hierarchy trained with separate losses has none.", src=(WA, "§1")),
        hyp("q5", "If nested dependence matters, nested and alternating training reach different solutions.", "different fixed points on a toy instance", "same fixed point"),
        infer("q6", "If alternating training reaches the same solution, the bilevel view is unnecessary.", ["q5"]),
        infer("q7", "Learning cost: world-model planning benchmarks (not in the profile); value assessed separately.", ["q1"]),
        given("q8", "Taste rules are inferred, unconfirmed tie-breakers only."),
    ], {"correspondences": [{"profile_item": "bilevel optimization", "mechanism_map": "x = high-level model, y = low-level model, y*(x) = low-level solution map; hypergradient via finite inner steps",
                             "conditions": ["actual solution dependence between levels"], "status": "hypothesis", "evidence_refs": [f"{WB}#§2"]}],
        "assessments": [asm("bilevel optimization", "field_importance", "known", "medium", [f"{WB}#§2"], "one candidate mechanism for WP2", "concept"),
                        asm("world model", "field_importance", "known", "high", [f"{WT}#§2"], "object of WP1", "concept")],
        "learning_tasks": [{"topic": "world-model planning benchmarks and baselines", "importance": "high", "affects": ["W1"], "why": "needed to test any planning claim"}],
        "taste_rules_applied": []})
    write(W, "propose_candidates", [
        infer("q1", "Open: whether nested dependence changes the trained solution at all, and whether that matters for planning return.", src=(WB, "§3")),
        infer("q2", "W1 and W2 below state hypotheses, mechanisms, nearest neighbours, checks and abandon conditions.", ["q1"]),
        hyp("q3", "Both are hypotheses.", "the toy check separates them", "the toy check is uninformative"),
        infer("q4", "W2 (alternating suffices) is the mechanism-different alternative; not every problem is rewritten as bilevel.", src=(WA, "§2")),
    ], {"candidates": [
        {"key": "W1", "title": "Nested training of the high-level model through the low-level solution map", "problem_scope": "two-level world models with an actual solution dependence",
         "hypothesis": W1C2["statement"], "mechanism": "hypergradient through y*(x)", "increment": "planning-return test of nested training (not prediction error)",
         "nearest_neighbors": [WB, WT], "claims": [W1C1, W1C2], "validation_protocol": {"decision_signal": "planning return (undecided by user)"},
         "abandon_conditions": ["toy check shows no difference", "no runnable baseline"], "research_branch": "empirical",
         "cheapest_check": {"action_type": "cpu_pilot", "inputs": {"pilot_id": "nested_vs_alternating"}}},
        {"key": "W2", "title": "Alternating multi-loss training suffices", "problem_scope": "same two-level models",
         "hypothesis": W2C1["statement"], "mechanism": "separate losses, alternating updates", "increment": "simpler training if true",
         "nearest_neighbors": [WA], "claims": [W2C1], "validation_protocol": {}, "abandon_conditions": ["a counterexample instance"],
         "research_branch": "empirical", "cheapest_check": {"action_type": "cpu_pilot", "inputs": {"pilot_id": "nested_vs_alternating"}}}],
        "no_alternative_reason": None,
        "unknowns": [{"key": "wm_nested", "question": "Do nested and alternating training reach different solutions on a toy two-level problem?",
                      "affects": ["W1", "W2"], "importance": "high",
                      "available_checks": [{"action_type": "cpu_pilot", "purpose": "preliminary_check", "inputs": {"pilot_id": "nested_vs_alternating"},
                                            "cost": {"pilots": 1}, "can_disqualify": True}]},
                     {"key": "wm_baseline", "question": "Is there a runnable world-model baseline with a planning-return evaluator?", "affects": ["W1"], "importance": "high",
                      "available_checks": [{"action_type": "search_literature", "purpose": "information_gathering",
                                            "inputs": {"query": "hierarchical world model planning benchmark code", "requires_live": True}, "cost": {"search_queries": 1}}]}]})
    for key, claim, novelty_ref in [("W1", "C1", WB), ("W2", "C1", WA)]:
        write(W, f"check_candidate__rev_{key}_v1", [
            reported("q1", "Nearest synthetic sources: bilevel latent dynamics (§2) and alternating multi-loss training (§2).", WB, "§2"),
            reported("q2", "The bilevel source reports no planning benchmark, only prediction error.", WB, "§3"),
            infer("q3", "The difference is substantive only if the levels have a real solution dependence.", src=(WA, "§1")),
            unk("q4", "Novelty needs a live search; only synthetic fixtures were read."),
            infer("q5", "Depends on the undecided decision signal and on a runnable baseline.", ["q4"]),
            hyp("q6", "A toy instance may separate nested from alternating training.", "different fixed points", "same fixed point"),
            infer("q7", "Run the CPU toy check first; the planning claim needs AI-Scientist-v3 with a real baseline.", ["q6"]),
            infer("q8", "Keep the planning claim pending; do not report toy results as world-model evidence.", ["q7"]),
        ], {"candidate_key": key, "claim_checks": [{"claim_id": claim, "status": "unresolved", "source_refs": [f"{novelty_ref}#§2"],
                                                     "conditions": ["actual solution dependence"], "counterexample_status": "construction_to_check",
                                                     "checked_scope": "synthetic fixture papers"}],
            "assessments": [asm(key, "scientific_value", "known", "high" if key == "W1" else "medium", [f"{WT}#§2"], "planning return is the field's bottleneck (synthetic)"),
                            asm(key, "novelty", "unknown", None, [], "no live search"),
                            asm(key, "feasibility", "known", "low" if key == "W1" else "high", [f"{WB}#§3"], "W1 needs GPU-scale training via v3; W2 is cheap")]})
    write(W, "make_research_spec__pilot__rev_W1_v1", [
        infer("q1", "The toy pilot tests only whether nested and alternating training differ; identical solutions would undercut W1's mechanism.", ["q3"]),
        given("q2", "Baseline: alternating updates on the same quadratic; CPU only; no data."),
        given("q3", "Frozen: quadratic instance and step sizes; the planning claim (C2) is out of scope and stays unknown."),
        infer("q4", "Continue only if the solutions differ; this is a precondition, not evidence for C2.", ["q3"]),
        given("q5", "Local registered pilot; the formal planning experiment would be a v3 task once a baseline exists."),
    ], {"candidate_key": "W1", "study_stage": "pilot", "research_branch": "empirical", "hypothesis": W1C1["statement"],
        "falsification": "nested and alternating fixed points coincide", "baselines": ["alternating two-loss updates"],
        "environment": {"toy": "quadratic two-level problem"}, "evaluation": {"method": "closed form + gradient runs"},
        "resources": {"cpu_seconds": 10}, "continue_criteria": ["fixed points differ"], "abandon_criteria": ["fixed points coincide"],
        "theorem_statement": None, "assumptions": ["lower level strongly convex"], "policy_information_class": None,
        "proof_obligations": [], "counterexample_search_plan": None, "review_method": "closed-form check", "missing": []})
    write(W, "update_decision__r1", [
        infer("q1", "Only the initial synthetic reading so far.", src=(WB, "§2")),
        infer("q2", "Applies to W1 and W2.", ["q1"]),
        unk("q3", "No judgement changed yet."),
        infer("q4", "Both unresolved on novelty.", ["q3"]),
        infer("q5", "The toy check decides between W1's mechanism and W2's claim.", ["q4"]),
        infer("q6", "Run the nested_vs_alternating pilot; different solutions refute W2 C1 and support W1 C1 (toy scope only).", ["q5"]),
        infer("q7", "Not a duplicate.", ["q6"]),
        infer("q8", "Continue.", ["q5"]), infer("q9", "No stop.", ["q8"]),
    ], {"next_action": {"action_type": "cpu_pilot", "purpose": "preliminary_check", "target_unknown_key": "wm_nested", "candidate_keys": ["W1", "W2"],
                        "inputs": {"pilot_id": "nested_vs_alternating"}, "expected_branches": [{"if": "differ", "then": "reject W2; W1 mechanism plausible"}],
                        "cost_cap": {"pilots": 1}, "why_now": "cheapest check that can disqualify a candidate"},
        "stop_recommendation": {"stop": False}})
    write(W, "update_decision__r2", [
        observed("q1", "New: the toy pilot artifact reports different nested and alternating solutions.", "artifact:nested_vs_alternating.json", "closed_form"),
        infer("q2", "Refutes W2 C1 (general) by counterexample; supports W1 C1 within the toy scope only.", ["q1"]),
        infer("q3", "W2 rejected; W1's planning claim (C2) is untouched.", ["q2"]),
        infer("q4", "W1 remains unresolved (novelty unknown, feasibility low without a backend).", ["q3"]),
        infer("q5", "The decisive unknowns are a runnable baseline and the decision signal; both need live work or the user.", ["q4"]),
        unk("q6", "No allowed offline action can check the baseline."),
        infer("q7", "Repeating the toy pilot would add nothing.", ["q1"]),
        infer("q8", "Stop as inconclusive; formal experiments belong to AI-Scientist-v3 once a baseline exists.", ["q5"]),
        infer("q9", "Next most valuable check: find a runnable hierarchical world-model baseline with a planning-return evaluator.", ["q8"]),
    ], {"next_action": None, "stop_recommendation": {"stop": True, "planning_outcome": "inconclusive"}})
    write(W, "check_claim_evidence", [
        observed("q1", "W1 C1 and W2 C1 cite the toy pilot artifact.", "artifact:nested_vs_alternating.json", "closed_form"),
        infer("q2", "Same pilot protocol as the claims' revision.", ["q1"]),
        infer("q3", "The toy result does not reach W1's planning claim.", ["q1"]),
        unk("q4", "Missing: any world-model experiment."),
    ], {"checked": "all claims"})


if __name__ == "__main__":
    mdp_literature()
    mdp_llm()
    wm_literature()
    wm_llm()
    print("fixtures written to", ROOT)
