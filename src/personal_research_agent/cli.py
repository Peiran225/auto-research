"""pra — personal research agent CLI (plan §11.1).

Exit codes: 0 finished (including valid negative / inconclusive results and paused runs),
2 configuration error, 3 run failure, 4 blocked dependency (provider/backend unavailable).
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import warnings
from pathlib import Path
from typing import Optional

import typer

warnings.filterwarnings("ignore", message=".*shadows an attribute in parent.*")

from .config import PROJECT_ROOT, ConfigError, load_config  # noqa: E402

app = typer.Typer(add_completion=False, help="Personal research agent (budgeted, resumable).")

EXIT_OK, EXIT_CONFIG, EXIT_FAILURE, EXIT_BLOCKED = 0, 2, 3, 4


def _runs_root() -> Path:
    return Path(os.environ.get("PRA_RUNS_ROOT", PROJECT_ROOT / "runs"))


def _exit_for(drun) -> int:
    from .models import OperationStatus

    if drun.operation_status == OperationStatus.failed:
        return EXIT_FAILURE
    if drun.operation_status == OperationStatus.blocked_dependency:
        return EXIT_BLOCKED
    return EXIT_OK


def _summary(drun) -> dict:
    return {"run_id": drun.run_id, "phase": drun.phase.value, "operation_status": drun.operation_status.value,
            "planning_outcome": drun.planning_outcome.value, "research_outcome": drun.research_outcome.value,
            "manuscript_status": drun.manuscript_status.value,
            "stop_reason": drun.stop_reason.value if drun.stop_reason else None, "rounds": drun.round,
            "recommended": drun.recommended_candidate_revision_id, "error": drun.error,
            "reports": f"runs/{drun.run_id}/reports/"}


@app.command()
def doctor(config: Path = typer.Option(..., help="run config YAML"),
           check_live: bool = typer.Option(False, help="also contact free endpoints (model listing, arXiv) in live mode")):
    """List capabilities and the exact missing items. Never starts a paid task."""
    try:
        cfg = load_config(config)
    except ConfigError as exc:
        typer.echo(f"CONFIG ERROR: {exc}")
        raise typer.Exit(EXIT_CONFIG)
    from .agents.binding import sdk_mapping_evidence
    from .backends.local import LocalBackend

    report: dict = {"mode": cfg.mode, "strategy": cfg.decision.get("strategy"), "limits": cfg.limits.model_dump()}
    missing: list[str] = []
    if cfg.llm.provider == "fixture":
        report["llm"] = {"provider": "fixture", "note": "offline fixture; no model probe, no credentials, no network"}
    else:
        key_present = bool(os.environ.get(cfg.llm.credential_env))
        report["llm"] = {"provider": "openai", "api": "responses", "model": cfg.llm.model,
                         "reasoning": cfg.llm.reasoning, "effort_sent": False, "credential_env": cfg.llm.credential_env,
                         "credential_present": key_present, "sdk": sdk_mapping_evidence(),
                         "pricing": cfg.llm.pricing,
                         "model_choice": "official GPT-6 Pro mapping" if cfg.llm.is_official_mapping
                         else f"user override: {cfg.llm.override_reason}"}
        if not key_present:
            missing.append(f"export {cfg.llm.credential_env}=<key> (read from the environment only)")
        if cfg.llm.pricing.get("input_per_mtok") is None or cfg.llm.pricing.get("output_per_mtok") is None:
            missing.append("llm.pricing input/output per MTok: needed to enforce limits.api_usd (otherwise calls are 'unpriced')")
        if check_live:
            from .controller import Controller
            report["llm"]["mapping_check"] = Controller.check_mapping(cfg)
    report["literature"] = {"provider": cfg.literature.provider}
    if check_live and cfg.literature.provider == "arxiv":
        from .literature.providers import ArxivProvider
        try:
            hits = ArxivProvider(cfg.literature.request_timeout_seconds).search("robust Markov decision process", 1)
            report["literature"]["live_search"] = f"ok ({hits[0].canonical_id if hits else 'no hits'})"
        except Exception as exc:
            report["literature"]["live_search"] = f"failed: {exc}"
            missing.append(f"literature provider {cfg.literature.provider} unreachable: {exc}")
    if cfg.backend.kind == "local":
        report["backend"] = LocalBackend().probe().__dict__
    else:
        from .backends.ai_scientist_v3 import AIScientistV3Backend
        rep = AIScientistV3Backend(cfg.backend, _runs_root() / "_doctor").probe()
        report["backend"] = rep.__dict__
        missing += rep.missing
    report["environment"] = {"pdflatex": shutil.which("pdflatex") is not None, "docker": shutil.which("docker") is not None,
                             "gpu": shutil.which("nvidia-smi") is not None, "python": sys.version.split()[0]}
    report["missing"] = missing
    typer.echo(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    raise typer.Exit(EXIT_OK)


@app.command()
def run(task: Path = typer.Option(...), profile: Path = typer.Option(...), config: Path = typer.Option(...),
        run_id: str = typer.Option(...),
        strategy: Optional[str] = typer.Option(None, help="one_shot | evidence_loop | personalized_loop"),
        until: Optional[str] = typer.Option(None, help="stop before the phase after this one")):
    """Run the closed loop allowed by the config."""
    from .controller import Controller

    try:
        ctrl = Controller.create(task, profile, config, run_id, strategy, _runs_root())
    except ConfigError as exc:
        typer.echo(f"CONFIG ERROR: {exc}")
        raise typer.Exit(EXIT_CONFIG)
    drun = ctrl.run(until)
    typer.echo(json.dumps(_summary(drun), indent=2, ensure_ascii=False))
    raise typer.Exit(_exit_for(drun))


@app.command()
def resume(run_id: str = typer.Option(...), until: Optional[str] = typer.Option(None),
           retry_failed: bool = typer.Option(False, help="reopen a failed/blocked run; completed steps are reused, failed ones retried within limits"),
           raise_limit: list[str] = typer.Option([], "--raise-limit", help="raise a frozen limit, e.g. --raise-limit api_usd=35 (only increases; recorded)"),
           reopen_at: Optional[str] = typer.Option(None, "--reopen-at", help="restart a finished run from an earlier phase (clarify ... acquire_evidence); finished steps are reused")):
    """Idempotent resume: finished runs are not re-run; completed actions are not repeated or re-charged."""
    from .controller import Controller

    try:
        if raise_limit:
            raises = {}
            for item in raise_limit:
                key, _, value = item.partition("=")
                raises[key.strip()] = float(value)
            typer.echo(json.dumps({"limits_raised": Controller.raise_limits(run_id, raises, _runs_root())}))
        if reopen_at:
            typer.echo(json.dumps({"reopened_from": Controller.reopen_at(run_id, reopen_at, _runs_root())}))
        ctrl = Controller.open(run_id, _runs_root())
    except (ConfigError, ValueError) as exc:
        typer.echo(f"CONFIG ERROR: {exc}")
        raise typer.Exit(EXIT_CONFIG)
    from .models import OperationStatus
    if ctrl.drun.operation_status == OperationStatus.completed:
        typer.echo(f"run {run_id} already completed; nothing to resume")
        typer.echo(json.dumps(_summary(ctrl.drun), indent=2, ensure_ascii=False))
        raise typer.Exit(EXIT_OK)
    drun = ctrl.run(until, retry_failed=retry_failed)
    typer.echo(json.dumps(_summary(drun), indent=2, ensure_ascii=False))
    raise typer.Exit(_exit_for(drun))


@app.command()
def status(run_id: str = typer.Option(...)):
    """operation / planning / research / manuscript states and budget use."""
    from .budget import Budget
    from .models import DecisionRun
    from .store import Store

    run_dir = _runs_root() / run_id
    if not (run_dir / "state.sqlite").exists():
        typer.echo(f"no run {run_id}")
        raise typer.Exit(EXIT_CONFIG)
    store = Store(run_dir / "state.sqlite", run_id)
    drun = store.require(f"run_{run_id}", DecisionRun)
    b = Budget(store, drun.config_snapshot["config"]["limits"], drun.deadline_epoch).snapshot()
    typer.echo(json.dumps({**_summary(drun), "budget": b, "notes": drun.notes}, indent=2, ensure_ascii=False))


@app.command()
def report(run_id: str = typer.Option(...)):
    """Regenerate reports only. No model, search or backend call is made."""
    from .controller import Controller
    from .reporting.reports import write_reports

    ctrl = Controller.open(run_id, _runs_root(), check_drift=False)
    out = write_reports(ctrl)
    typer.echo(json.dumps(out, indent=2, ensure_ascii=False))


@app.command()
def verify(run_id: str = typer.Option(...)):
    """Check citations, artifact hashes, budget ledger and claim-to-evidence links."""
    from .reporting.verify import verify_run

    res = verify_run(_runs_root() / run_id)
    typer.echo(json.dumps(res, indent=2, ensure_ascii=False, default=str))
    raise typer.Exit(EXIT_OK if res["ok"] else EXIT_FAILURE)


@app.command()
def compare(run_ids: list[str] = typer.Argument(..., help="runs of the same task under different strategies")):
    """Strategy comparison table (plan §12.1). Fixture runs only show that the code works."""
    from .reporting.compare import compare_runs

    typer.echo(json.dumps(compare_runs([_runs_root() / r for r in run_ids]), indent=2, ensure_ascii=False))


@app.command("import")
def import_(run_id: str = typer.Option(...), source: str = typer.Option(..., help="arXiv URL/id, DOI, paper URL or local PDF/text")):
    """Import a paper you provide into a run (charged as one full-text read). Offline runs accept
    only local files."""
    from .controller import Controller
    from .netguard import forbid_network

    ctrl = Controller.open(run_id, _runs_root(), check_drift=False)
    if ctrl.config.mode == "offline_local" and not Path(source).expanduser().exists():
        typer.echo("CONFIG ERROR: offline_local runs can only import local files")
        raise typer.Exit(EXIT_CONFIG)
    if ctrl.config.mode == "offline_local":
        with forbid_network():
            paper = ctrl.lit.import_source(source)
    else:
        paper = ctrl.lit.import_source(source)
    typer.echo(json.dumps({"paper_id": paper.id, "canonical_id": paper.canonical_id, "text_status": paper.text_status.value,
                           "units": len(paper.read_scope)}, indent=2))


@app.command("v3-validate")
def v3_validate(config: Path = typer.Option(..., help="config with backend.kind=ai_scientist_v3"),
                out: Path = typer.Option(PROJECT_ROOT / "runs" / "_v3_validation")):
    """Materialise the MDP CPU task with the pinned v3 scaffold and run the upstream task checker
    (real baseline evaluation and negative programs). No agent is launched."""
    from .backends.ai_scientist_v3 import AIScientistV3Backend
    from .models import ExecutionOrigin, ResearchBranch, ResearchSpec, StudyStage

    try:
        cfg = load_config(config)
    except ConfigError as exc:
        typer.echo(f"CONFIG ERROR: {exc}")
        raise typer.Exit(EXIT_CONFIG)
    backend = AIScientistV3Backend(cfg.backend, out)
    out.mkdir(parents=True, exist_ok=True)
    probe = backend.probe()
    spec = ResearchSpec(id="spec_v3_integration", origin=ExecutionOrigin.offline_local, source="pra v3-validate",
                        study_stage=StudyStage.pilot, candidate_revision_id="integration_check",
                        protocol_id="proto_mdp_policy", protocol_version=1, research_branch=ResearchBranch.empirical,
                        hypothesis="a history-dependent policy can exceed the open-loop baseline value 1 in scenario A",
                        falsification="no correct candidate scores above 1",
                        evaluation={"task_kit": "mdp_policy", "scenario": "A", "horizon": 2, "p": "1/2",
                                    "beats_baseline_threshold": 1.0})
    bundle = backend.materialize_task(spec)
    val = backend.validate_task(bundle)
    result = {"probe": probe.__dict__, "task_dir": str(bundle.task_dir), "snapshot_sha256": bundle.snapshot_sha256,
              "validation_ok": val.ok, "errors": val.errors,
              "checks": [{k: c.get(k) for k in ("name", "expect", "returncode", "seconds", "stdout_tail")} for c in val.checks]}
    (out / "v3_validation.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    typer.echo(json.dumps({k: result[k] for k in ("task_dir", "validation_ok", "errors")} |
                          {"checks": [(c["name"], c["returncode"]) for c in result["checks"]]}, indent=2, default=str))
    raise typer.Exit(EXIT_OK if val.ok else EXIT_FAILURE)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
