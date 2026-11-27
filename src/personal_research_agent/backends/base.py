"""Research backend protocol (plan §9) and its data types."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Protocol

from ..models import ResearchSpec


@dataclass
class CapabilityReport:
    backend: str
    available: bool
    capabilities: dict[str, Any]          # scaffold / evaluator / real_agent / gpu / sealed_final / writing ...
    budget_dimensions: dict[str, str]     # dimension -> "strict" | "best_effort" | "none"
    missing: list[str] = field(default_factory=list)
    versions: dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskBundle:
    task_dir: Path
    spec_id: str
    protocol_hash: str
    snapshot_sha256: str
    files: dict[str, str] = field(default_factory=dict)   # relative path -> sha256


@dataclass
class ValidationReport:
    ok: bool
    checks: list[dict[str, Any]]
    errors: list[str] = field(default_factory=list)


@dataclass
class BackendRunConfig:
    wall_seconds: float
    phases: list[str]
    overrides: dict[str, Any] = field(default_factory=dict)


@dataclass
class BackendRun:
    backend: str
    run_dir: Optional[Path]
    task_snapshot_sha256: str
    pid: Optional[int] = None
    started_at: Optional[float] = None
    deadline: Optional[float] = None
    argv: list[str] = field(default_factory=list)
    agent: dict[str, Any] = field(default_factory=dict)


@dataclass
class RunStatus:
    raw_status: str
    normalized: str                 # running | completed | no_winner | not_qualified | degraded | failed | interrupted | unknown
    phases_completed: list[str] = field(default_factory=list)
    detail: str = ""


@dataclass
class EvidenceBundle:
    outcome: str                    # supports | refutes | inconclusive | execution_error | not_run
    metrics: dict[str, Any]
    artifacts: dict[str, str]       # path -> sha256
    missing: list[str]
    manuscript: dict[str, Any]      # {"status": "draft"|"not_generated", "reason":..., "files": {...}}
    cost: dict[str, Any]
    protocol_hash_matches: bool
    raw_status: str
    notes: list[str] = field(default_factory=list)


class ResearchBackend(Protocol):
    def probe(self) -> CapabilityReport: ...
    def materialize_task(self, spec: ResearchSpec) -> TaskBundle: ...
    def validate_task(self, task: TaskBundle) -> ValidationReport: ...
    def launch(self, task: TaskBundle, config: BackendRunConfig) -> BackendRun: ...
    def poll(self, run: BackendRun) -> RunStatus: ...
    def resume(self, run: BackendRun, remaining_phases: list[str]) -> BackendRun: ...
    def collect_evidence(self, run: BackendRun) -> EvidenceBundle: ...


class BackendError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code   # UNSUPPORTED_BUDGET_CAPABILITY | NOT_AVAILABLE | VALIDATION_FAILED | PURPOSE_BOUNDARY | ...
