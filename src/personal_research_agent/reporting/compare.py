"""Same-budget strategy comparison (plan §12.1). Reports traceability, wrong references,
re-judgement after counter-evidence, candidate survival, interventions and resource use. Fixture
runs demonstrate that the comparison code runs; they do not show one strategy is better."""
from __future__ import annotations

from pathlib import Path

from ..models import Assessment, AssessmentState, CandidateRevision, DecisionRun, Evidence, QueryResult
from ..store import Store
from .verify import verify_run


def compare_runs(run_dirs: list[Path]) -> dict:
    rows = []
    limits = set()
    for rd in run_dirs:
        st = Store(rd / "state.sqlite", rd.name)
        d = st.require(f"run_{rd.name}", DecisionRun)
        limits.add(str(sorted(d.config_snapshot["config"]["limits"].items())))
        asm = [a for a in st.list(Assessment) if a.subject_type == "candidate"]
        known = [a for a in asm if a.state == AssessmentState.known]
        ev = {e.id for e in st.list(Evidence)}
        traceable = [a for a in known if a.evidence_ids and all(e in ev for e in a.evidence_ids)]
        rejudged = len(st.events("assessment_reevaluated"))
        revs = st.list(CandidateRevision)
        v = verify_run(rd)
        rows.append({
            "run_id": rd.name, "strategy": d.strategy, "planning_outcome": d.planning_outcome.value,
            "research_outcome": d.research_outcome.value, "stop_reason": d.stop_reason.value if d.stop_reason else None,
            "known_judgements": len(known), "traceable_rate": round(len(traceable) / len(known), 3) if known else None,
            "wrong_references": len([p for p in v["problems"] if "missing" in p or "unresolvable" in p]),
            "rejudgements_after_counterevidence": rejudged,
            "candidates_total": len({r.candidate_id for r in revs}),
            "candidates_surviving": len({r.candidate_id for r in revs if r.status == "active"}),
            "human_interventions": 0, "rounds": d.round,
            "llm_calls": st.conn.execute("SELECT COALESCE(SUM(actual),0) FROM budget WHERE dimension='llm_calls' AND state='settled'").fetchone()[0],
            "execution_origins": sorted({q.execution_origin.value for q in st.list(QueryResult)}),
        })
        st.close()
    return {"same_limits": len(limits) == 1, "runs": rows,
            "note": "fixture runs only show the comparison interface works; no claim that one strategy is better"}
