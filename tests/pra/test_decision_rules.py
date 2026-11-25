"""T01–T05, T09: unknowns, familiarity, evidence independence, revisions, refutations, partial ranking."""
import time

import pytest

from personal_research_agent import profiles
from personal_research_agent.config import load_profile
from personal_research_agent.decision import rules
from personal_research_agent.decision.ranking import rank
from personal_research_agent.models import (
    Assessment, AssessmentState, Concept, EvidenceKind, ExecutionOrigin, Level, LinkRelation, PairwiseDecision,
)
from personal_research_agent.store import ImmutableRecordError

from .conftest import ROOT, assess, evidence, link, rev


def _rank(revs, asms, strategy="evidence_loop", rejected=None):
    return rank(revs, asms, 1, strategy, ExecutionOrigin.fixture, None, "rank_t", rejected or {}, [])


# T01 ------------------------------------------------------------------------------------------
def test_t01_unknown_novelty_is_not_a_low_score():
    with pytest.raises(ValueError):
        Assessment(id="a", origin=ExecutionOrigin.fixture, source="t", subject_type="candidate", subject_id="A",
                   subject_revision="r", dimension="novelty", state=AssessmentState.unknown, judgment=Level.low,
                   rationale="unknown cannot carry a judgment")
    a, b = rev("CAND-A"), rev("CAND-B")
    asms = [assess(a.id, "scientific_value", "high"), assess(a.id, "novelty", None), assess(a.id, "feasibility", "high"),
            assess(b.id, "scientific_value", "low", cid="CAND-B"), assess(b.id, "novelty", "low", cid="CAND-B"),
            assess(b.id, "feasibility", "low", cid="CAND-B")]
    snap = _rank([a, b], asms)
    assert a.id in snap.unresolved_candidates            # kept, not eliminated
    assert a.id not in snap.rejected_candidates
    assert snap.pairwise_decisions[0]["decision"] == PairwiseDecision.insufficient_evidence.value
    # vetoes never fire on missing evidence
    assert rules.vetoes([a, b], [], {}, {}, {}) == []


# T02 ------------------------------------------------------------------------------------------
def test_t02_familiarity_does_not_raise_scientific_value_and_unfamiliar_core_concepts_need_learning():
    profile = load_profile(ROOT / "profiles" / "peiran.yaml")
    cap, basis = profiles.capability_for(["minimax optimization"], profile)
    assert cap == Level.medium and "nonconvex minimax optimization" in basis   # best match, stated not verified
    cap2, _ = profiles.capability_for(["value of information"], profile)
    assert cap2 == Level.low
    concepts = [Concept(id="c1", origin=ExecutionOrigin.fixture, source="t", canonical_name="minimax optimization", role="tool",
                        existing_capability=Level.medium, field_importance=Level.low),
                Concept(id="c2", origin=ExecutionOrigin.fixture, source="t", canonical_name="value of information", role="core",
                        existing_capability=Level.low, field_importance=Level.high)]
    tasks = profiles.learning_tasks(concepts)
    assert [t.concept for t in tasks] == ["value of information"]
    # personal fit cannot beat a science difference, and is ignored outside the personalized strategy
    a, b = rev("CAND-A"), rev("CAND-B")
    common = lambda r, c, sv: [assess(r, "scientific_value", sv, cid=c), assess(r, "novelty", "medium", cid=c),
                               assess(r, "feasibility", "medium", cid=c)]
    asms = common(a.id, "CAND-A", "low") + common(b.id, "CAND-B", "high") + [assess(a.id, "personal_fit", "high"),
                                                                           assess(b.id, "personal_fit", "low", cid="CAND-B")]
    snap = _rank([a, b], asms, strategy="personalized_loop")
    assert snap.preferred_candidates == [b.id]
    tie = common(a.id, "CAND-A", "high") + common(b.id, "CAND-B", "high") + [assess(a.id, "personal_fit", "high"),
                                                                           assess(b.id, "personal_fit", "low", cid="CAND-B")]
    assert set(_rank([a, b], tie, strategy="evidence_loop").preferred_candidates) == {a.id, b.id}
    snap_p = _rank([a, b], tie, strategy="personalized_loop")
    assert snap_p.preferred_candidates == [a.id]
    assert any("preference-sensitive" in str(c) for c in snap_p.changed_from_previous)


# T03 ------------------------------------------------------------------------------------------
def test_t03_mirrors_do_not_add_independent_evidence_but_distinct_facts_remain(store):
    r = rev()
    e1 = evidence("e1", group="paper1#p.3", kind=EvidenceKind.literature_report, ns="literature", locator="p.3", source="paper1")
    mirror = evidence("e2", group="paper1#p.3", kind=EvidenceKind.literature_report, ns="literature", locator="p.3",
                      source="paper1-mirror", obs="same result restated")
    other = evidence("e3", group="paper1#p.7", kind=EvidenceKind.literature_report, ns="literature", locator="p.7", source="paper1")
    for e in (e1, mirror, other):
        store.put(e)
    exact_dup = e1.model_copy(update={"id": "e1b"})
    kept_id, created = store.put(exact_dup)
    assert (kept_id, created) == ("e1", False)
    links = [link(f"l{i}", e, r.id) for i, e in enumerate(("e1", "e2", "e3"))]
    ev = {e.id: e for e in (e1, mirror, other)}
    assert rules.independent_support(r.id, links, ev) == 2   # p.3 (twice) counts once, p.7 counts


# T04 ------------------------------------------------------------------------------------------
def test_t04_old_evidence_does_not_support_a_new_revision(store):
    v1 = rev()
    store.put(v1)
    changed = v1.model_copy(update={"hypothesis": "narrowed"})
    with pytest.raises(ImmutableRecordError):
        store.update(changed.model_validate(changed.model_dump()))
    v2 = rev(version=2, parent=v1.id).model_copy(update={"hypothesis": "narrowed"})
    v2 = v2.model_validate(v2.model_dump())
    assert v2.key_fields_hash != v1.key_fields_hash
    ev = {"e1": evidence("e1")}
    links = [link("l1", "e1", v1.id)]
    assert rules.independent_support(v1.id, links, ev) == 1
    assert rules.independent_support(v2.id, links, ev) == 0


# T05 ------------------------------------------------------------------------------------------
def test_t05_one_applicable_refutation_outweighs_many_supports():
    r = rev()
    ev = {f"s{i}": evidence(f"s{i}", group=f"g{i}") for i in range(5)}
    ev["x"] = evidence("x", group="gx", kind=EvidenceKind.counterexample)
    links = [link(f"l{i}", f"s{i}", r.id) for i in range(5)] + [link("lx", "x", r.id, LinkRelation.refutes)]
    vetoes = rules.vetoes([r], links, ev, {}, {})
    assert [v.revision_id for v in vetoes] == [r.id]
    # an unverified or fixture-only refutation does not veto
    ev["x"] = evidence("x", group="gx", kind=EvidenceKind.counterexample, verified=False)
    assert rules.vetoes([r], links, ev, {}, {}) == []


# T09 ------------------------------------------------------------------------------------------
def test_t09_unresolved_candidates_block_all_rejected_and_no_forced_champion():
    from personal_research_agent.config import Limits

    limits = Limits(max_rounds=6, max_actions=20, max_no_change_rounds=2, max_retries_per_action=1, max_candidates=6,
                    max_parallel_actions=2, max_llm_calls=40, max_input_tokens_total=1, max_output_tokens_total=1,
                    max_search_queries=1, max_full_text_reads=1, max_pilots=1, run_wall_seconds=1, action_wall_seconds=1,
                    gpu_hours=0, api_usd=0)
    d = rules.stop_check(1, 0, limits, 1, active_count=0, unresolved_count=1, wall_remaining=10, budget_exhausted_dims=[])
    assert d.reason is None or d.reason.value != "all_candidates_rejected"
    d2 = rules.stop_check(1, 0, limits, 1, active_count=2, unresolved_count=2, wall_remaining=10, budget_exhausted_dims=["llm_calls"])
    assert d2.reason.value == "budget_exhausted"
    a, b = rev("CAND-A"), rev("CAND-B")
    snap = _rank([a, b], [assess(a.id, "scientific_value", "high")])
    assert snap.preferred_candidates == [] and set(snap.unresolved_candidates) == {a.id, b.id}
