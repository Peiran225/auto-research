"""Programmatic decision rules: evidence applicability, independence, vetoes, recommendation
gates and stop conditions (plan §6.2–6.5). Model output never overrides these."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..models import (
    Assessment, AssessmentState, CandidateRevision, Evidence, EvidenceKind, EvidenceLink, ExecutionOrigin,
    LinkRelation, PaperRecord, ResearchAction, StopReason, TextStatus, Unknown, VerificationStatus, Level,
)


def links_for(revision_id: str, links: list[EvidenceLink]) -> list[EvidenceLink]:
    """Only links made against this exact revision apply; links to a parent revision do not
    automatically support a new version (T04)."""
    return [l for l in links if l.candidate_revision_id == revision_id]


def independent_support(revision_id: str, links: list[EvidenceLink], evidence: dict[str, Evidence],
                        relation: LinkRelation = LinkRelation.supports) -> int:
    """Number of independent sources: mirrors, restatements and re-analyses of one result share
    ``same_source_group`` and count once (T03)."""
    groups = {evidence[l.evidence_id].same_source_group for l in links_for(revision_id, links)
              if l.relation == relation and l.evidence_id in evidence}
    return len(groups)


@dataclass
class Veto:
    revision_id: str
    reason: str
    evidence_ids: list[str] = field(default_factory=list)


def vetoes(revisions: list[CandidateRevision], links: list[EvidenceLink], evidence: dict[str, Evidence],
           resource_blocks: dict[str, str], coverage_blocks: dict[str, str] | None = None) -> list[Veto]:
    """Explicit disqualifiers only: an applicable verified counterexample / computation that
    refutes a claim of this revision, or a verified hard resource limit. Support counts never
    outweigh an applicable refutation (T05). Absence of evidence is never a veto (T09)."""
    out = []
    for r in revisions:
        if r.status != "active":
            continue
        refuting = [l for l in links_for(r.id, links) if l.relation == LinkRelation.refutes
                    and l.evidence_id in evidence
                    and evidence[l.evidence_id].verification_status == VerificationStatus.verified
                    and evidence[l.evidence_id].kind in (EvidenceKind.counterexample, EvidenceKind.computation,
                                                          EvidenceKind.backend_artifact)]
        if refuting:
            out.append(Veto(r.id, "applicable verified refutation: " + "; ".join(l.applicability for l in refuting),
                            [l.evidence_id for l in refuting]))
        elif coverage_blocks and r.id in coverage_blocks:
            out.append(Veto(r.id, coverage_blocks[r.id]))
        elif r.candidate_id in resource_blocks:
            out.append(Veto(r.id, "verified hard resource limit: " + resource_blocks[r.candidate_id]))
    return out


@dataclass
class GateReport:
    revision_id: str
    passed: bool
    failures: list[str]


def recommendation_gates(rev: CandidateRevision, dims: dict[str, Assessment], papers: dict[str, PaperRecord],
                         links: list[EvidenceLink], evidence: dict[str, Evidence], unknowns: list[Unknown],
                         backend_ok_for_branch: bool, preference_sensitive: bool) -> GateReport:
    """Plan §6.4: 'worth continuing' thresholds, not proof of novelty or of the final result."""
    f: list[str] = []
    if not rev.hypothesis or not rev.mechanism or not rev.claims:
        f.append("problem/mechanism/claims not explicit")
    missing = [d for d in ("scientific_value", "novelty", "feasibility")
               if d not in dims or dims[d].state != AssessmentState.known]
    if missing:
        f.append(f"decisive dimensions unknown: {missing}")
    nn = [papers[p] for p in rev.nearest_neighbors if p in papers]
    read_nn = [p for p in nn if p.text_status in (TextStatus.full_text, TextStatus.partial_text)
               and p.origin == ExecutionOrigin.live]
    if not read_nn:
        f.append("no nearest neighbour read substantively from a live source (fixture/synthetic or abstract-only reading does not count)")
    sv = dims.get("scientific_value")
    if sv is None or sv.state != AssessmentState.known or not sv.evidence_ids:
        f.append("field value lacks checkable evidence")
    pilot_support = [l for l in links_for(rev.id, links) if l.relation == LinkRelation.supports
                     and l.evidence_id in evidence
                     and evidence[l.evidence_id].kind in (EvidenceKind.computation, EvidenceKind.backend_artifact,
                                                          EvidenceKind.derivation, EvidenceKind.counterexample)
                     and evidence[l.evidence_id].namespace != "fixture"]
    if not pilot_support:
        f.append("cheapest validation has not met its stage threshold (no non-fixture pilot support)")
    if not backend_ok_for_branch:
        f.append("resources for the next stage are not available (backend/branch)")
    open_cheap = [u for u in unknowns if u.status == "open" and u.importance == Level.high
                  and rev.candidate_id in u.affects and u.available_checks]
    if open_cheap:
        f.append(f"cheap disqualifying checks still open: {[u.id for u in open_cheap]}")
    if preference_sensitive:
        f.append("recommendation depends on a preference tie-break (report as conditional)")
    return GateReport(rev.id, not f, f)


@dataclass
class StopDecision:
    stop: bool
    reason: Optional[StopReason] = None
    detail: str = ""


def stop_check(round_: int, no_change: int, limits, actions_done: int, active_count: int,
               unresolved_count: int, wall_remaining: float, budget_exhausted_dims: list[str]) -> StopDecision:
    if active_count == 0 and unresolved_count == 0:
        return StopDecision(True, StopReason.all_candidates_rejected, "every candidate was rejected on explicit grounds")
    if budget_exhausted_dims:
        return StopDecision(True, StopReason.budget_exhausted, f"exhausted: {budget_exhausted_dims}")
    if wall_remaining <= 0:
        return StopDecision(True, StopReason.budget_exhausted, "run wall time exhausted")
    if actions_done >= limits.max_actions:
        return StopDecision(True, StopReason.budget_exhausted, "max_actions reached")
    if round_ >= limits.max_rounds:
        return StopDecision(True, StopReason.max_rounds_reached, f"{round_} rounds")
    if no_change >= limits.max_no_change_rounds:
        return StopDecision(True, StopReason.max_no_change_reached, f"{no_change} rounds without new information")
    return StopDecision(False)


def action_priority(action: ResearchAction, preferred: list[str], top_two_unknown_ids: set[str]) -> tuple:
    """Plan §6.3 heuristic (not a Bayesian value-of-information computation): lower tuple = earlier.
    1) cheap checks that can disqualify the current preference, 2) unknowns deciding the top two,
    3) cheaper, 4) alternatives with a different mechanism."""
    targets_preferred = any(r in preferred for r in action.candidate_revision_ids)
    can_disqualify = action.rationale.get("can_disqualify", False)
    cost = sum(action.cost_cap.values()) if action.cost_cap else 1.0
    return (
        0 if (can_disqualify and (targets_preferred or not preferred)) else 1,
        0 if action.target_unknown_id in top_two_unknown_ids else 1,
        cost,
        0 if action.rationale.get("alternative_mechanism") else 1,
    )
