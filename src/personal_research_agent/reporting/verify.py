"""``pra verify``: offline integrity checks of a finished run. Opens the store read-only in
practice: no provider, search or backend is constructed, so no research call or cost can occur."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..models import (
    Assessment, AssessmentState, Claim, DecisionRun, Evidence, EvidenceLink, ExecutionOrigin, ModelBinding,
    QueryResult, sha256_text,
)
from ..store import Store
from .audit import check_claim


def verify_run(run_dir: Path) -> dict[str, Any]:
    run_id = run_dir.name
    store = Store(run_dir / "state.sqlite", run_id)
    problems: list[str] = []
    checks: dict[str, Any] = {}
    try:
        drun = store.require(f"run_{run_id}", DecisionRun)
        ev = {e.id: e for e in store.list(Evidence)}
        links = {l.id: l for l in store.list(EvidenceLink)}
        # references
        for l in links.values():
            if l.evidence_id not in ev:
                problems.append(f"link {l.id} -> missing evidence {l.evidence_id}")
            if not store.exists(l.candidate_revision_id):
                problems.append(f"link {l.id} -> missing revision {l.candidate_revision_id}")
        for a in store.list(Assessment):
            for eid in a.evidence_ids + a.contrary_evidence_ids:
                if eid not in ev:
                    problems.append(f"assessment {a.id} cites missing evidence {eid}")
            if a.state == AssessmentState.unknown and a.judgment is not None:
                problems.append(f"assessment {a.id}: unknown with a judgment")
        bindings = {b.id for b in store.list(ModelBinding)}
        for q in store.list(QueryResult):
            if q.execution_origin == ExecutionOrigin.live and q.model_binding_id not in bindings:
                problems.append(f"live query {q.id} without the run binding")
            if q.execution_origin == ExecutionOrigin.live and drun.model_binding_id and q.model_binding_id != drun.model_binding_id:
                problems.append(f"query {q.id} used binding {q.model_binding_id}, run binding is {drun.model_binding_id}")
        checks["references"] = "ok" if not problems else "problems"
        # artifacts
        n_art = 0
        for e in ev.values():
            if e.artifact_path:
                n_art += 1
                p = run_dir / e.artifact_path
                if not p.exists():
                    problems.append(f"artifact missing {e.artifact_path}")
                elif sha256_text(p.read_text(encoding="utf-8")) != e.content_hash:
                    problems.append(f"artifact hash mismatch {e.artifact_path}")
        checks["artifacts"] = n_art
        # claims
        for c in store.list(Claim):
            f = check_claim(c, links, ev, run_dir)
            if f:
                if c.audit_status == "passed":
                    problems.append(f"claim {c.id} marked passed but now fails: {f}")
                if c.usable_in_manuscript:
                    problems.append(f"claim {c.id} usable in manuscript despite findings")
        checks["claims"] = len(store.list(Claim))
        # budget ledger
        cfg = drun.config_snapshot["config"]["limits"]
        from ..budget import LIMIT_KEYS
        rows = store.conn.execute("SELECT dimension, reserved, actual, state, action_id, attempt FROM budget").fetchall()
        open_rows = [r for r in rows if r[3] == "reserved"]
        if open_rows and drun.operation_status.value == "completed":
            problems.append(f"{len(open_rows)} budget reservation(s) still open after completion")
        used: dict[str, float] = {}
        for dim, reserved, actual, state, *_ in rows:
            if state == "settled":
                used[dim] = used.get(dim, 0) + (actual if actual is not None else reserved)
        for dim, total in used.items():
            limit = float(cfg.get(LIMIT_KEYS.get(dim, ""), 0) or 0)
            if LIMIT_KEYS.get(dim) and total > limit + 1e-9:
                problems.append(f"budget {dim} used {total} > limit {limit}")
        dup = store.conn.execute("SELECT action_id, attempt, dimension, COUNT(*) FROM budget WHERE dimension='actions' "
                                 "GROUP BY action_id, attempt HAVING COUNT(*) > 1").fetchall()
        if dup:
            problems.append(f"double-charged action attempts: {dup}")
        checks["budget_used"] = used
        # reports & fixture contamination of the research note
        rep = run_dir / "reports"
        note = rep / "research_note.md"
        if note.exists():
            text = note.read_text(encoding="utf-8")
            fixture_ids = [e.id for e in ev.values() if e.namespace == "fixture"] + ["fixture:"]
            leaked = [i for i in fixture_ids if i in text]
            if leaked:
                problems.append(f"research note contains fixture material: {leaked[:5]}")
            values_files = list((run_dir / "artifacts").rglob("mdp_values.json"))
            if values_files:
                vals = json.loads(values_files[0].read_text())["values"]
                for key, v in vals.items():
                    if v["exact"] not in text:
                        problems.append(f"research note does not show computed {key}={v['exact']}")
        for name in ("decision_report.md", "evidence_manifest.json", "claim_evidence_map.json"):
            if not (rep / name).exists():
                problems.append(f"missing report {name}")
        checks["status"] = {"operation": drun.operation_status.value, "planning": drun.planning_outcome.value,
                            "research": drun.research_outcome.value, "manuscript": drun.manuscript_status.value}
    finally:
        store.close()
    return {"run_id": run_id, "ok": not problems, "problems": problems, "checks": checks}
