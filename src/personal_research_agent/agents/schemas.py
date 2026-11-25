"""Typed payloads returned by each task_type. They map onto the §4 business objects; the
controller validates them and commits the derived records itself."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from ..models import Answer, AssessmentState, Level, LinkRelation, ProofStatus


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InterpretationOut(_M):
    id: str
    description: str
    objects: list[str] = []
    variables: list[str] = []
    information_conditions: list[str] = []
    working_assumptions: list[str] = []
    target_conclusion: Optional[str] = None
    status: Literal["open", "kept", "rejected_too_broad", "merged"] = "open"
    rejection_reason: Optional[str] = None


class ConceptOut(_M):
    canonical_name: str
    aliases: list[str] = []
    role: str
    search_terms: list[str] = []
    linked_question: Optional[str] = None


class UnknownOut(_M):
    key: str
    question: str
    affects: list[str] = []
    importance: Level
    available_checks: list[dict[str, Any]] = []
    missing_material: Optional[str] = None


class ClarifyPayload(_M):
    interpretations: list[InterpretationOut]
    concepts: list[ConceptOut]
    unknowns: list[UnknownOut] = []
    metrics_status: Literal["undecided", "proposed"] = "undecided"
    search_queries: list[dict[str, str]] = []   # [{"query":..., "purpose": "bottleneck|nearest|refuting|user_method_link"}]


class LinkOut(_M):
    candidate_key: str
    claim_id: str
    relation: LinkRelation
    applicability: str


class EvidenceOut(_M):
    locator: str
    observation: str
    kind: Literal["literature_report"] = "literature_report"
    links: list[LinkOut] = []


class ReadPaperPayload(_M):
    paper_id: str
    reading_status: Literal["complete_for_questions", "partial", "insufficient_material"]
    evidence: list[EvidenceOut] = []
    remaining_questions: list[str] = []


class FieldProblemOut(_M):
    id: str
    problem: str
    evidence_refs: list[str] = []
    metrics: list[str] = []
    baselines: list[str] = []
    status: Literal["consensus_background", "disputed", "single_source", "hypothesis"]


class MapFieldPayload(_M):
    field_problems: list[FieldProblemOut]
    idea_maps_to: list[str] = []
    missing_for_link: Optional[str] = None


class AssessmentOut(_M):
    subject_key: str                 # candidate key, concept name, or "link:<n>"
    subject_type: Literal["candidate", "concept", "link"]
    dimension: str
    state: AssessmentState
    judgment: Optional[Level] = None
    evidence_refs: list[str] = []
    contrary_refs: list[str] = []
    rationale: str
    conditional_on: list[str] = []


class CorrespondenceOut(_M):
    profile_item: str
    mechanism_map: str
    conditions: list[str] = []
    status: Literal["supported", "hypothesis", "unknown", "contradicted"]
    evidence_refs: list[str] = []


class LinkBackgroundPayload(_M):
    correspondences: list[CorrespondenceOut] = []
    assessments: list[AssessmentOut] = []
    learning_tasks: list[dict[str, Any]] = []
    taste_rules_applied: list[dict[str, Any]] = []


class CandidateOut(_M):
    key: str                           # stable candidate id, e.g. "CAND-A"
    title: str
    problem_scope: str
    hypothesis: str
    mechanism: str
    increment: str
    nearest_neighbors: list[str] = []
    claims: list[dict[str, Any]]
    validation_protocol: dict[str, Any] = {}
    abandon_conditions: list[str]
    research_branch: Literal["theoretical", "empirical", "mixed", "auto"]
    cheapest_check: dict[str, Any] = {}
    epistemic_status: Literal["hypothesis"] = "hypothesis"


class ProposePayload(_M):
    candidates: list[CandidateOut]
    no_alternative_reason: Optional[str] = None
    unknowns: list[UnknownOut] = []


class RevisionProposal(_M):
    candidate_key: str
    change_reason: str
    changes: dict[str, Any]            # new values for key fields
    recheck_evidence_refs: list[str] = []


class ClaimCheckOut(_M):
    claim_id: str
    status: Literal["covered", "possibly_distinct", "contradicted", "unresolved"]
    source_refs: list[str] = []
    conditions: list[str] = []
    counterexample_status: Literal["verified_counterexample", "construction_to_check", "proof_attempt_failed",
                                   "insufficient_evidence", "none_found_in_scope"] = "insufficient_evidence"
    checked_scope: str


class CheckCandidatePayload(_M):
    candidate_key: str
    claim_checks: list[ClaimCheckOut]
    assessments: list[AssessmentOut] = []
    unknowns: list[UnknownOut] = []
    revision_proposals: list[RevisionProposal] = []


class ObligationOut(_M):
    id: str
    statement: str
    depends_on: list[str] = []
    status: Literal["open", "discharged_by_derivation", "gap", "refuted"]
    evidence_refs: list[str] = []


class CheckTheoryPayload(_M):
    candidate_key: str
    quantifiers: str
    policy_information_class: str
    obligations: list[ObligationOut]
    proof_status: ProofStatus
    review_method: Literal["llm", "human", "checker", "none"]
    counterexample_status: str


class NextActionOut(_M):
    action_type: str
    purpose: Literal["information_gathering", "preliminary_check", "formal_research", "audit", "reporting"]
    target_unknown_key: Optional[str] = None
    candidate_keys: list[str] = []
    inputs: dict[str, Any] = {}
    expected_branches: list[dict[str, str]] = []
    cost_cap: dict[str, float] = {}
    why_now: str


class UpdateDecisionPayload(_M):
    new_evidence_refs: list[str] = []
    duplicate_evidence_refs: list[str] = []
    assessment_updates: list[AssessmentOut] = []
    ranking_changes: list[dict[str, Any]] = []
    next_action: Optional[NextActionOut] = None
    stop_recommendation: dict[str, Any] = Field(default_factory=dict)
    revision_proposals: list[RevisionProposal] = []


class ResearchSpecPayload(_M):
    candidate_key: str
    study_stage: Literal["pilot", "formal"]
    research_branch: Literal["theoretical", "empirical", "mixed"]
    hypothesis: str
    falsification: str
    baselines: list[str] = []
    environment: dict[str, Any] = {}
    evaluation: dict[str, Any] = {}
    resources: dict[str, Any] = {}
    continue_criteria: list[str] = []
    abandon_criteria: list[str] = []
    theorem_statement: Optional[str] = None
    assumptions: list[str] = []
    policy_information_class: Optional[str] = None
    proof_obligations: list[dict[str, Any]] = []
    counterexample_search_plan: Optional[dict[str, Any]] = None
    review_method: Optional[str] = None
    missing: list[str] = []


class GenericPayload(_M):
    model_config = ConfigDict(extra="allow")


PAYLOADS: dict[str, type[BaseModel]] = {
    "clarify_problem": ClarifyPayload,
    "read_paper": ReadPaperPayload,
    "map_field": MapFieldPayload,
    "link_background": LinkBackgroundPayload,
    "propose_candidates": ProposePayload,
    "check_candidate": CheckCandidatePayload,
    "check_theory": CheckTheoryPayload,
    "check_claim_evidence": GenericPayload,
    "update_decision": UpdateDecisionPayload,
    "make_research_spec": ResearchSpecPayload,
    "compress_summary": GenericPayload,
}


class Envelope(_M):
    answers: list[Answer]
    payload: dict[str, Any]


def output_schema(task_type: str) -> dict[str, Any]:
    """One self-contained JSON Schema (root-level $defs) for the envelope of this task_type."""
    from pydantic import create_model

    model = create_model(f"{task_type}_output", __config__=ConfigDict(extra="forbid"),
                         answers=(list[Answer], ...), payload=(PAYLOADS[task_type], ...))
    return model.model_json_schema()
