"""Evaluator-owned scoring for MDP policy candidates (stdlib only, copied verbatim into
AI-Scientist-v3 task directories as ``scoring.py``).

A candidate program writes ``policy.json`` = {"scenario": "A"|"B", "horizon": H, "p": "1/2",
"policy": {"<history>": action}} where <history> is "" for the first step and otherwise
"a1:r1|a2:r2|...". The evaluator computes the exact expected return itself. Any score-like
field written by the candidate is rejected (a candidate cannot report its own score).
"""
from __future__ import annotations

import json
import math
from fractions import Fraction
from itertools import product
from pathlib import Path

SELF_REPORTED_KEYS = {"score", "value", "combined_score", "return", "reward", "metrics"}


class ScoringError(Exception):
    """The candidate's artifact is missing or invalid (candidate failure, not evaluator failure)."""


def _outcomes(scenario: str, horizon: int, p: Fraction):
    pr = lambda th: p if th == 1 else 1 - p  # noqa: E731
    if scenario == "A":
        return [((th,) * horizon, pr(th)) for th in (0, 1)]
    if scenario == "B":
        out = []
        for seq in product((0, 1), repeat=horizon):
            prob = Fraction(1)
            for th in seq:
                prob *= pr(th)
            out.append((seq, prob))
        return out
    raise ScoringError(f"unknown scenario {scenario!r}")


def exact_value(policy: dict, scenario: str, horizon: int, p: Fraction) -> Fraction:
    total = Fraction(0)
    for thetas, prob in _outcomes(scenario, horizon, p):
        key, ret = "", 0
        for t in range(horizon):
            if key not in policy:
                raise ScoringError(f"policy has no action for reachable history {key!r}")
            a = policy[key]
            if a not in (0, 1) or isinstance(a, bool):
                raise ScoringError(f"action must be 0 or 1, got {a!r}")
            r = 1 if a == thetas[t] else 0
            ret += r
            key = f"{key}|{a}:{r}" if key else f"{a}:{r}"
        total += prob * ret
    return total


def score_artifact(work_dir: Path, expected: dict) -> dict:
    path = Path(work_dir) / "policy.json"
    if not path.is_file():
        raise ScoringError("missing artifact policy.json")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ScoringError(f"unreadable policy.json: {exc.__class__.__name__}") from exc
    if not isinstance(payload, dict):
        raise ScoringError("policy.json must be an object")
    reported = SELF_REPORTED_KEYS & set(payload)
    if reported:
        raise ScoringError(f"candidate reported its own score fields {sorted(reported)}; scores are computed by the evaluator")
    for key in ("scenario", "horizon", "p"):
        if str(payload.get(key)) != str(expected[key]):
            raise ScoringError(f"{key} must be {expected[key]!r} (frozen protocol), got {payload.get(key)!r}")
    policy = payload.get("policy")
    if not isinstance(policy, dict):
        raise ScoringError("policy must be a mapping from history keys to actions")
    value = exact_value(policy, expected["scenario"], int(expected["horizon"]), Fraction(str(expected["p"])))
    score = float(value)
    if not math.isfinite(score):
        raise ScoringError("non-finite score")
    return {"combined_score": score, "exact_value": str(value)}
