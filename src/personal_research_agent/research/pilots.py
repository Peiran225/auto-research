"""Registered local pilots: frozen-protocol CPU computations the local backend may run.

Each pilot returns artifacts plus machine-readable findings. Findings are turned into
``Evidence(kind=computation|counterexample, namespace="computation")`` by the controller, which
keeps them separate from fixture-driven decision evidence.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import mdp_demo, nested_vs_alternating


@dataclass
class PilotFinding:
    claim_key: str                  # which candidate claim the finding bears on
    kind: str                       # computation | counterexample
    holds: bool | None
    observation: str
    artifact: str                   # file name inside the pilot output dir
    locator: str
    assumptions_satisfied: bool | None = None
    scope: str = "finite_instance"


@dataclass
class PilotResult:
    pilot_id: str
    artifacts: list[Path]
    findings: list[PilotFinding] = field(default_factory=list)
    command: str = ""


def _mdp_exact(out: Path, params: dict) -> PilotResult:
    res = mdp_demo.run(out)
    v = res["values"]
    obs = (f"exact enumeration (H=2, p=1/2): V*_A(history)={v['A_history_optimal']['exact']}, "
           f"V*_B(history)={v['B_history_optimal']['exact']}, V*_A(open-loop)={v['A_open_loop_optimal']['exact']}")
    equal = v["A_history_optimal"]["exact"] == v["B_history_optimal"]["exact"]
    return PilotResult("mdp_exact_enumeration", [out / "mdp_values.json", out / "mdp_policy_values.csv"], [
        PilotFinding("eq_history", "counterexample" if not equal else "computation", holds=equal, observation=obs,
                     artifact="mdp_values.json", locator="values", assumptions_satisfied=True),
    ], command=f"python -m personal_research_agent.research.mdp_demo --out {out}")


def _mdp_counterexample(out: Path, params: dict) -> PilotResult:
    claim = params["claim"]
    res = mdp_demo.counterexample_search(claim)
    out.mkdir(parents=True, exist_ok=True)
    name = f"counterexample_search_{claim}.json"
    (out / name).write_text(json.dumps(res, indent=2), encoding="utf-8")
    if res["counterexamples"]:
        first = res["counterexamples"][0]
        f = PilotFinding(claim, "counterexample", holds=False, artifact=name, locator="counterexamples[0]",
                         assumptions_satisfied=first["assumptions_satisfied"],
                         observation=(f"claim {claim} fails at H={first['horizon']}, p={first['p']}: "
                                      f"V_A(history)={first['VA_history']} vs V_B(history)={first['VB_history']}; "
                                      f"{len(res['counterexamples'])}/{res['n_instances']} instances fail"))
    else:
        f = PilotFinding(claim, "computation", holds=True, artifact=name, locator="instances",
                         observation=f"claim {claim} holds on all {res['n_instances']} instances of the finite family "
                                     f"(H in {res['family']['horizons']}, p in {res['family']['p_values']}); "
                                     "finite-instance support only")
    return PilotResult(f"mdp_counterexample:{claim}", [out / name], [f],
                       command=f"python -m personal_research_agent.research.mdp_demo --out {out} --claim {claim}")


def _nested(out: Path, params: dict) -> PilotResult:
    res = nested_vs_alternating.run(out)
    gap = res["upper_objective_gap"]
    differ = abs(res["closed_form"]["x_nested"] - res["closed_form"]["x_alternating"]) > 1e-9
    return PilotResult("nested_vs_alternating", [out / "nested_vs_alternating.json"], [
        PilotFinding("nested_differs_from_alternating", "counterexample", holds=differ, artifact="nested_vs_alternating.json",
                     locator="closed_form", assumptions_satisfied=True, observation=(
                         f"toy quadratic (a=1, lam=0.5, c=1): nested x*={res['closed_form']['x_nested']:.6f}, "
                         f"alternating x={res['closed_form']['x_alternating']:.6f}, upper-objective gap={gap:.6f}; "
                         f"numerical runs match closed forms: {res['numerical_matches_closed_form']}")),
    ], command=f"python -m personal_research_agent.research.nested_vs_alternating --out {out}")


PILOTS: dict[str, Callable[[Path, dict], PilotResult]] = {
    "mdp_exact_enumeration": _mdp_exact,
    "mdp_counterexample": _mdp_counterexample,
    "nested_vs_alternating": _nested,
}
