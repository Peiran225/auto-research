"""Theory-branch rules (plan §8.1): proof obligations and proof-status transitions.

* ``formally_verified`` only with a passing run of a trusted proof checker (none is configured
  here, so it is unreachable by design).
* Finite numerical checks attach as finite-instance support and never move a general
  statement past ``draft``.
* ``disproved`` needs a counterexample instance that satisfies every assumption.
* A failed proof attempt is ``gap_found`` (undecided), never ``disproved``.
* ``reviewed`` records who reviewed (human / llm / other).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..models import ProofStatus

TRUSTED_CHECKERS: set[str] = set()   # e.g. {"lean4", "coq"} once a checker is actually installed


class ProofStatusError(ValueError):
    pass


@dataclass
class TheoryEvidence:
    kind: str                       # finite_instance | counterexample | derivation | review | checker
    evidence_id: str
    assumptions_satisfied: Optional[bool] = None
    holds: Optional[bool] = None
    reviewer: Optional[str] = None  # human | llm | other
    checker: Optional[str] = None
    checker_exit_code: Optional[int] = None
    notes: str = ""


@dataclass
class TheoryState:
    statement: str
    scope: str                      # general | finite_instance
    status: ProofStatus = ProofStatus.unproven
    finite_instance_support: list[str] = field(default_factory=list)
    history: list[dict] = field(default_factory=list)


def apply(state: TheoryState, ev: TheoryEvidence) -> TheoryState:
    old = state.status
    if ev.kind == "counterexample":
        if ev.assumptions_satisfied is not True:
            raise ProofStatusError("a counterexample must satisfy every assumption of the statement")
        state.status = ProofStatus.disproved
    elif ev.kind == "finite_instance":
        if ev.holds is False:
            raise ProofStatusError("a failing instance is a counterexample; record it as such")
        state.finite_instance_support.append(ev.evidence_id)
        if state.scope == "finite_instance":
            state.status = ProofStatus.reviewed if ev.reviewer else ProofStatus.draft
        elif state.status == ProofStatus.unproven:
            state.status = ProofStatus.draft   # numbers support instances, not the theorem
    elif ev.kind == "derivation":
        if state.status not in (ProofStatus.disproved,):
            state.status = ProofStatus.gap_found if ev.holds is False else ProofStatus.draft
    elif ev.kind == "review":
        if ev.reviewer not in ("human", "llm", "other"):
            raise ProofStatusError("a review must state who reviewed it (human / llm / other)")
        if state.status in (ProofStatus.draft, ProofStatus.gap_found):
            state.status = ProofStatus.reviewed if ev.holds else ProofStatus.gap_found
    elif ev.kind == "checker":
        if ev.checker not in TRUSTED_CHECKERS or ev.checker_exit_code != 0:
            raise ProofStatusError("formally_verified requires a passing trusted proof checker run")
        state.status = ProofStatus.formally_verified
    else:
        raise ProofStatusError(f"unknown theory evidence kind {ev.kind}")
    if state.status == ProofStatus.formally_verified and ev.kind != "checker":
        raise ProofStatusError("only a checker can produce formally_verified")
    state.history.append({"from": old.value, "to": state.status.value, "evidence": ev.evidence_id, "kind": ev.kind})
    return state
