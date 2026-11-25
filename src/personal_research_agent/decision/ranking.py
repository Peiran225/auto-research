"""Partial ranking (plan §4.3, §6.2).

Candidates are compared dimension by dimension on *known* judgments only. An unknown decisive
dimension yields ``insufficient_evidence`` instead of a forced order; trade-offs yield a tie.
Personal fit is used only by the personalized strategy and only to break science ties, and
that use is recorded so the sensitivity of the recommendation is visible.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..models import (
    LEVEL_ORDER, Assessment, AssessmentState, CandidateRevision, Level, PairwiseDecision, RankingSnapshot,
    ExecutionOrigin,
)

# For difficulty-like dimensions a lower level is better; we compare "feasibility" directly.
DECISIVE = ("scientific_value", "novelty", "feasibility")


@dataclass
class Standing:
    revision: CandidateRevision
    dims: dict[str, Optional[Assessment]] = field(default_factory=dict)

    def state(self, dim: str) -> AssessmentState:
        a = self.dims.get(dim)
        return a.state if a else AssessmentState.unknown

    def level(self, dim: str) -> Optional[Level]:
        a = self.dims.get(dim)
        return a.judgment if a and a.state == AssessmentState.known else None

    def unresolved_dims(self) -> list[str]:
        return [d for d in DECISIVE if self.level(d) is None]


def latest_assessments(assessments: list[Assessment], revision_id: str) -> dict[str, Assessment]:
    """Most recent assessment per dimension for one candidate revision (append-only history)."""
    out: dict[str, Assessment] = {}
    for a in assessments:
        if a.subject_type == "candidate" and a.subject_revision == revision_id:
            out[a.dimension] = a          # list is in insertion order -> last wins
    return out


def compare(a: Standing, b: Standing, use_personal_fit: bool) -> tuple[PairwiseDecision, str]:
    unknown = [d for d in DECISIVE if a.level(d) is None or b.level(d) is None]
    better_a = [d for d in DECISIVE if d not in unknown and LEVEL_ORDER[a.level(d)] > LEVEL_ORDER[b.level(d)]]
    better_b = [d for d in DECISIVE if d not in unknown and LEVEL_ORDER[b.level(d)] > LEVEL_ORDER[a.level(d)]]
    if unknown:
        return PairwiseDecision.insufficient_evidence, f"unknown on {unknown}"
    if better_a and not better_b:
        return PairwiseDecision.prefer_a, f"better on {better_a}"
    if better_b and not better_a:
        return PairwiseDecision.prefer_b, f"better on {better_b}"
    if better_a and better_b:
        return PairwiseDecision.tie, f"trade-off: A better on {better_a}, B better on {better_b}"
    if use_personal_fit:
        pa, pb = a.level("personal_fit"), b.level("personal_fit")
        if pa is not None and pb is not None and pa != pb:
            winner = PairwiseDecision.prefer_a if LEVEL_ORDER[pa] > LEVEL_ORDER[pb] else PairwiseDecision.prefer_b
            return winner, "science dimensions tied; broken by personal_fit (personalized strategy only)"
    return PairwiseDecision.tie, "equal on all known decisive dimensions"


def rank(revisions: list[CandidateRevision], assessments: list[Assessment], round_: int, strategy: str,
         origin: ExecutionOrigin, previous: Optional[RankingSnapshot], snapshot_id: str,
         rejected_reasons: dict[str, str], change_evidence: list[dict]) -> RankingSnapshot:
    use_fit = strategy == "personalized_loop"
    active = [r for r in revisions if r.status == "active" and r.id not in rejected_reasons]
    standings = [Standing(r, latest_assessments(assessments, r.id)) for r in active]
    pairwise = []
    beaten: set[str] = set()
    undecided: set[str] = set()
    tie_edges: list[tuple[str, str]] = []
    fit_used = False
    for i, a in enumerate(standings):
        for b in standings[i + 1:]:
            d, why = compare(a, b, use_fit)
            fit_used |= "personal_fit" in why
            pairwise.append({"a": a.revision.id, "b": b.revision.id, "decision": d.value, "why": why})
            if d == PairwiseDecision.prefer_a:
                beaten.add(b.revision.id)
            elif d == PairwiseDecision.prefer_b:
                beaten.add(a.revision.id)
            elif d == PairwiseDecision.tie:
                tie_edges.append((a.revision.id, b.revision.id))
            else:
                undecided |= {a.revision.id, b.revision.id}
    unresolved = [s.revision.id for s in standings if s.unresolved_dims()]
    preferred = [s.revision.id for s in standings
                 if s.revision.id not in beaten and s.revision.id not in unresolved]
    ties = [[x, y] for x, y in tie_edges if x in preferred and y in preferred]
    snap = RankingSnapshot(
        id=snapshot_id, origin=origin, source="decision.ranking", round=round_,
        preferred_candidates=preferred, ties=ties, unresolved_candidates=unresolved,
        rejected_candidates=dict(rejected_reasons), pairwise_decisions=pairwise, strategy=strategy,
        changed_from_previous=[],
    )
    if previous is not None:
        changes = []
        if previous.preferred_candidates != snap.preferred_candidates:
            changes.append({"change": "preferred", "from": previous.preferred_candidates, "to": snap.preferred_candidates})
        new_rej = set(snap.rejected_candidates) - set(previous.rejected_candidates)
        if new_rej:
            changes.append({"change": "rejected", "candidates": sorted(new_rej)})
        if previous.unresolved_candidates != snap.unresolved_candidates:
            changes.append({"change": "unresolved", "from": previous.unresolved_candidates, "to": snap.unresolved_candidates})
        if changes:
            for c in changes:
                c["evidence"] = change_evidence
        snap.changed_from_previous = changes
    if fit_used:
        snap.changed_from_previous.append({"note": "personal_fit broke at least one science tie; recommendation is preference-sensitive"})
    return snap
