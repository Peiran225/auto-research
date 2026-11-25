"""Local backend: theory counterexamples, preliminary CPU pilots and offline acceptance only
(plan §8.0). Formal empirical research is refused here and must go to AI-Scientist-v3."""
from __future__ import annotations

import multiprocessing as mp
import platform
import time
from pathlib import Path
from typing import Any

from ..models import ResearchSpec, StudyStage, ResearchBranch
from ..research.pilots import PILOTS, PilotResult
from .base import (
    BackendError, BackendRun, BackendRunConfig, CapabilityReport, EvidenceBundle, RunStatus, TaskBundle,
    ValidationReport,
)


def _child(pilot: str, out: str, params: dict, q: Any) -> None:
    try:
        res = PILOTS[pilot](Path(out), params)
        q.put(("ok", res))
    except Exception as exc:  # pragma: no cover - reported to the parent
        q.put(("error", f"{type(exc).__name__}: {exc}"))


class LocalBackend:
    name = "local"

    def probe(self) -> CapabilityReport:
        return CapabilityReport(
            backend="local", available=True,
            capabilities={"theory_counterexample": True, "cpu_pilot": True, "formal_empirical": False,
                          "gpu": False, "writing": "deterministic templates only", "pilots": sorted(PILOTS)},
            budget_dimensions={"wall_seconds": "strict", "pilots": "strict", "usd": "strict (no paid calls)"},
            versions={"python": platform.python_version()},
        )

    def check_purpose(self, spec: ResearchSpec) -> None:
        if spec.study_stage == StudyStage.formal and spec.research_branch in (ResearchBranch.empirical, ResearchBranch.mixed):
            raise BackendError("PURPOSE_BOUNDARY", "formal empirical research must run on ai_scientist_v3, not the local backend")

    def run_pilot(self, spec: ResearchSpec, out_dir: Path, deadline_seconds: float) -> PilotResult:
        self.check_purpose(spec)
        plan = spec.counterexample_search_plan or spec.evaluation
        pilot = plan.get("pilot_id")
        if pilot not in PILOTS:
            raise BackendError("NOT_AVAILABLE", f"no registered local pilot {pilot!r}; this check needs another backend")
        if deadline_seconds <= 0:
            raise BackendError("NO_TIME", "no run time left for the pilot")
        ctx = mp.get_context("fork")
        q = ctx.Queue()
        proc = ctx.Process(target=_child, args=(pilot, str(out_dir), plan, q), daemon=True)
        proc.start()
        proc.join(deadline_seconds)
        if proc.is_alive():
            proc.kill()
            proc.join()
            raise BackendError("TIMEOUT", f"pilot {pilot} exceeded {deadline_seconds:.1f}s")
        status, payload = q.get(timeout=5)
        if status != "ok":
            raise BackendError("PILOT_ERROR", payload)
        return payload

    # The generic protocol methods exist so the controller can treat both backends alike.
    def materialize_task(self, spec: ResearchSpec) -> TaskBundle:  # pragma: no cover - not used locally
        raise BackendError("NOT_AVAILABLE", "the local backend runs registered pilots directly")

    def validate_task(self, task: TaskBundle) -> ValidationReport:  # pragma: no cover
        return ValidationReport(ok=True, checks=[])

    def launch(self, task: TaskBundle, config: BackendRunConfig) -> BackendRun:  # pragma: no cover
        raise BackendError("NOT_AVAILABLE", "use run_pilot")

    def poll(self, run: BackendRun) -> RunStatus:  # pragma: no cover
        return RunStatus(raw_status="n/a", normalized="completed")

    def resume(self, run: BackendRun, remaining_phases: list[str]) -> BackendRun:  # pragma: no cover
        return run

    def collect_evidence(self, run: BackendRun) -> EvidenceBundle:  # pragma: no cover
        raise BackendError("NOT_AVAILABLE", "local pilots return findings directly")
