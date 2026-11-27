"""Versioned data contracts (plan §4).

Every persisted object has ``schema_version``, a stable ``id``, ``created_at`` and an origin.
Validators here enforce the contract rules that do not need the database (e.g. an unknown
assessment has ``judgment=None``); cross-object rules live in ``store.py`` and ``integrity.py``.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any, ClassVar, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = 1


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def stable_hash(obj: Any) -> str:
    return sha256_text(canonical_json(obj))


# --------------------------------------------------------------------------- enums
class ExecutionOrigin(str, Enum):
    fixture = "fixture"
    offline_local = "offline_local"
    live = "live"


class VerificationStatus(str, Enum):
    unverified = "unverified"
    verified = "verified"
    failed = "failed"
    not_applicable = "not_applicable"


class EpistemicStatus(str, Enum):
    fact = "fact"
    inference = "inference"
    hypothesis = "hypothesis"
    unknown = "unknown"


class FactBasis(str, Enum):
    input_given = "input_given"
    source_report = "source_report"
    tool_observation = "tool_observation"


class AssessmentState(str, Enum):
    known = "known"
    unknown = "unknown"
    disputed = "disputed"
    not_applicable = "not_applicable"


class Level(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


LEVEL_ORDER = {Level.low: 0, Level.medium: 1, Level.high: 2}


class TextStatus(str, Enum):
    abstract_only = "abstract_only"
    partial_text = "partial_text"
    full_text = "full_text"
    unavailable = "unavailable"


class EvidenceKind(str, Enum):
    literature_report = "literature_report"      # what a paper reports (not reproduced)
    computation = "computation"                  # this system computed it
    derivation = "derivation"                    # a written derivation / proof step
    counterexample = "counterexample"            # a checked counterexample
    model_inference = "model_inference"          # an LLM inference; never an observation
    input_given = "input_given"
    backend_artifact = "backend_artifact"        # produced by a research backend run


class LinkRelation(str, Enum):
    supports = "supports"
    refutes = "refutes"
    inconclusive = "inconclusive"
    context = "context"


class ActionPurpose(str, Enum):
    information_gathering = "information_gathering"
    preliminary_check = "preliminary_check"
    formal_research = "formal_research"
    audit = "audit"
    reporting = "reporting"


class ActionStatus(str, Enum):
    planned = "planned"
    reserved = "reserved"
    running = "running"
    succeeded = "succeeded"        # ran; includes negative scientific results
    no_change = "no_change"        # ran; produced no new information
    failed = "failed"              # execution error (not a scientific refutation)
    skipped_budget = "skipped_budget"
    skipped_duplicate = "skipped_duplicate"


TERMINAL_ACTION_STATUSES = {
    ActionStatus.succeeded, ActionStatus.no_change, ActionStatus.failed,
    ActionStatus.skipped_budget, ActionStatus.skipped_duplicate,
}


class OperationStatus(str, Enum):
    created = "created"
    running = "running"
    paused = "paused"
    blocked_dependency = "blocked_dependency"
    completed = "completed"
    failed = "failed"


class PlanningOutcome(str, Enum):
    recommended = "recommended"
    no_viable_candidate = "no_viable_candidate"
    inconclusive = "inconclusive"
    not_run = "not_run"


class ResearchOutcome(str, Enum):
    supported = "supported"
    refuted = "refuted"
    inconclusive = "inconclusive"
    not_run = "not_run"


class ManuscriptStatus(str, Enum):
    not_run = "not_run"
    not_generated = "not_generated"
    draft = "draft"
    evidence_checked = "evidence_checked"
    ready_for_human_review = "ready_for_human_review"


class StopReason(str, Enum):
    evidence_sufficient = "evidence_sufficient"
    all_candidates_rejected = "all_candidates_rejected"
    budget_exhausted = "budget_exhausted"
    max_rounds_reached = "max_rounds_reached"
    max_no_change_reached = "max_no_change_reached"
    no_available_action = "no_available_action"
    provider_failure = "provider_failure"
    user_cancelled = "user_cancelled"


class ProofStatus(str, Enum):
    unproven = "unproven"
    draft = "draft"
    gap_found = "gap_found"
    reviewed = "reviewed"
    formally_verified = "formally_verified"
    disproved = "disproved"


class StudyStage(str, Enum):
    pilot = "pilot"
    formal = "formal"


class ResearchBranch(str, Enum):
    auto = "auto"
    theoretical = "theoretical"
    empirical = "empirical"
    mixed = "mixed"


class PairwiseDecision(str, Enum):
    prefer_a = "prefer_a"
    prefer_b = "prefer_b"
    tie = "tie"
    insufficient_evidence = "insufficient_evidence"


class Phase(str, Enum):
    initialize = "initialize"
    clarify = "clarify"
    map_field = "map_field"
    retrieve_and_read = "retrieve_and_read"
    propose = "propose"
    assess = "assess"
    acquire_evidence = "acquire_evidence"
    select = "select"
    execute_research = "execute_research"
    audit = "audit"
    write = "write"
    finish = "finish"


PHASE_ORDER = list(Phase)


# --------------------------------------------------------------------------- base
class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=False)

    schema_version: int = SCHEMA_VERSION
    id: str
    created_at: str = Field(default_factory=utcnow)
    origin: ExecutionOrigin
    source: str = Field(description="provenance: who/what produced this record")

    @property
    def record_kind(self) -> str:
        return type(self).__name__


# --------------------------------------------------------------------------- profile
class ProfileItem(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str
    scope: Optional[str] = None
    source: str
    verified: bool = False


class TasteRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    rule: str
    applies_when: str
    source: str
    confirmed_by_user: bool = False


class ResearcherProfile(Record):
    researcher: str
    expertise: list[ProfileItem]
    research_interests: list[dict[str, Any]] = []
    taste_rules: list[TasteRule] = []
    constraints: list[dict[str, Any]] = []
    profile_hash: str


# --------------------------------------------------------------------------- problem
class Interpretation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    description: str
    objects: list[str] = []
    variables: list[str] = []
    information_conditions: list[str] = []
    working_assumptions: list[str] = []
    target_conclusion: Optional[str] = None   # mechanism / equivalence_conditions / counterexample / ...
    status: Literal["open", "kept", "rejected_too_broad", "merged"] = "open"
    rejection_reason: Optional[str] = None


class Concept(Record):
    canonical_name: str
    aliases: list[str] = []
    role: str
    # Personal familiarity and field importance are separate fields (plan §4.2).
    existing_capability: Optional[Level] = None
    existing_capability_basis: Optional[str] = None
    field_importance: Optional[Level] = None
    field_importance_basis: Optional[str] = None
    knowledge_gap: Optional[str] = None
    evidence_ids: list[str] = []


class ProblemSpec(Record):
    task_id: str
    idea_text: str
    interpretations: list[Interpretation]
    field_problems: list[dict[str, Any]] = []
    metrics_status: Literal["undecided", "proposed", "frozen"] = "undecided"
    metrics: dict[str, Any] = {}
    open_items: list[str] = []
    query_result_id: Optional[str] = None


# --------------------------------------------------------------------------- literature
class PaperRecord(Record):
    canonical_id: str                  # "doi:..." | "arxiv:<id>" | "local:<sha>" | "fixture:..."
    title: str
    authors: list[str] = []
    year: Optional[int] = None
    doi: Optional[str] = None
    arxiv_id: Optional[str] = None
    arxiv_version: Optional[str] = None
    url: Optional[str] = None
    retrieved_at: str = Field(default_factory=utcnow)
    provider: str
    text_status: TextStatus = TextStatus.abstract_only
    read_scope: list[str] = []          # what was actually read: "abstract", "p.3", "Sec. 2" ...
    document_path: Optional[str] = None
    document_sha256: Optional[str] = None
    abstract: Optional[str] = None
    keywords: list[str] = []
    verification_status: VerificationStatus = VerificationStatus.unverified


class Evidence(Record):
    kind: EvidenceKind
    namespace: Literal["fixture", "computation", "literature", "backend", "input"]
    source_id: str                      # PaperRecord / artifact / input id
    source_version: str
    locator: Optional[str]              # page/section/theorem/table, or artifact path
    content_hash: str
    observation: str
    depends_on: list[str] = []
    same_source_group: str              # identical results reported/mirrored share a group
    verification_status: VerificationStatus = VerificationStatus.unverified
    artifact_path: Optional[str] = None
    run_ref: Optional[str] = None
    protocol_version: Optional[str] = None
    dedup_key: str = ""

    @model_validator(mode="after")
    def _derive(self) -> "Evidence":
        if not self.dedup_key:
            self.dedup_key = stable_hash([self.source_id, self.source_version, self.locator, self.content_hash])
        if self.kind == EvidenceKind.model_inference and self.verification_status == VerificationStatus.verified:
            raise ValueError("an LLM inference cannot be marked as a verified observation")
        return self


class EvidenceLink(Record):
    evidence_id: str
    candidate_revision_id: str
    claim_id: str
    relation: LinkRelation
    applicability: str


# --------------------------------------------------------------------------- candidates
class CandidateRevision(Record):
    candidate_id: str
    version: int
    parent_revision_id: Optional[str] = None
    title: str
    problem_scope: str
    hypothesis: str
    mechanism: str
    increment: str
    nearest_neighbors: list[str] = []       # PaperRecord ids
    claims: list[dict[str, Any]] = []        # [{"id": "C1", "statement": ..., "scope": "general|finite_instance|conditional"}]
    validation_protocol: dict[str, Any] = {}
    abandon_conditions: list[str] = []
    unknown_ids: list[str] = []
    research_branch: ResearchBranch = ResearchBranch.auto
    key_fields_hash: str = ""
    change_reason: Optional[str] = None
    status: Literal["active", "rejected", "superseded"] = "active"

    KEY_FIELDS: ClassVar[tuple[str, ...]] = ("problem_scope", "hypothesis", "mechanism", "increment", "validation_protocol", "claims")

    @model_validator(mode="after")
    def _key_hash(self) -> "CandidateRevision":
        self.key_fields_hash = stable_hash({f: getattr(self, f) for f in self.KEY_FIELDS})
        return self


# --------------------------------------------------------------------------- assessments
class Assessment(Record):
    subject_type: Literal["candidate", "concept", "link"]
    subject_id: str
    subject_revision: Optional[str] = None
    dimension: str                       # scientific_value | novelty | feasibility | theory_difficulty | ...
    state: AssessmentState
    judgment: Optional[Level] = None
    evidence_ids: list[str] = []
    contrary_evidence_ids: list[str] = []
    rationale: str
    rubric_version: str = "rubric-v1"
    conditional_on: list[str] = []
    supersedes: Optional[str] = None

    @model_validator(mode="after")
    def _unknown_is_null(self) -> "Assessment":
        if self.state in (AssessmentState.unknown, AssessmentState.not_applicable) and self.judgment is not None:
            raise ValueError(f"assessment state={self.state.value} requires judgment=None (unknown is not a low score)")
        if self.state == AssessmentState.known and self.judgment is None:
            raise ValueError("a known assessment needs a judgment")
        if self.state == AssessmentState.known and not self.evidence_ids:
            raise ValueError("a known assessment must cite evidence")
        return self


# Dimensions: scientific value and personal familiarity are stored apart.
SCIENCE_DIMENSIONS = ("scientific_value", "novelty", "feasibility")
DIFFICULTY_DIMENSIONS = ("theory_difficulty", "experiment_difficulty", "engineering_difficulty", "learning_cost")
PERSONAL_DIMENSIONS = ("personal_fit",)


class Unknown(Record):
    question: str
    affects: list[str] = []               # candidate ids / gates
    importance: Level
    available_checks: list[dict[str, Any]] = []   # [{"action_type":..., "purpose":..., "cost": {...}}]
    status: Literal["open", "resolved", "unresolvable_in_budget"] = "open"
    resolution: Optional[str] = None
    missing_material: Optional[str] = None


# --------------------------------------------------------------------------- actions & specs
class ResearchAction(Record):
    action_type: str
    purpose: ActionPurpose
    target_unknown_id: Optional[str] = None
    candidate_revision_ids: list[str] = []
    inputs: dict[str, Any] = {}
    input_fingerprint: str
    cost_cap: dict[str, float] = {}
    rationale: dict[str, Any] = {}       # target_unknown, why, branches, cost, priority reason
    status: ActionStatus = ActionStatus.planned
    attempt: int = 1
    artifacts: list[str] = []
    usage: dict[str, float] = {}
    error: Optional[str] = None
    result_summary: Optional[str] = None
    new_information: Optional[bool] = None
    round: int = 0


class ResearchSpec(Record):
    study_stage: StudyStage
    candidate_revision_id: str
    protocol_id: str
    protocol_version: int
    protocol_hash: str = ""
    research_branch: ResearchBranch
    hypothesis: str
    falsification: str
    baselines: list[str] = []
    environment: dict[str, Any] = {}
    resources: dict[str, Any] = {}
    evaluation: dict[str, Any] = {}
    continue_criteria: list[str] = []
    abandon_criteria: list[str] = []
    # theory branch (plan §8.1)
    theorem_statement: Optional[str] = None
    assumptions: list[str] = []
    policy_information_class: Optional[str] = None
    proof_obligations: list[dict[str, Any]] = []
    counterexample_search_plan: Optional[dict[str, Any]] = None
    review_method: Optional[str] = None
    missing: list[str] = []
    frozen: bool = True

    @model_validator(mode="after")
    def _hash(self) -> "ResearchSpec":
        if self.research_branch == ResearchBranch.auto:
            raise ValueError("research_branch must be resolved (theoretical/empirical/mixed) before a spec is frozen")
        body = self.model_dump(exclude={"protocol_hash", "created_at", "id"}, mode="json")
        self.protocol_hash = stable_hash(body)
        return self


class Claim(Record):
    candidate_revision_id: str
    protocol_id: Optional[str] = None
    protocol_version: Optional[int] = None
    statement: str
    scope: Literal["general", "finite_instance", "conditional", "negative"]
    evidence_link_ids: list[str] = []
    audit_status: Literal["unaudited", "passed", "failed"] = "unaudited"
    usable_in_manuscript: bool = False
    status: Literal["supported", "refuted", "inconclusive", "unproven"] = "unproven"
    study_stage: Optional[StudyStage] = None
    proof_status: Optional[ProofStatus] = None
    proof_history: list[dict[str, Any]] = []
    audit_findings: list[str] = []


class BudgetUsage(Record):
    run_id: str
    action_id: Optional[str]
    attempt: int = 1
    backend_run_id: Optional[str] = None
    dimension: str
    reserved: float = 0.0
    actual: Optional[float] = None
    state: Literal["reserved", "settled", "released"] = "reserved"
    cost_type: Literal["fixture", "actual", "estimated", "unpriced", "measured"] = "measured"


class ModelBinding(Record):
    requested_product: str
    provider: str
    api: str
    resolved_model: str
    reasoning_mode: str
    requested_effort: Optional[str] = None
    effective_effort: Optional[str] = None      # unknown until a response reports it
    sdk_name: str
    sdk_version: Optional[str]
    mapping_verified_on: str
    mapping_sources: list[str]
    mapping_check: dict[str, Any]               # how/when the mapping was (re)checked
    binding_hash: str = ""
    runtime_metadata: list[dict[str, Any]] = []

    @model_validator(mode="after")
    def _hash(self) -> "ModelBinding":
        self.binding_hash = stable_hash({
            "provider": self.provider, "api": self.api, "model": self.resolved_model,
            "reasoning_mode": self.reasoning_mode, "effort": self.requested_effort,
        })
        return self


class TaskQuerySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_type: str
    template_version: str
    questions: list[dict[str, str]]
    input_refs: list[str]
    input_versions: dict[str, str] = {}
    allowed_tools: list[str] = []
    output_schema_name: str
    context_scope: str
    call_budget: dict[str, int]


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question_id: str
    statement: Optional[str]
    epistemic_status: EpistemicStatus
    basis_type: Optional[FactBasis] = None
    source_refs: list[dict[str, Any]] = []      # [{"source_id":..., "locator":..., "read_scope":...}]
    premise_ids: list[str] = []
    scope: Optional[str] = None
    contrary_evidence_refs: list[str] = []
    missing_information: Optional[str] = None
    prediction: Optional[str] = None
    falsification: Optional[str] = None

    @model_validator(mode="after")
    def _epistemics(self) -> "Answer":
        s = self.epistemic_status
        if s == EpistemicStatus.unknown:
            if self.statement is not None:
                raise ValueError(f"{self.question_id}: unknown answers carry statement=null")
            if not self.missing_information:
                raise ValueError(f"{self.question_id}: unknown answers must say what is missing")
        elif s == EpistemicStatus.fact:
            if self.basis_type is None:
                raise ValueError(f"{self.question_id}: a fact needs basis_type")
            if self.basis_type != FactBasis.input_given and not self.source_refs:
                raise ValueError(f"{self.question_id}: a fact needs source_refs")
            if any(not r.get("locator") for r in self.source_refs if self.basis_type == FactBasis.source_report):
                raise ValueError(f"{self.question_id}: literature facts need a real locator")
        elif s == EpistemicStatus.inference:
            if not self.premise_ids and not self.source_refs:
                raise ValueError(f"{self.question_id}: an inference must list its premises")
        elif s == EpistemicStatus.hypothesis:
            if not self.prediction or not self.falsification:
                raise ValueError(f"{self.question_id}: a hypothesis needs a testable prediction and a falsification condition")
        if s != EpistemicStatus.fact and self.basis_type is not None:
            raise ValueError(f"{self.question_id}: basis_type is only for facts")
        return self


class QueryResult(Record):
    query_id: str
    task_type: str
    template_version: str
    input_refs: list[str]
    input_fingerprint: str
    candidate_revision_id: Optional[str] = None
    protocol_id: Optional[str] = None
    protocol_version: Optional[int] = None
    execution_origin: ExecutionOrigin
    model_binding_id: Optional[str] = None
    answers: list[Answer]
    payload: dict[str, Any] = {}
    derived_object_ids: list[str] = []
    unresolved: list[str] = []
    repair_attempts: int = 0

    @model_validator(mode="after")
    def _binding(self) -> "QueryResult":
        if self.execution_origin == ExecutionOrigin.live and not self.model_binding_id:
            raise ValueError("a live QueryResult must reference the run's ModelBinding")
        if self.execution_origin == ExecutionOrigin.fixture and self.model_binding_id:
            raise ValueError("fixture results must not reference a real ModelBinding")
        return self


class RankingSnapshot(Record):
    round: int
    preferred_candidates: list[str] = []
    ties: list[list[str]] = []
    unresolved_candidates: list[str] = []
    rejected_candidates: dict[str, str] = {}
    pairwise_decisions: list[dict[str, Any]] = []
    changed_from_previous: list[dict[str, Any]] = []   # [{"change":..., "evidence_ids": [...], "assessment_ids": [...]}]
    strategy: str


class DecisionRun(Record):
    run_id: str
    task_id: str
    config_snapshot: dict[str, Any]
    config_hash: str
    profile_hash: str
    prompt_hashes: dict[str, str]
    code_version: str
    strategy: str
    phase: Phase = Phase.initialize
    round: int = 0
    no_change_rounds: int = 0
    operation_status: OperationStatus = OperationStatus.created
    planning_outcome: PlanningOutcome = PlanningOutcome.not_run
    research_outcome: ResearchOutcome = ResearchOutcome.not_run
    manuscript_status: ManuscriptStatus = ManuscriptStatus.not_run
    manuscript_reason: Optional[str] = None
    stop_reason: Optional[StopReason] = None
    model_binding_id: Optional[str] = None
    recommended_candidate_revision_id: Optional[str] = None
    deadline_epoch: float
    wall_used_seconds: float = 0.0
    error: Optional[str] = None
    notes: list[str] = []

    @field_validator("strategy")
    @classmethod
    def _strategy(cls, v: str) -> str:
        if v not in ("one_shot", "evidence_loop", "personalized_loop"):
            raise ValueError(f"unknown strategy {v}")
        return v


ALL_RECORD_TYPES: dict[str, type[Record]] = {
    cls.__name__: cls for cls in (
        ResearcherProfile, Concept, ProblemSpec, PaperRecord, Evidence, EvidenceLink, CandidateRevision,
        Assessment, Unknown, ResearchAction, ResearchSpec, Claim, BudgetUsage, ModelBinding, QueryResult,
        RankingSnapshot, DecisionRun,
    )
}

# Records that may be updated in place (status fields). Everything else is append-only:
# a change creates a new record (new revision / superseding assessment).
MUTABLE_KINDS = {"DecisionRun", "ResearchAction", "Unknown", "PaperRecord", "Claim", "CandidateRevision"}
