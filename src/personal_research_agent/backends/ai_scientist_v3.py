"""AI-Scientist-v3 adapter (plan §9), pinned to commit f8ae47d324edcb6c0d430552f1c7729748c0d411.

Formal experiments, ablations and experimental paper drafts belong to v3. This adapter only:
probes capabilities, materialises a hand-written task from a frozen ResearchSpec using the
upstream scaffold, validates it with the upstream checker (real baseline evaluation), launches
``agsci run`` after ``doctor`` and ``--dry-run``, polls, resumes on the same run directory and
task snapshot, and collects structured evidence. v3's agent/model are configured separately
(``backend.agent``) and never inherit the front-end GPT-6 Pro binding or its prompts.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from ..config import PINNED_V3_COMMIT, BackendConfig
from ..models import ResearchSpec
from .base import (
    BackendError, BackendRun, BackendRunConfig, CapabilityReport, EvidenceBundle, RunStatus, TaskBundle,
    ValidationReport,
)

if TYPE_CHECKING:  # pragma: no cover
    from ..controller import Controller

SCORING_SRC = Path(__file__).resolve().parents[1] / "research" / "mdp_policy_scoring.py"
AGENT_CLIS = {"claude": "claude", "codex": "codex", "cursor": "cursor-agent", "opencode": "opencode",
              "gemini": "gemini", "pi": "pi"}
AGENT_CREDENTIALS = {"claude": ["ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"], "codex": ["OPENAI_API_KEY", "CODEX_API_KEY"],
                     "gemini": ["GEMINI_API_KEY"], "cursor": ["CURSOR_API_KEY"], "opencode": [], "pi": []}
HAND_WRITTEN_PHASES = ("investigation", "ablations", "posthoc", "paper")
CONTRACT_ONLY_PHASES = ("task_drafting", "final_evaluation")


def _sha_dir(root: Path) -> tuple[str, dict[str, str]]:
    files = {}
    for p in sorted(root.rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts and ".venv" not in p.parts:
            files[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest(), files


def _run(argv: list[str], cwd: Path, timeout: float, env: Optional[dict] = None) -> dict:
    """argv arrays only; never a shell string."""
    started = time.time()
    try:
        proc = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)
        return {"argv": argv, "returncode": proc.returncode, "seconds": round(time.time() - started, 2),
                "stdout_tail": proc.stdout[-2000:], "stderr_tail": proc.stderr[-2000:]}
    except subprocess.TimeoutExpired:
        return {"argv": argv, "returncode": None, "seconds": round(time.time() - started, 2), "error": "timeout"}
    except FileNotFoundError as exc:
        return {"argv": argv, "returncode": None, "error": f"not found: {exc.filename}"}


class AIScientistV3Backend:
    name = "ai_scientist_v3"

    def __init__(self, cfg: BackendConfig, work_dir: Path):
        self.cfg = cfg
        self.checkout = Path(cfg.checkout or "")
        self.python = Path(cfg.python or self.checkout / ".venv" / "bin" / "python")
        self.agsci = Path(cfg.agsci or self.checkout / ".venv" / "bin" / "agsci")
        self.work_dir = Path(work_dir).resolve()
        if cfg.inherit_frontend_llm:
            raise BackendError("CONFIG", "v3 must not inherit the front-end LLM configuration")

    # ------------------------------------------------------------------ probe
    def probe(self) -> CapabilityReport:
        missing: list[str] = []
        versions: dict[str, Any] = {}
        if not (self.checkout / "pyproject.toml").exists():
            missing.append(f"checkout not found at {self.checkout}")
            return CapabilityReport(self.name, False, {}, {}, missing, versions)
        head = _run(["git", "rev-parse", "HEAD"], self.checkout, 10)
        versions["commit"] = head.get("stdout_tail", "").strip()
        pinned = self.cfg.pinned_commit or PINNED_V3_COMMIT
        if versions["commit"] != pinned:
            missing.append(f"checkout at {versions['commit'] or '?'} is not the pinned {pinned}")
        lock = self.checkout / "uv.lock"
        versions["uv_lock_sha256"] = hashlib.sha256(lock.read_bytes()).hexdigest() if lock.exists() else None
        help_ = _run([str(self.agsci), "--help"], self.checkout, 60)
        cli_ok = help_.get("returncode") == 0 and "doctor" in help_.get("stdout_tail", "")
        if not cli_ok:
            missing.append("agsci CLI not runnable (run `uv sync` in the checkout)")
        docker = _run(["docker", "info", "--format", "{{.ServerVersion}}"], self.checkout, 15)
        docker_ok = docker.get("returncode") == 0
        versions["docker_server"] = docker.get("stdout_tail", "").strip() or docker.get("stderr_tail", "")[-200:]
        gpu = _run(["nvidia-smi", "-L"], self.checkout, 10).get("returncode") == 0
        agent = self.cfg.agent or {}
        agent_name, agent_model = agent.get("name"), agent.get("model")
        cli = shutil.which(AGENT_CLIS.get(agent_name or "", "")) if agent_name else None
        creds = [k for k in AGENT_CREDENTIALS.get(agent_name or "", []) if os.environ.get(k)]
        env_file = (self.checkout / ".env").exists()
        real_agent = bool(agent_name and (cli or (self.cfg.container_enabled and docker_ok))
                          and (creds or env_file))
        if not agent_name:
            missing.append("backend.agent.name is not set (v3 agent is configured separately from the GPT-6 Pro front end)")
        elif not real_agent:
            missing.append(f"agent {agent_name}: CLI {'found' if cli else 'missing'}, credentials "
                           f"{'present' if creds or env_file else 'missing'} ({AGENT_CREDENTIALS.get(agent_name)})")
        if self.cfg.container_enabled and not docker_ok:
            missing.append("container.enabled=true but the Docker daemon is not reachable")
        latex = shutil.which("pdflatex") is not None
        caps = {
            "scaffold": (self.checkout / "skills/setup-task/scripts/new_task.py").exists(),
            "evaluator_check": (self.checkout / "skills/setup-task/scripts/check_task.py").exists(),
            "cli": cli_ok, "docker": docker_ok, "real_agent": real_agent, "gpu": gpu,
            "sealed_final": False,   # hand-written tasks only; contract tasks need the official drafting route
            "writing": "paper phase (container image provides LaTeX)" if self.cfg.container_enabled else
                       ("paper phase (native pdflatex found)" if latex else "paper phase needs pdflatex or container mode"),
            "agent": {"name": agent_name, "model": agent_model, "reasoning_effort": agent.get("reasoning_effort"),
                      "source": "backend.agent (independent of the front-end ModelBinding)"},
        }
        budget = {"wall_seconds": "strict (process group killed at the run deadline)",
                  "idea_cycles": "strict (investigation.execution.max_idea_cycles)",
                  "replications": "strict (ablations.execution.num_replications)",
                  "workers": "strict", "usd": "best_effort (v3 records metrics/cost_summary.json; no hard cap)",
                  "tokens": "best_effort (recorded by v3, not capped)"}
        return CapabilityReport(self.name, cli_ok and versions["commit"] == pinned, caps, budget, missing, versions)

    def check_budget_capability(self, report: CapabilityReport) -> None:
        for dim in self.cfg.require_strict_budget:
            mode = report.budget_dimensions.get(dim, "none")
            if not mode.startswith("strict"):
                raise BackendError("UNSUPPORTED_BUDGET_CAPABILITY",
                                   f"config requires a strict {dim} cap; v3 supports only {mode}")

    # ------------------------------------------------------------------ task
    def materialize_task(self, spec: ResearchSpec) -> TaskBundle:
        kit = (spec.evaluation or {}).get("task_kit")
        if kit != "mdp_policy":
            raise BackendError("NOT_AVAILABLE", f"no executable task kit {kit!r} in the frozen spec "
                               "(needs a runnable baseline, evaluator-owned scoring and fixed protocol)")
        proto = {k: spec.evaluation[k] for k in ("scenario", "horizon", "p")}
        task_dir = self.work_dir / f"task_{spec.protocol_id}_v{spec.protocol_version}"
        if task_dir.exists():
            shutil.rmtree(task_dir)
        res = _run([str(self.python), str(self.checkout / "skills/setup-task/scripts/new_task.py"), str(task_dir),
                    "--layout", "single", "--entrypoint", "program.py"], self.checkout, 120)
        if res.get("returncode") != 0:
            raise BackendError("SCAFFOLD_FAILED", json.dumps(res)[:500])
        # evaluator: the upstream template with the scoring hook bound to evaluator-owned code
        ev = (task_dir / "evaluate.py").read_text(encoding="utf-8")
        start = ev.index("def score(work: Path, profile: str)")
        end = ev.index("def run_replication(")
        score_fn = (
            "def score(work: Path, profile: str) -> dict[str, float]:\n"
            '    """Exact expected return of the candidate policy, computed by evaluator-owned scoring.py."""\n'
            "    import importlib.util\n"
            "    spec = importlib.util.spec_from_file_location('task_scoring', task_dir() / 'scoring.py')\n"
            "    mod = importlib.util.module_from_spec(spec)\n"
            "    spec.loader.exec_module(mod)\n"
            "    try:\n"
            f"        result = mod.score_artifact(work, {json.dumps(proto)})\n"
            "    except mod.ScoringError as exc:\n"
            "        raise CandidateFailure(str(exc)) from exc\n"
            "    # the harness averages every metric over replications: keep numeric ones only\n"
            "    return {k: float(v) for k, v in result.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}\n\n\n")
        ev = ev[:start] + score_fn + ev[end:]
        ev = ev.replace('PROGRAM_TIMEOUT_SECONDS = {"smoke": 120, "search": 600, "full": 600}',
                        'PROGRAM_TIMEOUT_SECONDS = {"smoke": 30, "search": 60, "full": 60}')
        ev = ev.replace('    return [sys.executable, "-u", str(entrypoint_rel), "--profile", profile]',
                        '    return [sys.executable, "-u", str(entrypoint_rel)]')
        ev = ev.replace("Edit every TODO. Keep the CLI, the output files, and the failure semantics.",
                        "Generated by personal-research-agent from a frozen ResearchSpec; the CLI, output files and failure semantics are upstream's.")
        ev = ev.replace("# --- Task settings (TODO) ---", "# --- Task settings ---")
        ev = ev.replace('    """TODO: the command that runs the candidate (e.g. torchrun ... for multi-GPU training).',
                        '    """The command that runs the candidate.')
        (task_dir / "evaluate.py").write_text(ev, encoding="utf-8")
        shutil.copyfile(SCORING_SRC, task_dir / "scoring.py")
        baseline = spec.evaluation.get("baseline_policy", {"": 0, "0:0": 0, "0:1": 0, "1:0": 0, "1:1": 0})
        (task_dir / "program_0" / "src" / "program.py").write_text(
            "\"\"\"Baseline: a history-independent (open-loop) policy that always plays action 0.\"\"\"\n"
            "import json\n\n"
            f"POLICY = {json.dumps(baseline)}\n\n"
            "if __name__ == '__main__':\n"
            f"    json.dump({{'scenario': {proto['scenario']!r}, 'horizon': {proto['horizon']}, 'p': {str(proto['p'])!r}, "
            "'policy': POLICY}, open('policy.json', 'w'))\n", encoding="utf-8")
        rubric_threshold = spec.evaluation.get("beats_baseline_threshold")
        (task_dir / "task.md").write_text("\n".join([
            "# Goal",
            f"- Hypothesis under test: {spec.hypothesis}",
            f"- Falsification: {spec.falsification}",
            "- Edit only `src/program.py`. It must write `policy.json` with the fixed protocol fields and a policy "
            "mapping each reachable history key (\"\" then \"a1:r1\", \"a1:r1|a2:r2\", ...) to an action in {0,1}.",
            f"- Maximize `combined_score` = exact expected return in scenario {proto['scenario']} "
            f"(horizon {proto['horizon']}, P(theta=1)={proto['p']}), computed by the evaluator from the policy; "
            "`correct.json` must report `correct: true`.",
            "- Each evaluation takes under one second on one CPU core.",
            "- Implement ONE policy per evaluation. Do NOT run sweeps or multiple variants inside one program.",
            "", "# Constraints",
            "- The program must not write score, value, return or metrics fields; the evaluator computes the score.",
            "- The protocol fields (scenario, horizon, p) are frozen.",
            "", "# Rubrics",
            f"- `beats_baseline`: combined_score > {rubric_threshold if rubric_threshold is not None else 1.0}",
            "- `evidence`: every evaluated candidate produces `metrics.json` and `correct.json`.", ""]), encoding="utf-8")
        readme = task_dir / "README.md"
        readme.write_text(readme.read_text(encoding="utf-8") + "\n\n## Provenance\n"
                          f"- Generated by personal-research-agent from ResearchSpec {spec.id} "
                          f"({spec.protocol_id}@{spec.protocol_version}, hash {spec.protocol_hash}).\n"
                          "- Hand-written task: no task_contract.json; phases investigation,ablations,posthoc,paper.\n",
                          encoding="utf-8")
        if (task_dir / "task_contract.json").exists():
            raise BackendError("CONTRACT_FILE", "task_contract.json must never be written by hand")
        sha, files = _sha_dir(task_dir)
        return TaskBundle(task_dir=task_dir, spec_id=spec.id, protocol_hash=spec.protocol_hash, snapshot_sha256=sha,
                          files=files)

    def _negative_programs(self, task: TaskBundle) -> dict[str, str]:
        return {
            "crash": "raise SystemExit(3)\n",
            "self_reported_score": "import json\njson.dump({'scenario':'A','horizon':2,'p':'1/2','policy':{'':0},'score':99}, open('policy.json','w'))\n",
            "missing_artifact": "print('no policy written')\n",
        }

    def validate_task(self, task: TaskBundle) -> ValidationReport:
        checks: list[dict[str, Any]] = []
        errors: list[str] = []
        td = task.task_dir
        for f in ("task.md", "capture.py", "evaluate.py", "program_0/program_spec.toml", "program_0/src/program.py"):
            if not (td / f).exists():
                errors.append(f"missing {f}")
        if (td / "task_contract.json").exists():
            errors.append("task_contract.json present: would switch v3 into sealed contract mode")
        text = (td / "task.md").read_text(encoding="utf-8") if (td / "task.md").exists() else ""
        for section in ("# Goal", "# Rubrics"):
            if section.lower() not in text.lower():
                errors.append(f"task.md lacks {section}")
        if errors:          # structural problems: do not run the upstream checker on a broken task
            return ValidationReport(ok=False, checks=checks, errors=errors)
        check = str(self.checkout / "skills/setup-task/scripts/check_task.py")
        py = str(self.python)
        runs = [("static", [py, check, str(td)], "any"),
                ("smoke", [py, check, str(td), "--run", "--profile", "smoke"], "correct"),
                ("baseline_harness_wrapper", [py, check, str(td), "--run", "--expect", "correct"], "correct"),
                ("replications", [py, check, str(td), "--run", "--num-replications", "2"], "correct")]
        scratch = self.work_dir / "negative_programs"
        for name, src in self._negative_programs(task).items():
            prog = scratch / name
            if prog.exists():
                shutil.rmtree(prog)
            shutil.copytree(td / "program_0", prog)
            (prog / "src" / "program.py").write_text(src, encoding="utf-8")
            runs.append((f"negative_{name}", [py, check, str(td), "--run", "--program", str(prog), "--expect", "incorrect"],
                         "incorrect"))
        for name, argv, expect in runs:
            r = _run(argv, self.checkout, 600)
            r["name"], r["expect"] = name, expect
            checks.append(r)
            if r.get("returncode") != 0:
                errors.append(f"{name} failed (rc={r.get('returncode')}): {(r.get('stdout_tail') or '')[-300:]} {(r.get('stderr_tail') or '')[-300:]}")
        return ValidationReport(ok=not errors, checks=checks, errors=errors)

    # ------------------------------------------------------------------ launch / poll / resume / collect
    def _argv(self, task_dir: Path, run_id: str, results_root: Path, phases: list[str], extra: dict) -> list[str]:
        bad = [p for p in phases if p in CONTRACT_ONLY_PHASES]
        if bad:
            raise BackendError("CONTRACT_PHASE", f"hand-written tasks must not run {bad}")
        agent = self.cfg.agent or {}
        argv = [str(self.agsci), "run", str(task_dir), f'execution.phases="{",".join(phases)}"',
                f"run_id={run_id}", f"paths.results_root={results_root}",
                f"agent.name={agent.get('name')}",
                f"investigation.execution.max_idea_cycles={self.cfg.max_idea_cycles}",
                f"investigation.execution.workers={self.cfg.workers}",
                f"ablations.execution.num_replications={self.cfg.num_replications}",
                f"container.enabled={'true' if self.cfg.container_enabled else 'false'}"]
        if not self.cfg.container_enabled and "paper" in phases:
            # v3 refuses the paper phase for native agents; it runs only the paper in Docker
            argv.append("container.paper_enabled=true")
        if agent.get("model"):
            argv.append(f"agent.model={agent['model']}")
        if agent.get("reasoning_effort"):
            argv.append(f"agent.reasoning_effort={agent['reasoning_effort']}")
        argv += [f"{k}={v}" for k, v in extra.items()]
        return argv

    def preflight(self, task: TaskBundle, run_id: str, results_root: Path, phases: list[str]) -> list[dict]:
        doctor = _run([str(self.agsci), "doctor", str(task.task_dir)], self.checkout, 300)
        dry = _run(self._argv(task.task_dir, run_id, results_root, phases, {}) + ["--dry-run"], self.checkout, 300)
        return [dict(doctor, name="doctor"), dict(dry, name="dry_run")]

    def launch(self, task: TaskBundle, config: BackendRunConfig) -> BackendRun:
        report = self.probe()
        self.check_budget_capability(report)
        if not report.capabilities.get("real_agent"):
            raise BackendError("NOT_AVAILABLE", "; ".join(report.missing) or "no real agent available")
        run_id = config.overrides.get("run_id", f"pra_{int(time.time())}")
        results_root = self.work_dir / "v3_results"
        pre = self.preflight(task, run_id, results_root, config.phases)
        if any(p.get("returncode") != 0 for p in pre):
            raise BackendError("PREFLIGHT_FAILED", json.dumps(pre)[:800])
        argv = self._argv(task.task_dir, run_id, results_root, config.phases, {})
        log = open(self.work_dir / f"agsci_{run_id}.log", "ab")
        proc = subprocess.Popen(argv, cwd=self.checkout, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        run_dir = results_root / task.task_dir.name / str((self.cfg.agent or {}).get("name")) / run_id
        return BackendRun(self.name, run_dir, task.snapshot_sha256, pid=proc.pid, started_at=time.time(),
                          deadline=time.time() + config.wall_seconds, argv=argv, agent=dict(self.cfg.agent or {}))

    def poll(self, run: BackendRun) -> RunStatus:
        alive = False
        if run.pid:
            try:
                os.kill(run.pid, 0)
                alive = True
            except ProcessLookupError:
                alive = False
        if alive and run.deadline and time.time() > run.deadline:
            try:
                os.killpg(run.pid, signal.SIGINT)   # v3 evaluators expect SIGINT
                time.sleep(5)
                os.killpg(run.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            return RunStatus("deadline_exceeded", "interrupted", detail="stopped at the run deadline")
        if alive:
            return RunStatus("running", "running")
        return parse_pipeline_status(run.run_dir)

    def resume(self, run: BackendRun, remaining_phases: list[str]) -> BackendRun:
        if run.run_dir is None or not (run.run_dir / "task").exists():
            raise BackendError("RESUME", "no run-local task snapshot to resume from")
        sha, _ = _sha_dir(run.run_dir / "task")
        if run.task_snapshot_sha256 and sha != run.task_snapshot_sha256:
            # the upstream snapshot honours .agentic_task_ignore; record rather than silently adopt
            raise BackendError("SNAPSHOT_MISMATCH", "run-local task snapshot differs from the launched task; start a new run")
        argv = [str(self.agsci), "run", f"task.dir={run.run_dir / 'task'}", f"paths.run_dir={run.run_dir}",
                f'execution.phases="{",".join(remaining_phases)}"', f"agent.name={run.agent.get('name')}"]
        if run.agent.get("model"):
            argv.append(f"agent.model={run.agent['model']}")
        log = open(self.work_dir / "agsci_resume.log", "ab")
        proc = subprocess.Popen(argv, cwd=self.checkout, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        return BackendRun(self.name, run.run_dir, run.task_snapshot_sha256, pid=proc.pid, started_at=time.time(),
                          deadline=run.deadline, argv=argv, agent=run.agent)

    def collect_evidence(self, run: BackendRun) -> EvidenceBundle:
        return collect_run_dir(run.run_dir, run.task_snapshot_sha256)


# ---------------------------------------------------------------------- parsing (unit-tested)
def parse_pipeline_status(run_dir: Optional[Path]) -> RunStatus:
    if run_dir is None or not run_dir.exists():
        return RunStatus("missing_run_dir", "failed", detail="run directory was not created")
    events_path = run_dir / "pipeline_events.jsonl"
    events = []
    if events_path.exists():
        for line in events_path.read_text(encoding="utf-8").splitlines():
            try:
                events.append(json.loads(line))
            except ValueError:
                continue
    end = next((e for e in reversed(events) if e.get("event") == "pipeline_end"), None)
    phases_done = [e.get("phase") for e in events if e.get("event") in ("phase_end", "phase_completed") and e.get("phase")]
    if end is None:
        return RunStatus("no_pipeline_end", "interrupted", phases_done, "process ended without pipeline_end")
    raw = str(end.get("status"))
    outcome = str(end.get("outcome") or "")
    degraded = any(e.get("status") == "degraded" for e in events if e.get("event") != "pipeline_end")
    if raw in ("failed",):
        norm = "failed"
    elif raw == "interrupted":
        norm = "interrupted"
    elif "no_winner" in outcome or "no winner" in outcome:
        norm = "no_winner"
    elif "not qualified" in outcome or "not_qualified" in outcome:
        norm = "not_qualified"
    elif degraded or raw == "degraded":
        norm = "degraded"
    elif raw in ("completed", "success", "ok"):
        norm = "completed"
    else:
        norm = "unknown"
    return RunStatus(raw, norm, phases_done, outcome)


def collect_run_dir(run_dir: Optional[Path], expected_snapshot: str) -> EvidenceBundle:
    status = parse_pipeline_status(run_dir)
    artifacts: dict[str, str] = {}
    missing: list[str] = []
    metrics: dict[str, Any] = {}
    notes: list[str] = []
    if run_dir is None or not run_dir.exists():
        return EvidenceBundle("execution_error", {}, {}, ["run_dir"], {"status": "not_generated", "reason": "no run dir"},
                              {}, False, status.raw_status)
    snap_ok = False
    if (run_dir / "task").exists():
        sha, _ = _sha_dir(run_dir / "task")
        snap_ok = sha == expected_snapshot
        if not snap_ok:
            notes.append("task snapshot hash differs from the launched task (upstream ignore rules or tampering)")
    else:
        missing.append("task snapshot")
    sel = run_dir / ".downstream_selection.json"
    if sel.exists():
        artifacts[str(sel.relative_to(run_dir))] = hashlib.sha256(sel.read_bytes()).hexdigest()
    else:
        missing.append(".downstream_selection.json")
    best: Optional[dict] = None
    for m in sorted((run_dir / "investigation").rglob("metrics.json")) if (run_dir / "investigation").exists() else []:
        try:
            data = json.loads(m.read_text())
        except ValueError:
            continue
        correct_p = m.parent / "correct.json"
        correct = json.loads(correct_p.read_text()).get("correct") if correct_p.exists() else None
        score = data.get("combined_score")
        artifacts[str(m.relative_to(run_dir))] = hashlib.sha256(m.read_bytes()).hexdigest()
        if correct is True and isinstance(score, (int, float)) and score == score and abs(score) != float("inf"):
            if best is None or score > best["combined_score"]:
                best = {"combined_score": score, "path": str(m.relative_to(run_dir))}
    if best is None:
        missing.append("a correct, finite investigation score")      # kept missing, never filled with 0
    else:
        metrics["best_correct_score"] = best
    cost = {}
    cs = run_dir / "metrics" / "cost_summary.json"
    if cs.exists():
        cost = json.loads(cs.read_text())
    else:
        missing.append("metrics/cost_summary.json")
    paper_files = {str(p.relative_to(run_dir)): hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in (run_dir / "paper").rglob("*") if p.is_file() and p.suffix in (".pdf", ".tex", ".md", ".bib")} \
        if (run_dir / "paper").exists() else {}
    manuscript = {"status": "draft", "files": paper_files} if paper_files else \
        {"status": "not_generated", "reason": "manuscript_missing: v3 produced no paper files"
         + (f" (pipeline {status.normalized})" if status.normalized != "completed" else "")}
    if status.normalized in ("failed", "interrupted", "unknown"):
        outcome = "execution_error"
    elif best is None:
        outcome = "inconclusive"
    else:
        outcome = "inconclusive"   # scientific support is decided by the claim gates, not by exit status
    return EvidenceBundle(outcome, metrics, artifacts, missing, manuscript, cost, snap_ok, status.raw_status, notes)


def run_formal_with_v3(ctrl: "Controller", rev, spec: ResearchSpec) -> None:
    """Formal empirical research through v3, inside the run's budget and deadline."""
    from ..models import ActionPurpose, ActionStatus, ResearchOutcome
    from ..controller import ActionOutcome

    backend = AIScientistV3Backend(ctrl.config.backend, ctrl.run_dir / "backend")
    (ctrl.run_dir / "backend").mkdir(parents=True, exist_ok=True)

    def fn(action) -> "ActionOutcome":
        report = backend.probe()
        ctrl.store.event("v3_probe", {"available": report.available, "missing": report.missing,
                                      "capabilities": report.capabilities, "versions": report.versions,
                                      "budget": report.budget_dimensions})
        backend.check_budget_capability(report)
        task = backend.materialize_task(spec)
        val = backend.validate_task(task)
        ctrl.store.event("v3_task_validation", {"ok": val.ok, "errors": val.errors,
                                                "checks": [{k: c.get(k) for k in ("name", "returncode", "seconds")} for c in val.checks]})
        if not val.ok:
            return ActionOutcome(ActionStatus.failed, f"task validation failed: {val.errors[:2]}", False, [])
        wall = ctrl.budget.action_deadline_seconds(cleanup_margin=30)
        run = backend.launch(task, BackendRunConfig(wall_seconds=wall, phases=list(ctrl.config.backend.phases),
                                                    overrides={"run_id": ctrl.drun.run_id}))
        action.inputs["backend_run_dir"] = str(run.run_dir)
        ctrl.store.update(action, event="v3_launched", event_payload={"argv": run.argv, "pid": run.pid})
        while True:
            st = backend.poll(run)
            if st.normalized != "running":
                break
            time.sleep(30)
            ctrl._status_line(force=True)
        bundle = backend.collect_evidence(run)
        ctrl.store.event("v3_collected", {"outcome": bundle.outcome, "missing": bundle.missing, "raw_status": bundle.raw_status,
                                          "metrics": bundle.metrics, "notes": bundle.notes})
        ctrl.store.event("v3_manuscript", bundle.manuscript)
        status = ActionStatus.failed if bundle.outcome == "execution_error" else ActionStatus.succeeded
        return ActionOutcome(status, f"v3 {st.normalized}; outcome {bundle.outcome}; missing {bundle.missing}",
                             bundle.outcome != "execution_error", list(bundle.artifacts))

    action = ctrl.execute_action("backend_formal", ActionPurpose.formal_research, {"spec": spec.id}, fn, None, [rev.id],
                                 {"spec": spec.id})
    if action.status != ActionStatus.succeeded:
        ctrl.drun.research_outcome = ResearchOutcome.not_run
        ctrl.drun.notes.append(f"formal v3 research not completed: {action.error or action.result_summary}")
