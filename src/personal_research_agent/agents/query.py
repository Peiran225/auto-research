"""Question-based queries (plan §5): template loading, request assembly, program-side
validation and one bounded repair.

Validation is not just JSON syntax. The runner checks, per answer:
* every template question is answered;
* epistemic rules (facts have a basis and real sources; unknowns are null; hypotheses are testable);
* every cited source resolves in this run and was part of the query input;
* literature locators exist in the retrieved document and the claimed read scope matches what
  was actually retrieved; tool observations cite computation/backend artifacts.
Whether a source *supports* a statement is checked later by Q4; structure passing is not truth.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, ValidationError

from ..models import (
    EpistemicStatus, Evidence, EvidenceKind, ExecutionOrigin, FactBasis, ModelBinding, PaperRecord, QueryResult,
    TaskQuerySpec, TextStatus, stable_hash, sha256_text,
)
from ..store import Store, new_id
from .gateway import LLMGateway
from .providers import LLMRequest, ProviderError
from .schemas import PAYLOADS, Envelope, output_schema

PROMPTS_DIR = Path(__file__).resolve().parents[3] / "prompts"

# Words that would turn a question into a persona/authority prompt (plan §5, T20).
PERSONA_PATTERNS = [
    r"\byou are\b", r"\bact as\b", r"\bas an? (expert|professor|reviewer|scientist)\b", r"\bexpert\b",
    r"\bprofessor\b", r"\breviewer\b", r"你是", r"扮演", r"作为一名", r"专家", r"教授", r"审稿人", r"权威",
]

READ_SCOPE_RANK = {"search_snippet": 0, "abstract": 1, "partial_text": 2, "full_text": 3}
STATUS_MAX_SCOPE = {TextStatus.unavailable: -1, TextStatus.abstract_only: 1, TextStatus.partial_text: 2,
                    TextStatus.full_text: 3}


class QueryValidationError(RuntimeError):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors[:8]))
        self.errors = errors


@dataclass
class Template:
    task_type: str
    version: str
    text: str
    questions: list[dict[str, str]]
    sha256: str


def load_template(name: str, prompts_dir: Path = PROMPTS_DIR) -> Template:
    text = (prompts_dir / f"{name}.txt").read_text(encoding="utf-8")
    version = re.search(r"^template_version:\s*(\S+)", text, re.M)
    questions = [{"id": f"q{m.group(1)}", "text": m.group(2).strip()}
                 for m in re.finditer(r"^\s*(\d+)\.\s+(.+)$", text, re.M)]
    return Template(task_type=name, version=version.group(1) if version else f"{name}-unversioned", text=text,
                    questions=questions, sha256=sha256_text(text))


def prompt_hashes(prompts_dir: Path = PROMPTS_DIR) -> dict[str, str]:
    return {p.stem: sha256_text(p.read_text(encoding="utf-8")) for p in sorted(prompts_dir.glob("*.txt"))}


def persona_violations(text: str) -> list[str]:
    return [p for p in PERSONA_PATTERNS if re.search(p, text, re.I)]


@dataclass
class QueryInput:
    task_type: str
    material: dict[str, Any]               # data passed to the model (not instructions)
    input_refs: list[str]                  # record ids / "paper#loc" / "artifact:..." given as material
    fixture_key: str = ""
    candidate_revision_id: Optional[str] = None
    protocol_id: Optional[str] = None
    protocol_version: Optional[int] = None
    allowed_tools: list[str] = field(default_factory=list)
    context_scope: str = "isolated"


class RefResolver:
    """Resolves references used in answers/payloads: record ids, "paper_id#locator" and
    "artifact:<name>" (computation/backend evidence by artifact name)."""

    def __init__(self, store: Store, run_dir: Path):
        self.store, self.run_dir = store, run_dir

    def paper_and_locator(self, ref: str) -> tuple[Optional[PaperRecord], Optional[str]]:
        pid, _, loc = ref.partition("#")
        rec = self.store.get(pid)
        return (rec if isinstance(rec, PaperRecord) else None), (loc or None)

    def evidence_for(self, ref: str) -> Optional[Evidence]:
        rec = self.store.get(ref)
        if isinstance(rec, Evidence):
            return rec
        if ref.startswith("artifact:"):
            name = ref.split(":", 1)[1]
            for ev in self.store.list(Evidence):
                if ev.artifact_path and Path(ev.artifact_path).name == name or ev.locator == name:
                    return ev
            return None
        if "#" in ref:
            paper, loc = self.paper_and_locator(ref)
            if paper:
                for ev in self.store.list(Evidence):
                    if ev.source_id == paper.id and ev.locator == loc:
                        return ev
        return None

    def exists(self, ref: str) -> bool:
        if self.store.exists(ref):
            return True
        if "#" in ref:
            paper, loc = self.paper_and_locator(ref)
            return paper is not None and self.locator_ok(paper, loc)[0]
        return self.evidence_for(ref) is not None

    def locator_ok(self, paper: PaperRecord, locator: Optional[str]) -> tuple[bool, str]:
        from ..literature.service import load_document_for

        if not locator:
            return False, "missing locator"
        if locator == "abstract":
            return bool(paper.abstract), "abstract not available"
        doc = load_document_for(self.run_dir, paper)
        if doc is None:
            return False, f"no retrieved document for {paper.id}; only metadata/abstract available"
        return doc.has_locator(locator), f"locator {locator} not in retrieved units of {paper.id}"


class QueryRunner:
    def __init__(self, gateway: LLMGateway, store: Store, run_dir: Path, binding: Optional[ModelBinding],
                 max_output_tokens: int = 8000):
        self.gateway, self.store, self.run_dir, self.binding = gateway, store, run_dir, binding
        self.max_output_tokens = max_output_tokens
        self.common = load_template("common_evidence_query")
        self.resolver = RefResolver(store, run_dir)

    # ------------------------------------------------------------------ public
    def run(self, qi: QueryInput, action_id: Optional[str]) -> tuple[QueryResult, BaseModel]:
        tpl = load_template(qi.task_type)
        spec = TaskQuerySpec(
            task_type=qi.task_type, template_version=tpl.version, questions=tpl.questions,
            input_refs=qi.input_refs, allowed_tools=qi.allowed_tools, output_schema_name=f"{qi.task_type}_output",
            context_scope=qi.context_scope, call_budget={"max_output_tokens": self.max_output_tokens},
        )
        request = self._request(tpl, spec, qi)
        response = self.gateway.call(request, action_id)
        repairs = 0
        errors = self._validate_raw(response.output, response.parse_error, tpl, qi)
        output = response.output
        if errors:
            repairs = 1
            self.store.event("query_validation_failed", {"task_type": qi.task_type, "errors": errors[:20],
                                                         "action_id": action_id, "repair": "attempting one bounded repair"})
            repair_tpl = load_template("json_repair")
            repair_req = LLMRequest(
                task_type="json_repair",
                developer_text=self.common.text + "\n\n" + repair_tpl.text + "\n\n" + tpl.text,
                user_payload={"validation_errors": errors, "previous_output": response.raw_text[:60000],
                              "original_material": qi.material},
                output_schema=output_schema(qi.task_type), schema_name=f"{qi.task_type}_output",
                max_output_tokens=self.max_output_tokens, fixture_key=f"{qi.fixture_key or qi.task_type}__repair",
            )
            try:
                repaired = self.gateway.call(repair_req, action_id)
            except ProviderError as exc:
                if exc.code == "FIXTURE_MISSING":
                    raise QueryValidationError(errors) from exc
                raise
            output = repaired.output
            errors = self._validate_raw(repaired.output, repaired.parse_error, tpl, qi)
            if errors:
                self.store.event("query_rejected", {"task_type": qi.task_type, "errors": errors[:20],
                                                    "action_id": action_id})
                raise QueryValidationError(errors)
        assert output is not None
        env = Envelope.model_validate(output)
        payload = PAYLOADS[qi.task_type].model_validate(env.payload)
        result = QueryResult(
            id=new_id("qr"), origin=self.gateway.origin, source=f"query:{qi.task_type}",
            query_id=new_id("q"), task_type=qi.task_type, template_version=tpl.version, input_refs=qi.input_refs,
            input_fingerprint=stable_hash({"t": qi.task_type, "m": qi.material, "r": qi.input_refs}),
            candidate_revision_id=qi.candidate_revision_id, protocol_id=qi.protocol_id,
            protocol_version=qi.protocol_version, execution_origin=self.gateway.origin,
            model_binding_id=self.binding.id if (self.binding and self.gateway.origin == ExecutionOrigin.live) else None,
            answers=env.answers, payload=env.payload,
            unresolved=[a.question_id for a in env.answers if a.epistemic_status == EpistemicStatus.unknown],
            repair_attempts=repairs,
        )
        return result, payload

    # ------------------------------------------------------------------ request
    def _request(self, tpl, spec: TaskQuerySpec, qi: QueryInput) -> LLMRequest:
        developer = "\n\n".join([
            self.common.text, tpl.text,
            "QUESTIONS (answer every id): " + json.dumps(tpl.questions, ensure_ascii=False),
            "ALLOWED TOOLS: " + json.dumps(qi.allowed_tools),
            "INPUT REFERENCES you may cite (anything else is invalid): " + json.dumps(qi.input_refs, ensure_ascii=False),
            "BUDGET: " + json.dumps(spec.call_budget),
            "Return JSON with 'answers' (one or more per question id) and 'payload' matching the schema.",
        ])
        return LLMRequest(task_type=qi.task_type, developer_text=developer, user_payload={"material": qi.material},
                          output_schema=output_schema(qi.task_type), schema_name=f"{qi.task_type}_output",
                          max_output_tokens=self.max_output_tokens, fixture_key=qi.fixture_key)

    # ------------------------------------------------------------------ validation
    def _validate_raw(self, output: Optional[dict], parse_error: Optional[str], tpl, qi: QueryInput) -> list[str]:
        if output is None:
            return [parse_error or "no output"]
        try:
            env = Envelope.model_validate(output)
        except ValidationError as exc:
            return [f"envelope: {e['loc']}: {e['msg']}" for e in exc.errors()][:20]
        errors: list[str] = []
        try:
            PAYLOADS[qi.task_type].model_validate(env.payload)
        except ValidationError as exc:
            errors += [f"payload: {e['loc']}: {e['msg']}" for e in exc.errors()][:20]
        answered = {a.question_id for a in env.answers}
        for q in tpl.questions:
            if q["id"] not in answered:
                errors.append(f"question {q['id']} not answered")
        unknown_ids = answered - {q["id"] for q in tpl.questions}
        if unknown_ids:
            errors.append(f"answers to unknown question ids {sorted(unknown_ids)}")
        allowed = set(qi.input_refs)
        for a in env.answers:
            errors += self._check_answer(a, allowed, answered)
        errors += self._check_payload_refs(env.payload, allowed)
        return errors

    def _allowed(self, ref: str, allowed: set[str]) -> bool:
        if ref in allowed:
            return True
        base = ref.split("#", 1)[0]
        if base in allowed or any(a.split("#", 1)[0] == base for a in allowed):
            return True
        ev = self.resolver.evidence_for(ref)          # e.g. "artifact:<file>" naming given evidence
        return ev is not None and ev.id in allowed

    def _check_answer(self, a, allowed: set[str], answered: set[str]) -> list[str]:
        errs: list[str] = []
        for ref in a.source_refs:
            sid = ref.get("source_id")
            if not sid:
                errs.append(f"{a.question_id}: source_ref without source_id")
                continue
            if not self._allowed(sid, allowed):
                errs.append(f"{a.question_id}: cites {sid}, which was not part of the input")
                continue
            rec = self.store.get(sid.split("#", 1)[0])
            if isinstance(rec, PaperRecord):
                loc = ref.get("locator") or (sid.split("#", 1)[1] if "#" in sid else None)
                ok, why = self.resolver.locator_ok(rec, loc)
                if not ok:
                    errs.append(f"{a.question_id}: {why}")
                scope = ref.get("read_scope")
                if scope not in READ_SCOPE_RANK:
                    errs.append(f"{a.question_id}: read_scope must be one of {sorted(READ_SCOPE_RANK)}")
                elif READ_SCOPE_RANK[scope] > STATUS_MAX_SCOPE[rec.text_status]:
                    errs.append(f"{a.question_id}: claims read_scope={scope} but {rec.id} is {rec.text_status.value}")
            elif not self.resolver.exists(sid):
                errs.append(f"{a.question_id}: unresolvable source {sid}")
            if a.basis_type == FactBasis.tool_observation:
                ev = self.resolver.evidence_for(sid)
                if ev is None or ev.kind not in (EvidenceKind.computation, EvidenceKind.counterexample,
                                                 EvidenceKind.backend_artifact):
                    errs.append(f"{a.question_id}: tool_observation must cite a computation/backend artifact")
            if a.basis_type == FactBasis.source_report and not isinstance(rec, PaperRecord):
                errs.append(f"{a.question_id}: source_report must cite a retrieved paper")
        for pid in a.premise_ids:
            if pid not in answered and not self.resolver.exists(pid):
                errs.append(f"{a.question_id}: premise {pid} is neither an answer id nor a resolvable record")
        for ref in a.contrary_evidence_refs:
            if not self.resolver.exists(ref):
                errs.append(f"{a.question_id}: contrary evidence {ref} unresolvable")
        return errs

    def _check_payload_refs(self, payload: dict, allowed: set[str]) -> list[str]:
        errs: list[str] = []

        def walk(obj: Any, path: str) -> None:
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if k.endswith("_refs") or k in ("nearest_neighbors",):
                        for ref in v or []:
                            if not isinstance(ref, str):
                                continue
                            if not self.resolver.exists(ref):
                                errs.append(f"payload {path}.{k}: unresolvable reference {ref}")
                            elif not self._allowed(ref, allowed) and not self._is_internal(ref):
                                errs.append(f"payload {path}.{k}: {ref} was not part of the input")
                    else:
                        walk(v, f"{path}.{k}")
            elif isinstance(obj, list):
                for i, v in enumerate(obj):
                    walk(v, f"{path}[{i}]")

        walk(payload, "payload")
        return errs

    def _is_internal(self, ref: str) -> bool:
        """Evidence/computation records produced by this run may be cited when passed via
        material; papers must be passed explicitly."""
        rec = self.store.get(ref.split("#", 1)[0])
        return isinstance(rec, Evidence) and rec.kind != EvidenceKind.literature_report
