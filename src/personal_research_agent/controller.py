"""Explicit state machine for one research run (plan §6, §7).

Phases: initialize -> clarify -> map_field -> retrieve_and_read -> propose -> assess
        <-> acquire_evidence -> select -> execute_research -> audit -> write -> finish

The model proposes; this controller validates and commits. Every action has an input
fingerprint, a budget reservation, a recorded outcome and a checkpoint, so ``resume`` neither
repeats completed work nor charges it twice.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

import yaml

from . import profiles as prof
from .agents.binding import S11, S12, S13, build_binding, sdk_mapping_evidence
from .agents.gateway import LLMGateway
from .agents.providers import FixtureProvider, OpenAIResponsesProvider, ProviderError
from .agents.query import QueryInput, QueryRunner, QueryValidationError, RefResolver, prompt_hashes
from .backends.base import BackendError
from .backends.local import LocalBackend
from .budget import Budget, BudgetExceeded
from .config import PROJECT_ROOT, ConfigError, RunConfig, TaskSpec, load_config, load_profile, load_task
from .decision import rules
from .decision.ranking import latest_assessments, rank
from .literature.base import Document
from .literature.providers import ArxivProvider, FixtureLiteratureProvider, LiteratureError, OpenAlexProvider
from .literature.service import LiteratureCache, LiteratureService, load_document_for
from .models import (
    PHASE_ORDER, ActionPurpose, ActionStatus, Assessment, AssessmentState, CandidateRevision, Claim, Concept,
    DecisionRun, Evidence, EvidenceKind, EvidenceLink, ExecutionOrigin, Interpretation, Level, LinkRelation,
    ManuscriptStatus, ModelBinding, OperationStatus, PaperRecord, Phase, PlanningOutcome, ProblemSpec,
    ProofStatus, QueryResult, RankingSnapshot, ResearchAction, ResearchBranch, ResearchOutcome,
    ResearchSpec, ResearcherProfile, StopReason, StudyStage, TERMINAL_ACTION_STATUSES, Unknown,
    VerificationStatus, sha256_text, stable_hash, utcnow,
)
from .netguard import forbid_network
from .research.theory import ProofStatusError, TheoryEvidence, TheoryState, apply as apply_theory
from .store import Store, new_id

FIXTURES = PROJECT_ROOT / "tests" / "fixtures"
RUNS_ROOT = PROJECT_ROOT / "runs"


class RunFailure(RuntimeError):
    pass


class BlockedDependency(RuntimeError):
    pass


def code_version() -> str:
    try:
        sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, capture_output=True, text=True,
                             timeout=5).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "src", "prompts"], cwd=PROJECT_ROOT,
                               capture_output=True, text=True, timeout=5).stdout.strip()
        return (sha or "unknown") + ("+dirty" if dirty else "")
    except Exception:
        return "unknown"


@dataclass
class ActionOutcome:
    status: ActionStatus
    summary: str
    new_information: bool
    artifacts: list[str]


class Controller:
    # ================================================================== construction
    def __init__(self, run_dir: Path, store: Store, config: RunConfig, task: TaskSpec, profile: ResearcherProfile,
                 drun: DecisionRun, binding: Optional[ModelBinding], log: Callable[[str], None] = None):
        self.run_dir, self.store, self.config, self.task, self.profile = run_dir, store, config, task, profile
        self.drun, self.binding = drun, binding
        self.log = log or (lambda m: print(m, file=sys.stderr))
        self.session_start = time.time()
        self.drun.deadline_epoch = self.session_start + max(0.0, config.limits.run_wall_seconds - drun.wall_used_seconds)
        self.budget = Budget(store, config.limits.model_dump(), self.drun.deadline_epoch)
        self.origin = config.origin
        self.resolver = RefResolver(store, run_dir)
        self.local = LocalBackend()
        self._last_status = 0.0
        self._gateway: Optional[LLMGateway] = None
        self._runner: Optional[QueryRunner] = None
        self._lit: Optional[LiteratureService] = None

    @classmethod
    def create(cls, task_path: Path, profile_path: Path, config_path: Path, run_id: str,
               strategy: Optional[str] = None, runs_root: Path = RUNS_ROOT) -> "Controller":
        config = load_config(config_path)
        task = load_task(task_path)
        profile = load_profile(profile_path)
        if strategy:
            config.decision["strategy"] = strategy
        run_dir = runs_root / run_id
        if (run_dir / "state.sqlite").exists():
            raise ConfigError(f"run {run_id} already exists; use `pra resume --run-id {run_id}`")
        run_dir.mkdir(parents=True, exist_ok=True)
        snapshot = {"config": config.model_dump(mode="json"), "task": task.model_dump(mode="json"),
                    "profile_path": str(profile_path), "profile_raw": yaml.safe_load(Path(profile_path).read_text()),
                    "task_path": str(task_path), "config_path": str(config_path),
                    "task_file_sha256": sha256_text(Path(task_path).read_text(encoding="utf-8"))}
        (run_dir / "config_snapshot.json").write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")
        store = Store(run_dir / "state.sqlite", run_id)
        binding = None
        if config.llm.provider == "openai":
            binding = build_binding(config.llm, run_id, cls.check_mapping(config))
        drun = DecisionRun(
            id=f"run_{run_id}", origin=config.origin, source="pra run", run_id=run_id, task_id=task.task_id,
            config_snapshot=snapshot, config_hash=stable_hash(snapshot["config"]), profile_hash=profile.profile_hash,
            prompt_hashes=prompt_hashes(), code_version=code_version(), strategy=config.decision["strategy"],
            deadline_epoch=time.time() + config.limits.run_wall_seconds,
            model_binding_id=binding.id if binding else None,
        )
        with store.tx():
            store.put(drun, event="run_created", event_payload={"strategy": drun.strategy, "mode": config.mode})
            store.put(profile, event="profile_loaded")
            if binding:
                store.put(binding, event="model_binding_frozen", event_payload={"binding_hash": binding.binding_hash})
        return cls(run_dir, store, config, task, profile, drun, binding)

    @classmethod
    def open(cls, run_id: str, runs_root: Path = RUNS_ROOT, check_drift: bool = True) -> "Controller":
        run_dir = runs_root / run_id
        if not (run_dir / "state.sqlite").exists():
            raise ConfigError(f"no run {run_id} under {runs_root}")
        store = Store(run_dir / "state.sqlite", run_id)
        drun = store.require(f"run_{run_id}", DecisionRun)
        snap = drun.config_snapshot
        config = RunConfig.model_validate(snap["config"])
        task = TaskSpec.model_validate(snap["task"])
        profile = store.require(f"profile_{snap['profile_raw']['profile_id']}", ResearcherProfile)
        if check_drift:
            tp = Path(snap["task_path"])
            if tp.exists() and sha256_text(tp.read_text(encoding="utf-8")) != snap["task_file_sha256"]:
                store.event("task_drift_detected", {"task_path": str(tp)})
                raise ConfigError(f"task file {tp} changed since the run started (task drift); start a new run")
        binding = store.get(drun.model_binding_id) if drun.model_binding_id else None  # reused, never re-resolved
        return cls(run_dir, store, config, task, profile, drun, binding)  # type: ignore[arg-type]

    @staticmethod
    def check_mapping(config: RunConfig) -> dict[str, Any]:
        """Re-check the GPT-6 Pro mapping before a new live run: SDK declarations (offline) plus
        the official pages and the account's model endpoint when reachable."""
        out: dict[str, Any] = {"sdk": sdk_mapping_evidence(), "sources": [S11, S12, S13], "web": {}}
        try:
            import httpx

            for url in (S12, S13):
                try:
                    r = httpx.get(url, timeout=10, follow_redirects=True)
                    out["web"][url] = {"status": r.status_code, "mentions_mode_pro": '"pro"' in r.text or "mode=\"pro\"" in r.text}
                except Exception as exc:
                    out["web"][url] = {"error": type(exc).__name__}
        except ImportError:  # pragma: no cover
            pass
        key = os.environ.get(config.llm.credential_env)
        if key:
            try:
                import openai

                m = openai.OpenAI(api_key=key, max_retries=0, timeout=20).models.retrieve(config.llm.model)
                out["account_model_available"] = getattr(m, "id", None) == config.llm.model
            except Exception as exc:
                out["account_model_available"] = False
                out["account_check_error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
        else:
            out["account_model_available"] = None
            out["account_check_error"] = f"{config.llm.credential_env} not set"
        return out

    # ================================================================== lazily built services
    @property
    def gateway(self) -> LLMGateway:
        if self._gateway is None:
            if self.config.llm.provider == "fixture":
                provider = FixtureProvider(FIXTURES / "llm", self.task.task_id)
            else:
                assert self.binding is not None
                provider = OpenAIResponsesProvider(self.binding, self.config.llm.credential_env)
            self._gateway = LLMGateway(provider, self.store, self.budget, self.binding,
                                       max_retries=self.config.limits.max_retries_per_action,
                                       pricing=self.config.llm.pricing,
                                       request_timeout=self.config.llm.request_timeout_seconds,
                                       log=self.log)
        return self._gateway

    @property
    def runner(self) -> QueryRunner:
        if self._runner is None:
            self._runner = QueryRunner(self.gateway, self.store, self.run_dir, self.binding,
                                       max_output_tokens=self.config.llm.max_output_tokens_per_call)
        return self._runner

    @property
    def lit(self) -> LiteratureService:
        if self._lit is None:
            p = self.config.literature.provider
            if p == "fixture":
                provider: Any = FixtureLiteratureProvider(FIXTURES / "literature", self.task.task_id)
                cache = None
            elif p == "arxiv":
                provider = ArxivProvider(self.config.literature.request_timeout_seconds)
                cache = LiteratureCache(self.run_dir.parent / "_cache" / "literature.sqlite")
            else:
                mail = os.environ.get(self.config.literature.openalex_mailto_env or "", None)
                provider = OpenAlexProvider(self.config.literature.request_timeout_seconds, mail)
                cache = LiteratureCache(self.run_dir.parent / "_cache" / "literature.sqlite")
            self._lit = LiteratureService(provider, self.store, self.budget, self.run_dir, self.origin, cache)
        return self._lit

    # ================================================================== top level
    def run(self, until: Optional[str] = None, retry_failed: bool = False) -> DecisionRun:
        if retry_failed and self.drun.operation_status in (OperationStatus.failed, OperationStatus.blocked_dependency):
            self.store.event("run_reopened", {"previous_status": self.drun.operation_status.value,
                                              "previous_error": (self.drun.error or "")[:300]})
            self.drun.operation_status, self.drun.error = OperationStatus.paused, None
        self.store.acquire_lock()
        try:
            if self.config.mode == "offline_local":
                with forbid_network():
                    self._run(until)
            else:
                self._run(until)
        finally:
            self.drun.wall_used_seconds += time.time() - self.session_start
            self._save_run()
            self.store.release_lock()
        return self.drun

    def _run(self, until: Optional[str]) -> None:
        if self.drun.operation_status in (OperationStatus.completed, OperationStatus.failed):
            self.log(f"run {self.drun.run_id} is already {self.drun.operation_status.value}; nothing to do")
            return
        self._reconcile()
        self.drun.operation_status = OperationStatus.running
        self._save_run(event="run_session_started")
        handlers = {
            Phase.initialize: lambda: None, Phase.clarify: self.clarify, Phase.map_field: self.map_field,
            Phase.retrieve_and_read: self.retrieve_and_read, Phase.propose: self.propose, Phase.assess: self.assess,
            Phase.acquire_evidence: self.acquire_evidence, Phase.select: self.select,
            Phase.execute_research: self.execute_research, Phase.audit: self.audit, Phase.write: self.write,
            Phase.finish: self.finish,
        }
        try:
            while True:
                phase = self.drun.phase
                if until and PHASE_ORDER.index(phase) > PHASE_ORDER.index(Phase(until)):
                    self.drun.operation_status = OperationStatus.paused
                    self.drun.notes.append(f"paused before {phase.value} (--until {until})")
                    return
                self._status_line()
                next_phase = handlers[phase]()
                if phase == Phase.finish:
                    return
                self.drun.phase = next_phase or PHASE_ORDER[PHASE_ORDER.index(phase) + 1]
                self._save_run(event="phase_completed", payload={"phase": phase.value, "next": self.drun.phase.value})
        except BlockedDependency as exc:
            self._fail(OperationStatus.blocked_dependency, StopReason.provider_failure, str(exc))
        except RunFailure as exc:
            self._fail(OperationStatus.failed, None, str(exc))

    def _fail(self, status: OperationStatus, reason: Optional[StopReason], msg: str) -> None:
        self.drun.operation_status = status
        self.drun.stop_reason = reason or self.drun.stop_reason
        self.drun.error = msg
        if self.drun.planning_outcome == PlanningOutcome.not_run:
            self.drun.planning_outcome = PlanningOutcome.inconclusive
        self.store.event("run_stopped", {"status": status.value, "error": msg[:500]})
        try:  # a failed or blocked run still gets a report with checkpoint and resume entry
            from .reporting.reports import write_reports
            write_reports(self)
        except Exception as exc:  # pragma: no cover
            self.store.event("report_failed", {"error": str(exc)[:300]})

    def _save_run(self, event: Optional[str] = None, payload: Optional[dict] = None) -> None:
        self.store.update(self.drun, event=event, event_payload=payload)

    def _status_line(self, force: bool = False) -> None:
        now = time.time()
        if force or now - self._last_status >= 30:
            b = self.budget.snapshot()
            self.log(f"[pra] {self.drun.run_id} phase={self.drun.phase.value} round={self.drun.round} "
                     f"actions={b['actions']['used']:.0f}/{b['actions']['limit']:.0f} "
                     f"llm_calls={b['llm_calls']['used']:.0f}/{b['llm_calls']['limit']:.0f} "
                     f"wall_left={self.budget.wall_remaining():.0f}s")
            self._last_status = now

    def _reconcile(self) -> None:
        """On resume: actions left 'running' by a killed process were not completed. Their
        reservations are settled at the reserved amount (no free retries, no double charge)
        and the attempt is marked failed so a later attempt can run."""
        stale = [a for a in self.store.list(ResearchAction) if a.status in (ActionStatus.running, ActionStatus.reserved)]
        done = {a.id for a in self.store.list(ResearchAction) if a.status in TERMINAL_ACTION_STATUSES}
        released = self.budget.release_orphans(done)
        for a in stale:
            if a.inputs.get("backend_run_dir"):
                a.error = "interrupted; external backend run must be reconciled with poll() before any relaunch"
            else:
                a.error = "interrupted by process exit before completion"
            for row_id, action_id, attempt, dim, reserved in self.budget.open_reservations():
                if action_id == a.id:
                    self.store.conn.execute("UPDATE budget SET actual=reserved, state='settled', settled_at=? WHERE id=?",
                                            (utcnow(), row_id))
            a.status = ActionStatus.failed
            self.store.update(a, event="action_reconciled", event_payload={"previous": "running"})
        if stale or released:
            self.log(f"[pra] reconciled {len(stale)} interrupted action(s), released {released} orphan reservation(s)")

    # ================================================================== actions
    def execute_action(self, action_type: str, purpose: ActionPurpose, inputs: dict, fn: Callable[[ResearchAction], ActionOutcome],
                       target_unknown_id: Optional[str] = None, candidate_revision_ids: Optional[list[str]] = None,
                       rationale: Optional[dict] = None, cost_cap: Optional[dict] = None,
                       charge_action: bool = True) -> ResearchAction:
        fp = stable_hash({"type": action_type, "purpose": purpose.value, "unknown": target_unknown_id,
                          "revisions": sorted(candidate_revision_ids or []), "inputs": inputs})
        existing_id = self.store.action_for_fingerprint(fp)
        if existing_id:
            existing = self.store.require(existing_id, ResearchAction)
            if existing.status in (ActionStatus.succeeded, ActionStatus.no_change, ActionStatus.skipped_budget):
                return existing       # identical input already done (or unaffordable): not repeated, not charged
            if existing.status == ActionStatus.failed and existing.attempt > self.config.limits.max_retries_per_action:
                return existing       # retry cap reached for this logical action
            action = existing
            action.attempt = existing.attempt + 1 if existing.status == ActionStatus.failed else existing.attempt
        else:
            action = ResearchAction(
                id=new_id("act"), origin=self.origin, source="controller", action_type=action_type, purpose=purpose,
                target_unknown_id=target_unknown_id, candidate_revision_ids=candidate_revision_ids or [],
                inputs=inputs, input_fingerprint=fp, cost_cap=cost_cap or {}, rationale=rationale or {},
                round=self.drun.round,
            )
            with self.store.tx():
                self.store.put(action, event="action_planned", event_payload={"type": action_type})
                self.store.bind_fingerprint(fp, action.id)
        try:
            res = self.budget.reserve({"actions": 1 if charge_action else 0}, action.id, action.attempt,
                                      cost_type="fixture" if self.origin == ExecutionOrigin.fixture else "measured")
        except BudgetExceeded as exc:
            action.status, action.error = ActionStatus.skipped_budget, str(exc)
            self.store.update(action, event="action_skipped_budget")
            return action
        action.status = ActionStatus.running
        self.store.update(action, event="action_started", event_payload={"attempt": action.attempt})
        started = time.time()
        try:
            out = fn(action)
            action.status, action.result_summary = out.status, out.summary
            action.new_information, action.artifacts = out.new_information, out.artifacts
            action.error = None
        except (ProviderError,) as exc:
            action.status, action.error = ActionStatus.failed, f"{exc.code}: {exc}"
            if exc.code in ("MISSING_CREDENTIALS", "AUTH_FAILED", "MODEL_UNAVAILABLE", "PRO_MODE_UNAVAILABLE",
                            "BINDING_MISMATCH", "FIXTURE_MISSING"):
                self._finish_action(action, res, started)
                raise BlockedDependency(f"model provider unavailable ({exc.code}); no fallback model or mode is used") from exc
        except QueryValidationError as exc:
            action.status, action.error = ActionStatus.failed, f"query output rejected: {exc}"
        except BudgetExceeded as exc:
            action.status, action.error = ActionStatus.skipped_budget, str(exc)
        except (BackendError, LiteratureError) as exc:
            action.status, action.error = ActionStatus.failed, str(exc)
        self._finish_action(action, res, started)
        return action

    def _finish_action(self, action: ResearchAction, res, started: float) -> None:
        self.budget.settle(res, {"actions": 1} if res.ids else {})
        action.usage = {"wall_seconds": round(time.time() - started, 3)}
        self.store.update(action, event="action_finished", event_payload={
            "status": action.status.value, "type": action.action_type, "error": (action.error or "")[:300]})

    def query(self, qi: QueryInput, purpose: ActionPurpose = ActionPurpose.information_gathering,
              target_unknown_id: Optional[str] = None, revision_ids: Optional[list[str]] = None,
              commit: Optional[Callable[[QueryResult, Any], list[str]]] = None) -> tuple[ResearchAction, Optional[Any]]:
        """Run one query as an idempotent action; ``commit`` turns the validated payload into
        records inside the same transaction as the QueryResult."""
        holder: dict[str, Any] = {}

        def fn(action: ResearchAction) -> ActionOutcome:
            result, payload = self.runner.run(qi, action.id)
            with self.store.tx():
                derived = commit(result, payload) if commit else []
                result.derived_object_ids = derived
                self.store.put(result, event="query_result", event_payload={"task_type": qi.task_type,
                                                                             "action_id": action.id})
            holder["payload"] = payload
            return ActionOutcome(ActionStatus.succeeded if derived or not commit else ActionStatus.no_change,
                                 f"{qi.task_type}: {len(result.answers)} answers, {len(derived)} records",
                                 bool(derived), [result.id])

        action = self.execute_action(f"query:{qi.task_type}", purpose,
                                     {"task_type": qi.task_type, "material_hash": stable_hash(qi.material),
                                      "refs": qi.input_refs, "fixture_key": qi.fixture_key},
                                     fn, target_unknown_id, revision_ids, charge_action=False)
        if "payload" not in holder and action.status in (ActionStatus.succeeded, ActionStatus.no_change) and action.artifacts:
            qr = self.store.get(action.artifacts[0])
            if isinstance(qr, QueryResult):
                from .agents.schemas import PAYLOADS
                holder["payload"] = PAYLOADS[qr.task_type].model_validate(qr.payload)
        return action, holder.get("payload")

    # ================================================================== helpers for records
    def current_revisions(self, include_inactive: bool = False) -> list[CandidateRevision]:
        revs = self.store.list(CandidateRevision)
        latest: dict[str, CandidateRevision] = {}
        for r in revs:
            if r.candidate_id not in latest or r.version > latest[r.candidate_id].version:
                latest[r.candidate_id] = r
        out = list(latest.values())
        return out if include_inactive else [r for r in out if r.status == "active"]

    def revision_for_key(self, key: str) -> Optional[CandidateRevision]:
        return next((r for r in self.current_revisions(True) if r.candidate_id == key), None)

    def _paper_ids(self) -> list[str]:
        return [p.id for p in self.store.list(PaperRecord)]

    def evidence_map(self) -> dict[str, Evidence]:
        return {e.id: e for e in self.store.list(Evidence)}

    def resolve_evidence_ids(self, refs: list[str]) -> tuple[list[str], list[str]]:
        ok, bad = [], []
        for ref in refs:
            ev = self.resolver.evidence_for(ref)
            (ok if ev else bad).append(ev.id if ev else ref)
        return ok, bad

    def add_assessments(self, outs: list, query_result_id: Optional[str]) -> list[str]:
        """Map AssessmentOut proposals to records. A 'known' judgment whose evidence does not
        resolve to stored Evidence is downgraded to unknown (never to a low score)."""
        ids = []
        for o in outs:
            if o.subject_type == "candidate":
                rev = self.revision_for_key(o.subject_key)
                if rev is None or rev.status != "active":
                    self.store.event("assessment_rejected", {"subject": o.subject_key, "reason": "no active revision"})
                    continue
                subject_id, subject_rev = rev.candidate_id, rev.id
            else:
                subject_id, subject_rev = o.subject_key, None
            ev_ids, bad = self.resolve_evidence_ids(o.evidence_refs)
            contra, _ = self.resolve_evidence_ids(o.contrary_refs)
            state, judgment, rationale = o.state, o.judgment, o.rationale
            if state == AssessmentState.known and (bad or not ev_ids):
                state, judgment = AssessmentState.unknown, None
                rationale += f" [downgraded to unknown: unresolvable evidence {bad or 'none cited'}]"
            prev = latest_assessments(self.store.list(Assessment), subject_rev).get(o.dimension) if subject_rev else None
            a = Assessment(id=new_id("asm"), origin=self.origin, source=f"query:{query_result_id}",
                           subject_type=o.subject_type, subject_id=subject_id, subject_revision=subject_rev,
                           dimension=o.dimension, state=state, judgment=judgment, evidence_ids=ev_ids,
                           contrary_evidence_ids=contra, rationale=rationale, conditional_on=o.conditional_on,
                           supersedes=prev.id if prev else None)
            self.store.put(a, event="assessment_added", event_payload={"dimension": a.dimension,
                                                                       "state": a.state.value})
            ids.append(a.id)
        return ids

    def add_unknowns(self, outs: list, source: str) -> list[str]:
        ids = []
        for u in outs:
            uid = f"unk_{u.key}"
            if self.store.exists(uid):
                continue
            self.store.put(Unknown(id=uid, origin=self.origin, source=source, question=u.question, affects=u.affects,
                                   importance=u.importance, available_checks=u.available_checks,
                                   missing_material=u.missing_material), event="unknown_added")
            ids.append(uid)
        return ids

    def apply_revision(self, prop, source: str) -> Optional[str]:
        """Create a new immutable CandidateRevision; old evidence is linked to it only as
        'inconclusive / pending applicability re-check' (T04)."""
        old = self.revision_for_key(prop.candidate_key)
        if old is None:
            return None
        fields = {k: v for k, v in prop.changes.items() if k in CandidateRevision.KEY_FIELDS or k in ("title", "nearest_neighbors", "abandon_conditions", "research_branch")}
        new = CandidateRevision(**{**old.model_dump(exclude={"id", "created_at", "key_fields_hash", "status",
                                                             "change_reason", "parent_revision_id", "version", "source"}),
                                   **fields},
                                id=f"rev_{old.candidate_id}_v{old.version + 1}", source=source,
                                version=old.version + 1, parent_revision_id=old.id, change_reason=prop.change_reason,
                                status="active")
        if new.key_fields_hash == old.key_fields_hash:
            self.store.event("revision_noop", {"candidate": old.candidate_id})
            return None
        self.store.put(new, event="candidate_revised", event_payload={"from": old.id, "reason": prop.change_reason})
        if old.status == "active":
            old.status = "superseded"
            self.store.update(old, event="candidate_superseded")
        ev_ids, _ = self.resolve_evidence_ids(prop.recheck_evidence_refs)
        for eid in ev_ids:
            self.store.put(EvidenceLink(id=new_id("lnk"), origin=self.origin, source="revision_recheck",
                                        evidence_id=eid, candidate_revision_id=new.id, claim_id="*",
                                        relation=LinkRelation.inconclusive,
                                        applicability="pending applicability re-check after revision"),
                           event="evidence_link_pending_recheck")
        return new.id

    # ================================================================== phases
    def clarify(self) -> None:
        material = {"idea_text": self.task.idea, "task_id": self.task.task_id,
                    "target_venues": self.task.target_venues, "research_branch": self.task.research_branch,
                    "metrics": self.task.metrics, "clarification_requirements": self.task.clarification_requirements,
                    "existing_candidate_revision": None}

        def commit(result: QueryResult, p) -> list[str]:
            ids = []
            ps = ProblemSpec(id=f"problem_{self.task.task_id}_v1", origin=self.origin, source=f"query:{result.id}",
                             task_id=self.task.task_id, idea_text=self.task.idea,
                             interpretations=[Interpretation(**i.model_dump()) for i in p.interpretations],
                             metrics_status="undecided" if self.task.metrics.get("status") == "undecided" else p.metrics_status,
                             open_items=[u.question for u in p.unknowns], query_result_id=result.id)
            missing_req = [r for r in self.task.clarification_requirements
                           if not any(r in (json.dumps(i.model_dump(), ensure_ascii=False)) for i in p.interpretations)
                           and r not in json.dumps([u.model_dump() for u in p.unknowns], ensure_ascii=False)]
            if missing_req:
                ps.open_items.append(f"clarification requirements not addressed: {missing_req}")
            self.store.put(ps, event="problem_spec")
            ids.append(ps.id)
            for c in p.concepts:
                cap, basis = prof.capability_for([c.canonical_name, *c.aliases], self.profile)
                cid = f"concept_{stable_hash(c.canonical_name)[:10]}"
                self.store.put(Concept(id=cid, origin=self.origin, source=f"query:{result.id}",
                                       canonical_name=c.canonical_name, aliases=c.aliases, role=c.role,
                                       existing_capability=cap, existing_capability_basis=basis), event="concept")
                ids.append(cid)
            ids += self.add_unknowns(p.unknowns, f"query:{result.id}")
            return ids

        _, payload = self.query(QueryInput("clarify_problem", material, input_refs=[f"task:{self.task.task_id}"],
                                           fixture_key="clarify_problem"), commit=commit)
        if payload is None:
            raise RunFailure("clarify_problem did not produce a valid result")
        self._search_plan = getattr(payload, "search_queries", [])
        self.store.event("search_plan", {"queries": self._search_plan})

    def _search_queries(self) -> list[dict[str, str]]:
        plan = [e["payload"]["queries"] for e in self.store.events("search_plan")]
        return plan[-1] if plan else []

    def _read_paper(self, paper: PaperRecord, questions: str, fixture_key: str) -> Optional[ResearchAction]:
        try:
            paper, doc = self.lit.read(paper, None)
        except (BudgetExceeded, LiteratureError) as exc:
            self.store.event("paper_read_skipped", {"paper": paper.id, "reason": str(exc)[:200]})
            return None
        units = doc.units
        material = {"paper_id": paper.id, "canonical_id": paper.canonical_id, "version": doc.version,
                    "text_status": doc.status.value, "read_scope": sorted(units), "questions": questions,
                    "units": {k: v[:6000] for k, v in units.items()},
                    "candidates": [{"key": r.candidate_id, "revision": r.id, "claims": r.claims}
                                   for r in self.current_revisions()]}

        def commit(result: QueryResult, p) -> list[str]:
            ids = []
            if p.paper_id != paper.id:
                raise QueryValidationError([f"read_paper payload for {p.paper_id}, expected {paper.id}"])
            for e in p.evidence:
                if not doc.has_locator(e.locator):
                    self.store.event("evidence_rejected", {"paper": paper.id, "locator": e.locator,
                                                           "reason": "locator not in retrieved text"})
                    continue
                namespace = "fixture" if paper.origin == ExecutionOrigin.fixture else "literature"
                ev = Evidence(id=new_id("ev"), origin=paper.origin, source=f"query:{result.id}",
                              kind=EvidenceKind.literature_report, namespace=namespace, source_id=paper.id,
                              source_version=doc.version, locator=e.locator,
                              content_hash=sha256_text(units[e.locator] + "\n" + e.observation),
                              observation=e.observation, same_source_group=f"{paper.canonical_id}#{e.locator}",
                              verification_status=VerificationStatus.unverified)
                eid, created = self.store.put(ev, event="evidence_added")
                if created:
                    ids.append(eid)
                for l in e.links:
                    rev = self.revision_for_key(l.candidate_key)
                    if rev:
                        self.store.put(EvidenceLink(id=new_id("lnk"), origin=self.origin, source=f"query:{result.id}",
                                                    evidence_id=eid, candidate_revision_id=rev.id, claim_id=l.claim_id,
                                                    relation=l.relation, applicability=l.applicability),
                                       event="evidence_link")
            return ids

        action, _ = self.query(QueryInput("read_paper", material, input_refs=[paper.id], fixture_key=fixture_key,
                                          allowed_tools=["retrieved_document"]), commit=commit)
        return action

    def map_field(self) -> None:
        cap = self.config.limits.max_search_queries
        for q in self._search_queries()[: max(1, cap // 2)]:
            try:
                self.lit.search(q["query"], 5, None, q.get("purpose", "field"))
            except (BudgetExceeded, LiteratureError) as exc:
                self.store.event("search_skipped", {"query": q["query"], "reason": str(exc)[:200]})
        papers = self.store.list(PaperRecord)
        for paper in papers[: max(0, self.config.limits.max_full_text_reads // 2)]:
            self._read_paper(paper, "Q2 read_paper (field map)", f"read_paper__{paper.id}")
        ev = [e for e in self.store.list(Evidence) if e.kind == EvidenceKind.literature_report]
        material = {"evidence": [{"id": e.id, "source_id": e.source_id, "locator": e.locator,
                                  "observation": e.observation} for e in ev],
                    "idea_text": self.task.idea}

        def commit(result: QueryResult, p) -> list[str]:
            base = self.store.require(f"problem_{self.task.task_id}_v1", ProblemSpec)
            ps = base.model_copy(update={"id": f"problem_{self.task.task_id}_v2", "source": f"query:{result.id}",
                                         "field_problems": [f.model_dump() for f in p.field_problems],
                                         "created_at": utcnow(), "query_result_id": result.id})
            self.store.put(ps, event="problem_spec_field_map")
            return [ps.id]

        self.query(QueryInput("map_field", material, input_refs=[e.id for e in ev] + self._paper_ids(), fixture_key="map_field"),
                   commit=commit)

    def retrieve_and_read(self) -> None:
        concepts = self.store.list(Concept)
        material = {
            "profile": {"expertise": [e.model_dump() for e in self.profile.expertise],
                        "research_interests": self.profile.research_interests,
                        "taste_rules": prof.taste_material(self.profile, self.drun.strategy)},
            "concepts": [c.model_dump(mode="json") for c in concepts],
            "field_problems": self.store.require(f"problem_{self.task.task_id}_v2", ProblemSpec).field_problems
            if self.store.exists(f"problem_{self.task.task_id}_v2") else [],
            "evidence": [{"id": e.id, "observation": e.observation} for e in self.store.list(Evidence)],
        }

        def commit(result: QueryResult, p) -> list[str]:
            ids = self.add_assessments([a for a in p.assessments if a.subject_type != "candidate"], result.id)
            for a in p.assessments:            # concept-level field importance (never derived from familiarity)
                if a.subject_type == "concept" and a.dimension == "field_importance" and a.state == AssessmentState.known:
                    for c in self.store.list(Concept):
                        if c.canonical_name == a.subject_key:
                            c2 = c.model_copy(update={"id": c.id + "_f", "field_importance": a.judgment,
                                                      "field_importance_basis": a.rationale, "created_at": utcnow()})
                            self.store.put(c2, event="concept_field_importance")
                            ids.append(c2.id)
            for t in p.learning_tasks:
                uid = f"unk_learn_{stable_hash(t)[:8]}"
                if not self.store.exists(uid):
                    self.store.put(Unknown(id=uid, origin=self.origin, source=f"query:{result.id}",
                                           question=f"learning task: {t.get('topic', t)}", affects=t.get("affects", []),
                                           importance=Level(t.get("importance", "medium")), available_checks=[],
                                           missing_material=t.get("why")), event="learning_task")
                    ids.append(uid)
            self.store.event("background_links", {"correspondences": [c.model_dump() for c in p.correspondences]})
            return ids

        self.query(QueryInput("link_background", material, input_refs=[e.id for e in self.store.list(Evidence)] + self._paper_ids(),
                              fixture_key="link_background"), commit=commit)
        # targeted reading for the user-method link queries
        for q in [q for q in self._search_queries() if q.get("purpose") == "user_method_link"]:
            try:
                for paper in self.lit.search(q["query"], 3, None, "user_method_link"):
                    if paper.document_path:
                        continue
                    if self.budget.remaining("full_text_reads") > 0:
                        self._read_paper(paper, "Q2 read_paper (background link)", f"read_paper__{paper.id}")
            except (BudgetExceeded, LiteratureError) as exc:
                self.store.event("search_skipped", {"query": q["query"], "reason": str(exc)[:200]})

    def propose(self) -> None:
        links = [e["payload"] for e in self.store.events("background_links")]
        material = {"idea_text": self.task.idea, "background_links": links[-1] if links else {},
                    "problem": self.store.require(f"problem_{self.task.task_id}_v1", ProblemSpec).model_dump(mode="json"),
                    "papers": [{"id": p.id, "title": p.title, "text_status": p.text_status.value}
                               for p in self.store.list(PaperRecord)],
                    "max_candidates": self.config.limits.max_candidates,
                    "taste_rules": prof.taste_material(self.profile, self.drun.strategy)}

        def commit(result: QueryResult, p) -> list[str]:
            ids = []
            for c in p.candidates[: self.config.limits.max_candidates]:
                branch = c.research_branch
                if branch == "auto":
                    branch = self.task.research_branch if self.task.research_branch != "auto" else "auto"
                rev = CandidateRevision(id=f"rev_{c.key}_v1", origin=self.origin, source=f"query:{result.id}",
                                        candidate_id=c.key, version=1, title=c.title, problem_scope=c.problem_scope,
                                        hypothesis=c.hypothesis, mechanism=c.mechanism, increment=c.increment,
                                        nearest_neighbors=c.nearest_neighbors, claims=c.claims,
                                        validation_protocol={**c.validation_protocol, "cheapest_check": c.cheapest_check},
                                        abandon_conditions=c.abandon_conditions,
                                        research_branch=ResearchBranch(branch))
                self.store.put(rev, event="candidate_proposed")
                ids.append(rev.id)
            ids += self.add_unknowns(p.unknowns, f"query:{result.id}")
            if p.no_alternative_reason:
                self.store.event("no_alternative_reason", {"reason": p.no_alternative_reason})
            return ids

        _, payload = self.query(QueryInput("propose_candidates", material,
                                           input_refs=[p.id for p in self.store.list(PaperRecord)],
                                           fixture_key="propose_candidates"), commit=commit)
        if not self.current_revisions():
            self.drun.notes.append("no candidate could be formed from the recorded links")

    def assess(self) -> Optional[Phase]:
        """Initial (or post-revision) Q4 check per active revision that has not been checked."""
        checked = {qr.candidate_revision_id for qr in self.store.list(QueryResult) if qr.task_type == "check_candidate"}
        for rev in self.current_revisions():
            if rev.id in checked:
                continue
            self.check_candidate(rev)
        rejected = self.apply_vetoes()
        self._rank_and_record(rejected)
        if self.drun.strategy == "one_shot":
            return Phase.select
        return Phase.acquire_evidence

    def check_candidate(self, rev: CandidateRevision) -> None:
        ev = self.evidence_map()
        linked = [l for l in self.store.list(EvidenceLink) if l.candidate_revision_id == rev.id]
        material = {"candidate": rev.model_dump(mode="json"),
                    "nearest_neighbors": [self.store.get(p).model_dump(mode="json") for p in rev.nearest_neighbors
                                          if self.store.exists(p)],
                    "evidence": [{"id": e.id, "kind": e.kind.value, "source_id": e.source_id, "locator": e.locator,
                                  "observation": e.observation, "namespace": e.namespace} for e in ev.values()],
                    "links": [l.model_dump(mode="json") for l in linked],
                    "search_scope": [x["payload"] for x in self.store.events("literature_search")]}
        refs = self._paper_ids() + list(ev) + [rev.id]

        def commit(result: QueryResult, p) -> list[str]:
            ids = self.add_assessments(p.assessments, result.id)
            ids += self.add_unknowns(p.unknowns, f"query:{result.id}")
            self.store.event("claim_checks", {"revision": rev.id, "checks": [c.model_dump() for c in p.claim_checks]})
            for prop in p.revision_proposals:
                rid = self.apply_revision(prop, f"query:{result.id}")
                if rid:
                    ids.append(rid)
            return ids or [result.id]

        self.query(QueryInput("check_candidate", material, input_refs=refs, candidate_revision_id=rev.id,
                              fixture_key=f"check_candidate__{rev.id}"), revision_ids=[rev.id], commit=commit)

    # ------------------------------------------------------------------ ranking
    def _rejections(self) -> dict[str, str]:
        out = {}
        for e in self.store.events("candidate_rejected"):
            out[e["payload"]["revision"]] = e["payload"]["reason"]
        return out

    def _rank_and_record(self, change_evidence: list[str]) -> RankingSnapshot:
        revisions = self.current_revisions(include_inactive=True)
        prev = (self.store.list(RankingSnapshot) or [None])[-1]
        snap = rank(revisions, self.store.list(Assessment), self.drun.round, self.drun.strategy, self.origin, prev,
                    new_id("rank"), {k: v for k, v in self._rejections().items() if any(r.id == k for r in revisions)},
                    [{"evidence_ids": change_evidence}])
        self.store.put(snap, event="ranking_snapshot", event_payload={"preferred": snap.preferred_candidates,
                                                                      "unresolved": snap.unresolved_candidates})
        return snap

    def apply_vetoes(self) -> list[str]:
        """Re-evaluate every candidate touched by new refutations (T05)."""
        rejected = []
        for v in rules.vetoes(self.current_revisions(), self.store.list(EvidenceLink), self.evidence_map(), {},
                              self.coverage_blocks()):
            rev = self.store.require(v.revision_id, CandidateRevision)
            rev.status = "rejected"
            with self.store.tx():
                self.store.update(rev, event="candidate_status")
                self.store.event("candidate_rejected", {"revision": rev.id, "reason": v.reason,
                                                        "evidence": v.evidence_ids})
                for dim in ("scientific_value", "novelty", "feasibility"):
                    prev = latest_assessments(self.store.list(Assessment), rev.id).get(dim)
                    self.store.put(Assessment(
                        id=new_id("asm"), origin=self.origin, source="veto_rule", subject_type="candidate",
                        subject_id=rev.candidate_id, subject_revision=rev.id, dimension=dim,
                        state=AssessmentState.disputed, judgment=None, evidence_ids=[],
                        contrary_evidence_ids=v.evidence_ids,
                        rationale=f"re-evaluated after refutation: {v.reason}", supersedes=prev.id if prev else None),
                        event="assessment_reevaluated")
            rejected.append(rev.id)
        return rejected

    def coverage_blocks(self) -> dict[str, str]:
        """A revision is vetoed for coverage only when Q4 found *every* claim covered and each
        covered check cites literature evidence read beyond the abstract."""
        out: dict[str, str] = {}
        papers = {p.id: p for p in self.store.list(PaperRecord)}
        for e in self.store.events("claim_checks"):
            rid, checks = e["payload"]["revision"], e["payload"]["checks"]
            if not checks or any(c["status"] != "covered" for c in checks):
                continue
            ok = True
            for c in checks:
                evs = [self.resolver.evidence_for(r) for r in c.get("source_refs", [])]
                evs = [x for x in evs if x is not None and x.kind == EvidenceKind.literature_report]
                if not evs or not all(papers.get(x.source_id) and papers[x.source_id].text_status.value in
                                      ("partial_text", "full_text") for x in evs):
                    ok = False
            if ok:
                ns = {self.resolver.evidence_for(r).namespace for c in checks for r in c.get("source_refs", [])
                      if self.resolver.evidence_for(r)}
                out[rid] = ("substantive coverage: every claim covered by "
                            + ", ".join(r for c in checks for r in c.get("source_refs", []))
                            + (" [fixture evidence: flow test only]" if "fixture" in ns else ""))
        return out

    # ------------------------------------------------------------------ evidence loop
    def acquire_evidence(self) -> Phase:
        while True:
            snap = (self.store.list(RankingSnapshot) or [None])[-1]
            active = self.current_revisions()
            stop = rules.stop_check(self.drun.round, self.drun.no_change_rounds, self.config.limits,
                                    int(self.budget.used("actions")), len(active),
                                    len(snap.unresolved_candidates) if snap else 0, self.budget.wall_remaining(),
                                    [d for d in ("llm_calls", "actions") if self.budget.remaining(d) < 1])
            if stop.stop:
                self.drun.stop_reason = stop.reason
                self.drun.notes.append(f"loop stopped: {stop.detail}")
                return Phase.select
            if snap and self._gates_any_pass(snap):
                self.drun.stop_reason = StopReason.evidence_sufficient
                return Phase.select
            started = {e["payload"]["round"] for e in self.store.events("round_started")}
            finished = {e["payload"]["round"] for e in self.store.events("round_finished")}
            if self.drun.round in started and self.drun.round not in finished:
                self.store.event("round_resumed", {"round": self.drun.round})     # interrupted round: re-enter it
            else:
                self.drun.round += 1
                self._save_run(event="round_started", payload={"round": self.drun.round})
            proposal = self._recorded_decision(self.drun.round) or self._update_decision(snap)
            action = self._choose_action(proposal, snap)
            if action is None:
                self.drun.stop_reason = StopReason.no_available_action
                self.drun.notes.append("no executable, non-duplicate, affordable action remained")
                return Phase.select
            new_info = self._execute_planned(action)
            rejected = self.apply_vetoes()
            for rev in self.current_revisions():
                if not any(q.candidate_revision_id == rev.id for q in self.store.list(QueryResult)
                           if q.task_type == "check_candidate"):
                    self.check_candidate(rev)
                    new_info = True
            evid = [e.id for e in self.store.list(Evidence) if e.source.endswith(action.get("action_id", "-"))]
            self._rank_and_record(evid)
            self.drun.no_change_rounds = 0 if (new_info or rejected) else self.drun.no_change_rounds + 1
            self._save_run(event="round_finished", payload={"round": self.drun.round, "new_information": new_info,
                                                            "rejected": rejected})
            self._status_line()

    def _gates_any_pass(self, snap: RankingSnapshot) -> bool:
        return any(g.passed for g in self.gate_reports(snap))

    def gate_reports(self, snap: RankingSnapshot) -> list[rules.GateReport]:
        papers = {p.id: p for p in self.store.list(PaperRecord)}
        links, ev, unknowns = self.store.list(EvidenceLink), self.evidence_map(), self.store.list(Unknown)
        sensitive = any("personal_fit" in json.dumps(c) for c in snap.changed_from_previous)
        out = []
        for rid in snap.preferred_candidates + snap.unresolved_candidates:
            rev = self.store.require(rid, CandidateRevision)
            dims = latest_assessments(self.store.list(Assessment), rid)
            backend_ok = rev.research_branch == ResearchBranch.theoretical or self.config.backend.kind == "ai_scientist_v3"
            g = rules.recommendation_gates(rev, dims, papers, links, ev, unknowns, backend_ok, sensitive)
            if rid not in snap.preferred_candidates:
                g.failures.insert(0, "not in the preferred set of the partial ranking (decisive dimension unknown)")
                g.passed = False
            out.append(g)
        return out

    def _recorded_decision(self, round_: int) -> Optional[Any]:
        from .agents.schemas import PAYLOADS

        for e in reversed(self.store.events("decision_proposal")):
            if e["payload"].get("round") == round_ and e["payload"].get("query_result_id"):
                qr = self.store.get(e["payload"]["query_result_id"])
                if isinstance(qr, QueryResult):
                    self.store.event("decision_reused", {"round": round_, "query_result_id": qr.id})
                    return PAYLOADS["update_decision"].model_validate(qr.payload)
        return None

    def _update_decision(self, snap: Optional[RankingSnapshot]) -> Optional[Any]:
        if self.budget.remaining("llm_calls") < 1:
            return None
        done = [a for a in self.store.list(ResearchAction) if a.status in TERMINAL_ACTION_STATUSES]
        ev = self.evidence_map()
        material = {
            "round": self.drun.round,
            "ranking": snap.model_dump(mode="json") if snap else None,
            "candidates": [r.model_dump(mode="json") for r in self.current_revisions(True)],
            "evidence": [{"id": e.id, "kind": e.kind.value, "namespace": e.namespace, "observation": e.observation,
                          "same_source_group": e.same_source_group} for e in ev.values()],
            "open_unknowns": [u.model_dump(mode="json") for u in self.store.list(Unknown) if u.status == "open"],
            "executed_fingerprints": [{"type": a.action_type, "fingerprint": a.input_fingerprint, "status": a.status.value}
                                      for a in done],
            "gates": [g.__dict__ for g in self.gate_reports(snap)] if snap else [],
            "budget": self.budget.snapshot(), "allowed_actions": sorted(self.allowed_action_types()),
        }

        def commit(result: QueryResult, p) -> list[str]:
            ids = self.add_assessments(p.assessment_updates, result.id)
            for prop in p.revision_proposals:
                rid = self.apply_revision(prop, f"query:{result.id}")
                if rid:
                    ids.append(rid)
            self.store.event("decision_proposal", {"round": self.drun.round, "query_result_id": result.id,
                                                   "next_action": p.next_action.model_dump()
                                                   if p.next_action else None, "stop": p.stop_recommendation,
                                                   "duplicates": p.duplicate_evidence_refs})
            return ids or [result.id]

        _, payload = self.query(QueryInput("update_decision", material,
                                           input_refs=list(ev) + self._paper_ids() + [r.id for r in self.current_revisions(True)],
                                           fixture_key=f"update_decision__r{self.drun.round}"), commit=commit)
        return payload

    def allowed_action_types(self) -> set[str]:
        allowed = {"counterexample_search", "cpu_pilot", "check_theory"}
        if self.budget.remaining("search_queries") >= 1:
            allowed.add("search_literature")
        if self.config.backend.kind == "ai_scientist_v3":
            allowed |= {"backend_pilot"}
        return allowed

    def _candidate_actions(self, proposal) -> list[dict]:
        cands: list[dict] = []
        if proposal is not None and proposal.next_action is not None:
            na = proposal.next_action
            cands.append({"action_type": na.action_type, "purpose": na.purpose, "unknown": na.target_unknown_key,
                          "candidates": na.candidate_keys, "inputs": na.inputs, "cost_cap": na.cost_cap,
                          "why": na.why_now, "branches": na.expected_branches, "from": "update_decision"})
        for u in self.store.list(Unknown):
            if u.status != "open":
                continue
            for chk in u.available_checks:
                cands.append({"action_type": chk.get("action_type"), "purpose": chk.get("purpose", "preliminary_check"),
                              "unknown": u.id.removeprefix("unk_"), "candidates": u.affects, "inputs": chk.get("inputs", {}),
                              "cost_cap": chk.get("cost", {}), "why": f"resolves unknown: {u.question}",
                              "branches": chk.get("branches", []), "can_disqualify": chk.get("can_disqualify", False),
                              "alternative_mechanism": chk.get("alternative_mechanism", False), "from": "unknown_checks"})
        return cands

    def _choose_action(self, proposal, snap: Optional[RankingSnapshot]) -> Optional[dict]:
        allowed = self.allowed_action_types()
        preferred = snap.preferred_candidates if snap else []
        options = []
        for c in self._candidate_actions(proposal):
            why_not = None
            revs = [self.revision_for_key(k) for k in c["candidates"]]
            revs = [r for r in revs if r is not None and r.status == "active"]
            if c["action_type"] not in allowed:
                why_not = f"action {c['action_type']} not allowed in this mode/backend"
            elif c["candidates"] and not revs:
                why_not = "targets no active candidate revision"
            elif c["unknown"] and not self.store.exists(f"unk_{c['unknown']}"):
                why_not = "unknown does not exist"
            elif c["action_type"] == "search_literature" and self.config.literature.provider == "fixture" \
                    and c["inputs"].get("requires_live"):
                why_not = "requires a live literature search; offline_local provides synthetic fixtures only"
            if not why_not:
                fp = stable_hash({"type": c["action_type"], "inputs": c["inputs"], "revisions": sorted(r.id for r in revs)})
                done = [a for a in self.store.list(ResearchAction) if a.rationale.get("choice_fingerprint") == fp]
                if any(a.status in (ActionStatus.succeeded, ActionStatus.no_change) for a in done):
                    why_not = "identical input already executed"
                elif any(a.status == ActionStatus.skipped_budget for a in done):
                    why_not = "identical input was already refused for budget"
                elif any(a.status == ActionStatus.failed and a.attempt > self.config.limits.max_retries_per_action for a in done):
                    why_not = "retry limit reached for identical input"
            if why_not:
                self.store.event("action_option_rejected", {"option": {k: c[k] for k in ("action_type", "unknown", "from")},
                                                            "reason": why_not})
                continue
            c["revision_ids"] = [r.id for r in revs]
            c["choice_fingerprint"] = fp
            options.append(c)
        if not options:
            return None
        top_two = set()
        if snap:
            for u in self.store.list(Unknown):
                if u.status == "open" and any(self.revision_for_key(k) and self.revision_for_key(k).id in (snap.preferred_candidates + snap.unresolved_candidates)[:2] for k in u.affects):
                    top_two.add(u.id)
        probe = lambda c: ResearchAction(id="probe", origin=self.origin, source="probe", action_type=c["action_type"],
                                         purpose=ActionPurpose(c["purpose"]), target_unknown_id=f"unk_{c['unknown']}" if c["unknown"] else None,
                                         candidate_revision_ids=c["revision_ids"], input_fingerprint="-",
                                         cost_cap=c["cost_cap"], rationale={"can_disqualify": c.get("can_disqualify", False),
                                                                            "alternative_mechanism": c.get("alternative_mechanism", False)})
        options.sort(key=lambda c: (0 if c["from"] == "update_decision" else 1,) + rules.action_priority(probe(c), preferred, top_two))
        chosen = options[0]
        self.store.event("action_selected", {"round": self.drun.round, "option": {k: chosen[k] for k in (
            "action_type", "unknown", "candidates", "why", "branches", "cost_cap", "from")},
            "alternatives": len(options) - 1})
        return chosen

    def _execute_planned(self, c: dict) -> bool:
        atype = c["action_type"]
        unknown_id = f"unk_{c['unknown']}" if c["unknown"] else None
        rationale = {"target_unknown": unknown_id, "why": c["why"], "branches": c["branches"],
                     "cost_cap": c["cost_cap"], "priority_reason": c["from"], "choice_fingerprint": c["choice_fingerprint"],
                     "can_disqualify": c.get("can_disqualify", False)}
        if atype in ("counterexample_search", "cpu_pilot"):
            fn = lambda action: self._run_pilot(action, c)
            purpose = ActionPurpose.preliminary_check
        elif atype == "search_literature":
            fn = lambda action: self._run_search(action, c)
            purpose = ActionPurpose.information_gathering
        elif atype == "check_theory":
            fn = lambda action: self._run_check_theory(action, c)
            purpose = ActionPurpose.preliminary_check
        else:
            self.store.event("action_unsupported", {"type": atype})
            return False
        action = self.execute_action(atype, purpose, c["inputs"], fn, unknown_id, c["revision_ids"], rationale,
                                     c["cost_cap"])
        c["action_id"] = action.id
        if action.status == ActionStatus.succeeded and unknown_id and self.store.exists(unknown_id):
            u = self.store.require(unknown_id, Unknown)
            u.status, u.resolution = "resolved", action.result_summary
            self.store.update(u, event="unknown_resolved")
        return bool(action.new_information)

    def _run_search(self, action: ResearchAction, c: dict) -> ActionOutcome:
        before = {p.canonical_id for p in self.store.list(PaperRecord)}
        papers = self.lit.search(c["inputs"]["query"], c["inputs"].get("max_results", 5), action.id,
                                 c["inputs"].get("purpose", "nearest"))
        new = [p for p in papers if p.canonical_id not in before]
        for p in new[:2]:
            if self.budget.remaining("full_text_reads") >= 1:
                self._read_paper(p, "Q2 read_paper (nearest-neighbour check)", f"read_paper__{p.id}")
        return ActionOutcome(ActionStatus.succeeded if new else ActionStatus.no_change,
                             f"{len(papers)} hits, {len(new)} new (absence of hits is not evidence of absence)",
                             bool(new), [p.id for p in new])

    # ------------------------------------------------------------------ pilots & specs
    def freeze_spec(self, rev: CandidateRevision, stage: StudyStage, plan: dict, fixture_key: str) -> Optional[ResearchSpec]:
        """Q5 make_research_spec -> frozen ResearchSpec. Missing items stay missing; for a formal
        theoretical spec the equivalence definition / statement must be explicit."""
        existing = [s for s in self.store.list(ResearchSpec)
                    if s.candidate_revision_id == rev.id and s.study_stage == stage
                    and (s.counterexample_search_plan or s.evaluation) == plan]
        if existing:
            return existing[-1]
        material = {"candidate": rev.model_dump(mode="json"), "study_stage": stage.value, "plan": plan,
                    "resources": {"backend": self.config.backend.kind, "limits": self.config.limits.model_dump()}}
        holder: dict[str, ResearchSpec] = {}

        def commit(result: QueryResult, p) -> list[str]:
            branch = ResearchBranch(p.research_branch)
            if rev.research_branch not in (ResearchBranch.auto, branch):
                raise QueryValidationError([f"spec branch {branch.value} differs from candidate branch {rev.research_branch.value}"])
            versions = [s.protocol_version for s in self.store.list(ResearchSpec) if s.protocol_id == f"proto_{rev.candidate_id}"]
            spec = ResearchSpec(
                id=new_id("spec"), origin=self.origin, source=f"query:{result.id}", study_stage=stage,
                candidate_revision_id=rev.id, protocol_id=f"proto_{rev.candidate_id}", protocol_version=max(versions, default=0) + 1,
                research_branch=branch, hypothesis=p.hypothesis, falsification=p.falsification, baselines=p.baselines,
                environment=p.environment, resources=p.resources, evaluation={**p.evaluation, **(plan if stage == StudyStage.formal else {})},
                continue_criteria=p.continue_criteria, abandon_criteria=p.abandon_criteria,
                theorem_statement=p.theorem_statement, assumptions=p.assumptions,
                policy_information_class=p.policy_information_class, proof_obligations=p.proof_obligations,
                counterexample_search_plan=plan if plan.get("pilot_id") else p.counterexample_search_plan,
                review_method=p.review_method, missing=p.missing)
            if branch in (ResearchBranch.theoretical, ResearchBranch.mixed) and not spec.theorem_statement:
                spec.missing.append("theorem_statement")
            if stage == StudyStage.formal and branch == ResearchBranch.theoretical and not spec.policy_information_class:
                spec.missing.append("policy/information class")
            self.store.put(spec, event="research_spec_frozen", event_payload={"stage": stage.value,
                                                                              "missing": spec.missing})
            holder["spec"] = spec
            return [spec.id]

        self.query(QueryInput("make_research_spec", material, input_refs=[rev.id], candidate_revision_id=rev.id,
                              fixture_key=fixture_key), purpose=ActionPurpose.preliminary_check
                   if stage == StudyStage.pilot else ActionPurpose.formal_research,
                   revision_ids=[rev.id], commit=commit)
        if "spec" in holder:
            return holder["spec"]
        specs = [s for s in self.store.list(ResearchSpec) if s.candidate_revision_id == rev.id and s.study_stage == stage]
        return specs[-1] if specs else None

    def _run_pilot(self, action: ResearchAction, c: dict) -> ActionOutcome:
        revs = [self.store.require(r, CandidateRevision) for r in c["revision_ids"]]
        if not revs:
            return ActionOutcome(ActionStatus.failed, "pilot needs a candidate revision", False, [])
        rev = revs[0]
        plan = dict(c["inputs"])
        spec = self.freeze_spec(rev, StudyStage.pilot, plan, f"make_research_spec__pilot__{rev.id}")
        if spec is None:
            return ActionOutcome(ActionStatus.failed, "pilot ResearchSpec could not be frozen", False, [])
        if spec.missing:
            return ActionOutcome(ActionStatus.failed, f"pilot spec incomplete: {spec.missing}", False, [spec.id])
        out_dir = self.run_dir / "artifacts" / f"{action.id}"
        marker = out_dir / "_complete.json"
        result = self._recover_pilot(marker, spec)
        if result is None:
            res = self.budget.reserve({"pilots": 1}, action.id, action.attempt)
            try:
                result = self.local.run_pilot(spec, out_dir, self.budget.action_deadline_seconds())
                marker.write_text(json.dumps({"protocol_hash": spec.protocol_hash, "pilot_id": result.pilot_id,
                                              "command": result.command, "artifacts": [str(p) for p in result.artifacts],
                                              "findings": [f.__dict__ for f in result.findings]}), encoding="utf-8")
            finally:
                self.budget.settle(res, {"pilots": 1})   # failed pilots are charged too
        ids = self._record_pilot(result, spec, action, revs)
        return ActionOutcome(ActionStatus.succeeded, "; ".join(f.observation for f in result.findings),
                             bool(ids), [str(p.relative_to(self.run_dir)) for p in result.artifacts] + ids)

    def _recover_pilot(self, marker: Path, spec: ResearchSpec):
        """A pilot that finished computing before the process died is recovered from its marker
        (same frozen protocol, artifacts hashed later), so resume neither repeats nor re-charges it."""
        from .research.pilots import PilotFinding, PilotResult

        if not marker.exists():
            return None
        data = json.loads(marker.read_text(encoding="utf-8"))
        if data.get("protocol_hash") != spec.protocol_hash or not all(Path(p).exists() for p in data["artifacts"]):
            return None
        self.store.event("pilot_result_recovered", {"marker": str(marker.relative_to(self.run_dir)), "pilot": data["pilot_id"]})
        return PilotResult(data["pilot_id"], [Path(p) for p in data["artifacts"]],
                           [PilotFinding(**f) for f in data["findings"]], data["command"])

    def _record_pilot(self, result, spec: ResearchSpec, action: ResearchAction, revs: list[CandidateRevision]) -> list[str]:
        ids = []
        with self.store.tx():
            for f in result.findings:
                art = Path(result.artifacts[0]).parent / f.artifact
                digest = sha256_text(art.read_text(encoding="utf-8"))
                kind = EvidenceKind.counterexample if f.kind == "counterexample" else EvidenceKind.computation
                ev = Evidence(id=new_id("ev"), origin=ExecutionOrigin.offline_local if self.config.mode == "offline_local" else ExecutionOrigin.live,
                              source=f"action:{action.id}", kind=kind, namespace="computation",
                              source_id=f"artifact:{result.pilot_id}", source_version=spec.protocol_hash,
                              locator=f"{f.artifact}:{f.locator}", content_hash=digest, observation=f.observation,
                              same_source_group=f"computation:{result.pilot_id}:{digest[:16]}",
                              verification_status=VerificationStatus.verified,
                              artifact_path=str(art.relative_to(self.run_dir)), run_ref=action.id,
                              protocol_version=f"{spec.protocol_id}@{spec.protocol_version}")
                eid, created = self.store.put(ev, event="computation_evidence")
                if created:
                    ids.append(eid)
                for rev in revs:
                    for claim in rev.claims:
                        if claim.get("check_key") != f.claim_key:
                            continue
                        expected = claim.get("expects_holds", True)
                        if f.holds is None:
                            relation, why = LinkRelation.inconclusive, "check did not decide the claim"
                        elif f.holds != expected and f.assumptions_satisfied:
                            relation, why = LinkRelation.refutes, f"verified counterexample satisfying the claim's assumptions ({f.locator})"
                        elif f.holds == expected:
                            relation = LinkRelation.supports
                            why = ("finite-instance support only; does not prove the general statement"
                                   if claim.get("scope") == "general" else "supports the claim within the computed scope")
                        else:
                            relation, why = LinkRelation.inconclusive, "assumptions of the claim not verified for this instance"
                        self.store.put(EvidenceLink(id=new_id("lnk"), origin=ev.origin, source=f"action:{action.id}",
                                                    evidence_id=eid, candidate_revision_id=rev.id, claim_id=claim["id"],
                                                    relation=relation, applicability=why), event="evidence_link")
                        self._update_claim(rev, claim, eid, relation, f, spec)
        return ids

    def _update_claim(self, rev: CandidateRevision, claim: dict, evidence_id: str, relation: LinkRelation, finding, spec) -> None:
        cid = f"claim_{rev.id}_{claim['id']}"
        existing = self.store.get(cid)
        c = existing if isinstance(existing, Claim) else Claim(
            id=cid, origin=self.origin, source="controller", candidate_revision_id=rev.id,
            protocol_id=spec.protocol_id, protocol_version=spec.protocol_version, statement=claim["statement"],
            scope=claim.get("scope", "general"), study_stage=spec.study_stage, proof_status=ProofStatus.unproven)
        state = TheoryState(statement=c.statement, scope="finite_instance" if c.scope == "finite_instance" else "general",
                            status=c.proof_status or ProofStatus.unproven)
        try:
            if relation == LinkRelation.refutes:
                apply_theory(state, TheoryEvidence("counterexample", evidence_id, assumptions_satisfied=True))
                c.status = "refuted"
            elif relation == LinkRelation.supports:
                apply_theory(state, TheoryEvidence("finite_instance", evidence_id, holds=True))
                c.status = "supported" if c.scope in ("finite_instance", "negative") else "unproven"
        except ProofStatusError as exc:
            c.audit_findings.append(str(exc))
        c.proof_status = state.status
        c.proof_history += state.history
        links = [l.id for l in self.store.list(EvidenceLink) if l.evidence_id == evidence_id and l.candidate_revision_id == rev.id]
        c.evidence_link_ids = sorted(set(c.evidence_link_ids) | set(links))
        if existing:
            self.store.update(c, event="claim_updated")
        else:
            self.store.put(c, event="claim_created")

    def _run_check_theory(self, action: ResearchAction, c: dict) -> ActionOutcome:
        rev = self.store.require(c["revision_ids"][0], CandidateRevision)
        ev = self.evidence_map()
        material = {"candidate": rev.model_dump(mode="json"),
                    "evidence": [{"id": e.id, "kind": e.kind.value, "observation": e.observation, "locator": e.locator}
                                 for e in ev.values() if e.namespace == "computation"],
                    "claims": [cl.model_dump(mode="json") for cl in self.store.list(Claim) if cl.candidate_revision_id == rev.id]}

        def commit(result: QueryResult, p) -> list[str]:
            if p.proof_status == ProofStatus.formally_verified:
                raise QueryValidationError(["check_theory cannot set formally_verified (no trusted proof checker ran)"])
            self.store.event("theory_check", {"revision": rev.id, "proof_status": p.proof_status.value,
                                              "review_method": p.review_method,
                                              "obligations": [o.model_dump() for o in p.obligations]})
            return [result.id]

        act, payload = self.query(QueryInput("check_theory", material, input_refs=[rev.id] + list(ev),
                                             candidate_revision_id=rev.id, fixture_key=f"check_theory__{rev.id}"),
                                  purpose=ActionPurpose.preliminary_check, revision_ids=[rev.id], commit=commit)
        if payload is None:
            return ActionOutcome(ActionStatus.failed, act.error or "check_theory failed", False, [])
        return ActionOutcome(ActionStatus.succeeded, f"proof status {payload.proof_status.value} ({payload.review_method})",
                             True, act.artifacts)

    # ------------------------------------------------------------------ select / execute
    def select(self) -> Phase:
        snap = (self.store.list(RankingSnapshot) or [None])[-1]
        if snap is None:
            snap = self._rank_and_record([])
        gates = self.gate_reports(snap)
        self.store.event("gate_reports", {"reports": [g.__dict__ for g in gates]})
        passed = [g for g in gates if g.passed]
        active = self.current_revisions()
        if not active and not snap.unresolved_candidates:
            self.drun.planning_outcome = PlanningOutcome.no_viable_candidate
            self.drun.stop_reason = self.drun.stop_reason or StopReason.all_candidates_rejected
        elif passed:
            self.drun.planning_outcome = PlanningOutcome.recommended
            self.drun.recommended_candidate_revision_id = passed[0].revision_id
            self.drun.stop_reason = self.drun.stop_reason or StopReason.evidence_sufficient
            return Phase.execute_research
        else:
            self.drun.planning_outcome = PlanningOutcome.inconclusive
            if self.drun.strategy == "one_shot" and not self.drun.stop_reason:
                self.drun.stop_reason = StopReason.no_available_action
                self.drun.notes.append("one_shot strategy: no evidence loop by design")
        return Phase.audit

    def execute_research(self) -> None:
        rev = self.store.require(self.drun.recommended_candidate_revision_id, CandidateRevision)
        plan = rev.validation_protocol.get("formal_plan", {})
        spec = self.freeze_spec(rev, StudyStage.formal, plan, f"make_research_spec__formal__{rev.id}")
        if spec is None or spec.missing:
            self.drun.research_outcome = ResearchOutcome.not_run
            self.drun.notes.append(f"formal research not started: spec missing {spec.missing if spec else 'spec'}")
            return
        if spec.research_branch == ResearchBranch.theoretical:
            c = {"revision_ids": [rev.id], "inputs": spec.counterexample_search_plan or {}, "unknown": None,
                 "why": "formal theory check", "branches": [], "cost_cap": {}, "from": "formal",
                 "choice_fingerprint": spec.protocol_hash}
            if (spec.counterexample_search_plan or {}).get("pilot_id"):
                self.execute_action("counterexample_search", ActionPurpose.formal_research, c["inputs"],
                                    lambda a: self._run_pilot(a, c), None, [rev.id], {"spec": spec.id})
            self.execute_action("check_theory", ActionPurpose.formal_research, {"spec": spec.id},
                                lambda a: self._run_check_theory(a, c), None, [rev.id], {"spec": spec.id})
        else:
            from .backends.ai_scientist_v3 import run_formal_with_v3
            run_formal_with_v3(self, rev, spec)

    def audit(self) -> None:
        from .reporting.audit import audit_claims
        audit_claims(self)
        claims = self.store.list(Claim)
        if claims and self.budget.remaining("llm_calls") >= 1:
            material = {"claims": [c.model_dump(mode="json") for c in claims],
                        "evidence": [e.model_dump(mode="json") for e in self.store.list(Evidence) if e.namespace == "computation"]}

            def commit(result: QueryResult, p) -> list[str]:
                self.store.event("claim_evidence_check", {"payload": result.payload})
                return [result.id]

            self.query(QueryInput("check_claim_evidence", material,
                                  input_refs=[e.id for e in self.store.list(Evidence) if e.namespace == "computation"],
                                  fixture_key="check_claim_evidence"), purpose=ActionPurpose.audit, commit=commit)
        self._set_research_outcome()

    def _set_research_outcome(self) -> None:
        """Formal claims decide the research outcome. Pilot claims decide it only for a
        theoretical task, where a verified counterexample is a genuine disproof; for empirical or
        mixed tasks pilot findings are reported but the research outcome stays not_run."""
        claims = [c for c in self.store.list(Claim) if c.audit_status != "failed"]
        formal = [c for c in claims if c.study_stage == StudyStage.formal]
        pilot = [c for c in claims if c.study_stage != StudyStage.formal]
        summary = "; ".join(f"{c.id}={c.status}/{c.proof_status.value if c.proof_status else '-'}" for c in claims)
        def branch(c: Claim) -> ResearchBranch:
            rev = self.store.get(c.candidate_revision_id)
            return rev.research_branch if isinstance(rev, CandidateRevision) else ResearchBranch.auto

        theory_pilot = [c for c in pilot if branch(c) == ResearchBranch.theoretical]
        if formal:
            pool, stage = formal, "formal"
        elif theory_pilot:
            pool, stage = theory_pilot, "pilot (theoretical branch: counterexamples are disproofs)"
        else:
            self.drun.research_outcome = ResearchOutcome.not_run
            if pilot:
                self.drun.notes.append("research_outcome=not_run: only preliminary checks ran for empirical/mixed "
                                       f"candidates; pilot findings (not research results): {summary}")
            return
        if any(c.status == "refuted" for c in pool):
            self.drun.research_outcome = ResearchOutcome.refuted
        elif all(c.status == "supported" for c in pool) and stage == "formal":
            self.drun.research_outcome = ResearchOutcome.supported
        else:
            self.drun.research_outcome = ResearchOutcome.inconclusive
        self.drun.notes.append(f"research_outcome={self.drun.research_outcome.value} from {stage} claims: {summary}")

    def write(self) -> None:
        from .reporting.reports import write_reports
        write_reports(self)

    def finish(self) -> None:
        from .reporting.reports import write_reports

        self.drun.operation_status = OperationStatus.completed
        if self.drun.planning_outcome == PlanningOutcome.not_run:
            self.drun.planning_outcome = PlanningOutcome.inconclusive
        write_reports(self)          # final statuses in the report
        self.store.export_jsonl(self.run_dir / "export")
        self._save_run(event="run_finished", payload={"planning": self.drun.planning_outcome.value,
                                                      "research": self.drun.research_outcome.value,
                                                      "stop_reason": self.drun.stop_reason.value if self.drun.stop_reason else None})
        self._status_line(force=True)
