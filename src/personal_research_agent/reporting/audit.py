"""Claim/evidence audit and the writing-context filter (plan §10, M7, T15).

Checks are programmatic and cannot be waived by a model: missing sources, wrong protocol or
revision, artifacts whose hash changed, fixture contamination, unverified evidence, and claims
broader than their evidence (a general statement backed only by finite instances).
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ..models import Claim, Evidence, EvidenceKind, EvidenceLink, LinkRelation, VerificationStatus, sha256_text

if TYPE_CHECKING:  # pragma: no cover
    from ..controller import Controller


def check_claim(claim: Claim, links: dict[str, EvidenceLink], evidence: dict[str, Evidence], run_dir: Path) -> list[str]:
    f: list[str] = []
    if not claim.evidence_link_ids:
        f.append("no evidence link")
    support, refute = [], []
    for lid in claim.evidence_link_ids:
        link = links.get(lid)
        if link is None:
            f.append(f"unresolvable link {lid}")
            continue
        if link.candidate_revision_id != claim.candidate_revision_id:
            f.append(f"link {lid} belongs to revision {link.candidate_revision_id}, claim is on {claim.candidate_revision_id}")
        ev = evidence.get(link.evidence_id)
        if ev is None:
            f.append(f"missing evidence {link.evidence_id}")
            continue
        if ev.namespace == "fixture":
            f.append(f"fixture evidence {ev.id} cannot support a research claim")
        if ev.verification_status != VerificationStatus.verified:
            f.append(f"evidence {ev.id} is {ev.verification_status.value}")
        if claim.protocol_id and ev.protocol_version and not ev.protocol_version.startswith(f"{claim.protocol_id}@"):
            f.append(f"evidence {ev.id} produced under {ev.protocol_version}, claim protocol {claim.protocol_id}")
        if ev.artifact_path:
            path = run_dir / ev.artifact_path
            if not path.exists():
                f.append(f"artifact missing: {ev.artifact_path}")
            elif sha256_text(path.read_text(encoding="utf-8")) != ev.content_hash:
                f.append(f"artifact hash changed: {ev.artifact_path}")
        (support if link.relation == LinkRelation.supports else refute if link.relation == LinkRelation.refutes else []).append(ev)
    if claim.status == "refuted" and not any(e.kind == EvidenceKind.counterexample for e in refute):
        f.append("refuted without a verified counterexample")
    if claim.status == "supported" and claim.scope == "general":
        f.append("over-broad: a general statement marked supported on finite-instance evidence")
    return f


def audit_claims(ctrl: "Controller") -> list[Claim]:
    links = {l.id: l for l in ctrl.store.list(EvidenceLink)}
    evidence = {e.id: e for e in ctrl.store.list(Evidence)}
    out = []
    for claim in ctrl.store.list(Claim):
        findings = check_claim(claim, links, evidence, ctrl.run_dir)
        claim.audit_findings = sorted(set(claim.audit_findings) | set(findings))
        claim.audit_status = "failed" if findings else "passed"
        claim.usable_in_manuscript = not findings
        ctrl.store.update(claim, event="claim_audited", event_payload={"status": claim.audit_status,
                                                                       "findings": findings})
        out.append(claim)
    return out


def writing_context(store, run_dir: Path) -> dict:
    """Material allowed into a research note / theory draft: audited claims and the verified,
    non-fixture evidence they cite. Fixture data, stale links and unresolved refs are excluded."""
    links = {l.id: l for l in store.list(EvidenceLink)}
    evidence = {e.id: e for e in store.list(Evidence)}
    claims, used = [], {}
    for c in store.list(Claim):
        if c.audit_status != "passed" or not c.usable_in_manuscript:
            continue
        ok = True
        for lid in c.evidence_link_ids:
            link = links.get(lid)
            ev = evidence.get(link.evidence_id) if link else None
            if ev is None or ev.namespace == "fixture" or ev.verification_status != VerificationStatus.verified:
                ok = False
                break
            used[ev.id] = ev
        if ok:
            claims.append(c)
    return {"claims": claims, "evidence": list(used.values())}
