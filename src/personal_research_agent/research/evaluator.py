"""Local CPU evaluator for pilot candidates (plan §8.2 rules applied at pilot scale).

Runs the candidate program in a scratch copy with a deadline (never later than the run's
remaining time), in its own process group, then scores the artifact with evaluator-owned code.
Candidate failures (crash, timeout, missing artifact, self-reported score, non-finite score)
give correct=false with a finite worst-case score; evaluator faults raise ``EvaluatorFault``.
"""
from __future__ import annotations

import json
import math
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from .mdp_policy_scoring import ScoringError, score_artifact

WORST_SCORE = -1e9


class EvaluatorFault(RuntimeError):
    pass


@dataclass
class EvalResult:
    correct: bool
    metrics: dict
    error: str | None
    wall_seconds: float
    replications: int


def _run(cmd: list[str], cwd: Path, timeout: float, log: Path) -> int | None:
    env = {k: v for k, v in os.environ.items()
           if not any(t in k.upper() for t in ("KEY", "TOKEN", "SECRET", "PASSWORD", "AUTH", "CREDENTIAL", "PROXY"))}
    env.pop("PYTHONPATH", None)
    with open(log, "wb") as fh:
        proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=fh, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            return proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return None
        finally:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait()


def evaluate_program(program: Path, results_dir: Path, expected: dict, timeout: float,
                     replications: int = 1) -> EvalResult:
    if timeout <= 0:
        raise EvaluatorFault("no time left in the run budget for this evaluation")
    results_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()
    scratch = Path(tempfile.mkdtemp(prefix="pra-eval-"))
    runs: list[dict] = []
    error: str | None = None
    try:
        for i in range(replications):
            work = scratch / f"work_{i}"
            shutil.copytree(program.parent, work)
            remaining = timeout - (time.time() - started)
            code = _run([sys.executable, "-I", program.name], work, max(0.1, remaining), results_dir / f"stdout_{i}.log")
            if code is None:
                error = f"timed out after {remaining:.1f}s"
                break
            if code != 0:
                error = f"program exited with code {code}"
                break
            try:
                runs.append(score_artifact(work, expected))
            except ScoringError as exc:
                error = str(exc)
                break
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    if error is None and runs:
        metrics = {"combined_score": sum(r["combined_score"] for r in runs) / len(runs),
                   "exact_value": runs[0]["exact_value"], "num_replications": len(runs)}
        if not math.isfinite(metrics["combined_score"]):
            error, metrics = "non-finite aggregate score", {"combined_score": WORST_SCORE}
    else:
        metrics = {"combined_score": WORST_SCORE}
    (results_dir / "metrics.json").write_text(json.dumps(metrics, indent=2, sort_keys=True), encoding="utf-8")
    correct = {"correct": error is None, **({"error": error[:500]} if error else {})}
    (results_dir / "correct.json").write_text(json.dumps(correct, indent=2), encoding="utf-8")
    return EvalResult(correct=error is None, metrics=metrics, error=error, wall_seconds=time.time() - started,
                      replications=len(runs))
