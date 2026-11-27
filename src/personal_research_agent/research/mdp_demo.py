"""Exact computation for the two-step MDP uncertainty example (plan §8.3).

Setting (horizon H, binary actions a_t in {0,1}, reward r_t = 1[a_t = theta_t], reward seen
immediately):
  A  theta is drawn once per episode (P(theta=1)=p) and stays fixed;
  B  theta_t is drawn i.i.d. at every step with the same marginal.
Both scenarios use the same policy classes:
  history  - deterministic policies mapping the own past actions and rewards to an action;
  open     - history-independent action sequences (the control without history).
Values are expectations computed exactly with Fractions by enumerating every deterministic
policy and every parameter outcome. Randomised policies cannot do better: the value is
linear in the mixture weights, so the maximum is attained at a deterministic policy.

This is a problem-clarification / falsification demonstration, not a new research result.
Run:  python -m personal_research_agent.research.mdp_demo --out <dir>
"""
from __future__ import annotations

import argparse
import csv
import json
import platform
import sys
from fractions import Fraction
from itertools import product
from pathlib import Path
from typing import Callable, Iterator

ACTIONS = (0, 1)
History = tuple  # ((a_1, r_1), ..., (a_k, r_k))


# --------------------------------------------------------------------------- scenarios
def parameter_outcomes(scenario: str, horizon: int, p: Fraction) -> list[tuple[tuple[int, ...], Fraction]]:
    """All parameter sequences (theta_1..theta_H) with their probabilities."""
    def pr(theta: int) -> Fraction:
        return p if theta == 1 else 1 - p

    if scenario == "A":   # fixed per episode
        return [((th,) * horizon, pr(th)) for th in (0, 1)]
    if scenario == "B":   # independent per step
        out = []
        for seq in product((0, 1), repeat=horizon):
            prob = Fraction(1)
            for th in seq:
                prob *= pr(th)
            out.append((seq, prob))
        return out
    raise ValueError(scenario)


# --------------------------------------------------------------------------- policies
def histories(horizon: int) -> list[History]:
    """Decision points of a deterministic history policy: every reachable history of length < H
    is identified by its reward sequence (own actions are determined by the policy itself),
    but we key on (actions, rewards) so the same table works for any policy."""
    out: list[History] = [()]
    frontier: list[History] = [()]
    for _ in range(horizon - 1):
        nxt = []
        for h in frontier:
            for a, r in product(ACTIONS, (0, 1)):
                nxt.append(h + ((a, r),))
        out += nxt
        frontier = nxt
    return out


def history_policies(horizon: int) -> Iterator[dict[History, int]]:
    """Every deterministic history-dependent policy, restricted to the histories it can reach
    (equivalent policies off-path are not enumerated twice)."""
    def build(h: History, depth: int) -> Iterator[dict[History, int]]:
        for a in ACTIONS:
            if depth == horizon - 1:
                yield {h: a}
                continue
            subs = [list(build(h + ((a, r),), depth + 1)) for r in (0, 1)]
            for s0, s1 in product(*subs):
                yield {h: a, **s0, **s1}

    yield from build((), 0)


def open_loop_policies(horizon: int) -> Iterator[tuple[int, ...]]:
    yield from product(ACTIONS, repeat=horizon)


def value_history_policy(policy: dict[History, int], scenario: str, horizon: int, p: Fraction) -> Fraction:
    total = Fraction(0)
    for thetas, prob in parameter_outcomes(scenario, horizon, p):
        h: History = ()
        ret = 0
        for t in range(horizon):
            a = policy[h]
            r = 1 if a == thetas[t] else 0
            ret += r
            h = h + ((a, r),)
        total += prob * ret
    return total


def value_open_loop(actions: tuple[int, ...], scenario: str, horizon: int, p: Fraction) -> Fraction:
    total = Fraction(0)
    for thetas, prob in parameter_outcomes(scenario, horizon, p):
        total += prob * sum(1 for a, th in zip(actions, thetas) if a == th)
    return total


def optimal(values: list[tuple[str, Fraction]]) -> tuple[Fraction, list[str]]:
    best = max(v for _, v in values)
    return best, [name for name, v in values if v == best]


def describe(policy: dict[History, int]) -> str:
    return "; ".join(f"{'∅' if not h else ','.join(f'a{i+1}={a}/r{i+1}={r}' for i, (a, r) in enumerate(h))}->{a}"
                     for h, a in sorted(policy.items(), key=lambda kv: (len(kv[0]), kv[0])))


def solve_instance(horizon: int, p: Fraction) -> dict:
    out: dict = {"horizon": horizon, "p_theta_1": str(p)}
    hist = list(history_policies(horizon))
    opens = list(open_loop_policies(horizon))
    for scenario in ("A", "B"):
        hv = [(describe(pi), value_history_policy(pi, scenario, horizon, p)) for pi in hist]
        ov = [(str(a), value_open_loop(a, scenario, horizon, p)) for a in opens]
        hb, hargs = optimal(hv)
        ob, oargs = optimal(ov)
        out[scenario] = {"history_optimal": hb, "history_argmax": hargs, "open_loop_optimal": ob,
                         "open_loop_argmax": oargs, "n_history_policies": len(hv), "n_open_loop_policies": len(ov),
                         "_all_history": hv, "_all_open": ov}
    return out


def belief_dp_value_A(horizon: int, p: Fraction) -> Fraction:
    """Independent cross-check for scenario A: dynamic programming over the posterior of theta."""
    def v(b: Fraction, steps: int) -> Fraction:
        if steps == 0:
            return Fraction(0)
        best = Fraction(-1)
        for a in ACTIONS:
            p_r1 = b if a == 1 else 1 - b          # P(reward=1) = P(theta=a)
            post_r1 = Fraction(1) if a == 1 else Fraction(0)  # reward 1 reveals theta=a
            post_r0 = Fraction(0) if a == 1 else Fraction(1)  # reward 0 reveals theta=1-a
            val = p_r1 * (1 + v(post_r1, steps - 1)) + (1 - p_r1) * v(post_r0, steps - 1)
            best = max(best, val)
        return best

    return v(p, horizon)


def dp_value_B(horizon: int, p: Fraction) -> Fraction:
    """Cross-check for B: future parameters are independent of the past, so each step is solved alone."""
    return horizon * max(p, 1 - p)


# --------------------------------------------------------------------------- claims on a family
FAMILY = {"horizons": [1, 2, 3], "p_values": ["1/2", "1/3", "2/3", "1/4"]}


def counterexample_search(claim: str, family: dict = FAMILY) -> dict:
    """Check a claim on every instance of a finite family. Claims:
    eq_history   V*_A(history) == V*_B(history)
    eq_open      V*_A(open) == V*_B(open)
    voi_identity V*_A(history) - V*_B(history) == V*_A(history) - V*_A(open)   (i.e. V*_B(history) == V*_A(open))
    b_no_history_gain  V*_B(history) == V*_B(open)
    Every instance satisfies the claim's assumptions by construction (same policy class in A and
    B, rewards observed, binary actions); the result records that check explicitly."""
    checks: Callable[[dict], bool] = {
        "eq_history": lambda s: s["A"]["history_optimal"] == s["B"]["history_optimal"],
        "eq_open": lambda s: s["A"]["open_loop_optimal"] == s["B"]["open_loop_optimal"],
        "voi_identity": lambda s: s["B"]["history_optimal"] == s["A"]["open_loop_optimal"],
        "b_no_history_gain": lambda s: s["B"]["history_optimal"] == s["B"]["open_loop_optimal"],
    }[claim]
    instances = []
    counterexamples = []
    for h in family["horizons"]:
        for ps in family["p_values"]:
            p = Fraction(ps)
            s = solve_instance(h, p)
            assert belief_dp_value_A(h, p) == s["A"]["history_optimal"], "enumeration/DP mismatch (A)"
            assert dp_value_B(h, p) == s["B"]["history_optimal"], "enumeration/DP mismatch (B)"
            row = {"horizon": h, "p": ps,
                   "VA_history": str(s["A"]["history_optimal"]), "VB_history": str(s["B"]["history_optimal"]),
                   "VA_open": str(s["A"]["open_loop_optimal"]), "VB_open": str(s["B"]["open_loop_optimal"]),
                   "assumptions_satisfied": True, "holds": checks(s)}
            instances.append(row)
            if not row["holds"]:
                counterexamples.append(row)
    return {"claim": claim, "family": family, "n_instances": len(instances), "instances": instances,
            "counterexamples": counterexamples,
            "verdict": "counterexample_found" if counterexamples else "holds_on_all_finite_instances",
            "scope_note": "finite family only; holding on these instances does not prove the general statement"}


# --------------------------------------------------------------------------- artifacts
def frac(x: Fraction) -> dict:
    return {"exact": str(x), "float": float(x)}


def run(out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    p = Fraction(1, 2)
    s = solve_instance(2, p)
    results = {
        "instance": {"horizon": 2, "actions": [0, 1], "reward": "r_t = 1[a_t = theta_t], observed immediately",
                     "prior": "P(theta=1) = 1/2",
                     "A": "theta drawn once per episode, fixed", "B": "theta_t drawn i.i.d. per step"},
        "policy_classes": {"history": "deterministic maps from own past (actions, rewards) to an action; same class in A and B",
                           "open_loop": "history-independent action sequences (control)"},
        "values": {
            "A_history_optimal": frac(s["A"]["history_optimal"]),
            "B_history_optimal": frac(s["B"]["history_optimal"]),
            "A_open_loop_optimal": frac(s["A"]["open_loop_optimal"]),
            "B_open_loop_optimal": frac(s["B"]["open_loop_optimal"]),
        },
        "argmax": {"A_history": s["A"]["history_argmax"], "B_history": s["B"]["history_argmax"],
                   "A_open_loop": s["A"]["open_loop_argmax"]},
        "counts": {"history_policies": s["A"]["n_history_policies"], "open_loop_policies": s["A"]["n_open_loop_policies"]},
        "cross_checks": {"A_belief_dp": str(belief_dp_value_A(2, p)), "B_per_step_dp": str(dp_value_B(2, p))},
        "method": "exhaustive enumeration of deterministic policies x exact outcome enumeration with fractions.Fraction",
        "environment": {"python": sys.version.split()[0], "platform": platform.platform()},
        "status": "validation example (problem clarification / falsification demo); not a novel contribution",
    }
    (out_dir / "mdp_values.json").write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    with open(out_dir / "mdp_policy_values.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["scenario", "policy_class", "policy", "value_exact", "value_float"])
        for scenario in ("A", "B"):
            for name, v in s[scenario]["_all_history"]:
                w.writerow([scenario, "history", name, str(v), float(v)])
            for name, v in s[scenario]["_all_open"]:
                w.writerow([scenario, "open_loop", name, str(v), float(v)])
    return results


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--claim", choices=["eq_history", "eq_open", "voi_identity", "b_no_history_gain"])
    args = ap.parse_args(argv)
    if args.claim:
        res = counterexample_search(args.claim)
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / f"counterexample_search_{args.claim}.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
        print(json.dumps({k: res[k] for k in ("claim", "n_instances", "verdict")}))
    else:
        res = run(args.out)
        print(json.dumps(res["values"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
