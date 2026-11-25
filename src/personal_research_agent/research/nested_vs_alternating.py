"""CPU clarification pilot for the world-model idea (plan §8.4: distinguish multiple losses /
alternating updates from nested solution dependence).

Toy quadratic, two blocks:
  lower level   g(x, y) = (y - a x)^2 + lam * y^2      ->  y*(x) = a x / (1 + lam)
  upper level   f(x, y) = (x - 1)^2 + c (y - 2)^2
Nested (bilevel) training minimises F(x) = f(x, y*(x)) and differentiates through y*(x).
Alternating training updates x on f with y fixed and y on g with x fixed (two losses, no
solution dependence). Both are run numerically with gradient steps and compared with the
closed-form fixed points. A non-zero gap shows the two readings of "multi-level optimization"
are different problems; it says nothing about world models themselves.
Run:  python -m personal_research_agent.research.nested_vs_alternating --out <dir>
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path


def closed_forms(a: float, lam: float, c: float) -> dict:
    k = a / (1 + lam)                       # y*(x) = k x
    x_nested = (1 + 2 * c * k) / (1 + c * k * k)          # argmin (x-1)^2 + c (k x - 2)^2
    # alternating fixed point: x = argmin_x f(x, y) = 1 ; y = argmin_y g(x, y) = k x
    x_alt = 1.0
    return {"k": k, "x_nested": x_nested, "y_nested": k * x_nested, "x_alternating": x_alt, "y_alternating": k * x_alt}


def upper(x: float, y: float, c: float) -> float:
    return (x - 1) ** 2 + c * (y - 2) ** 2


def run_nested(a: float, lam: float, c: float, steps: int, lr: float) -> tuple[float, float]:
    k = a / (1 + lam)
    x = 0.0
    for _ in range(steps):
        y = k * x
        grad = 2 * (x - 1) + 2 * c * (y - 2) * k     # dF/dx through the lower-level solution map
        x -= lr * grad
    return x, k * x


def run_alternating(a: float, lam: float, c: float, steps: int, lr: float) -> tuple[float, float]:
    x, y = 0.0, 0.0
    for _ in range(steps):
        x -= lr * 2 * (x - 1)                          # df/dx with y held fixed
        y -= lr * (2 * (y - a * x) + 2 * lam * y)      # dg/dy with x held fixed
    return x, y


def run(out_dir: Path, a: float = 1.0, lam: float = 0.5, c: float = 1.0, steps: int = 2000, lr: float = 0.05) -> dict:
    cf = closed_forms(a, lam, c)
    xn, yn = run_nested(a, lam, c, steps, lr)
    xa, ya = run_alternating(a, lam, c, steps, lr)
    res = {
        "setting": {"a": a, "lam": lam, "c": c, "steps": steps, "lr": lr},
        "closed_form": cf,
        "numerical": {"nested": {"x": xn, "y": yn, "upper_objective": upper(xn, yn, c)},
                      "alternating": {"x": xa, "y": ya, "upper_objective": upper(xa, ya, c)}},
        "numerical_matches_closed_form": abs(xn - cf["x_nested"]) < 1e-6 and abs(xa - cf["x_alternating"]) < 1e-6,
        "upper_objective_gap": upper(xa, ya, c) - upper(xn, yn, c),
        "status": "clarification pilot on a toy quadratic; not evidence about world models",
    }
    assert all(math.isfinite(v) for v in (xn, yn, xa, ya))
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "nested_vs_alternating.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    print(json.dumps(run(args.out), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
