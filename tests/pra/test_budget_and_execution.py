"""T06–T08, T10, T12, T17: bounded retries, atomic budget, outcomes vs faults, theory rules, evaluator."""
import json
import sys
import threading
import time
from pathlib import Path

import pytest

from personal_research_agent.agents.gateway import LLMGateway
from personal_research_agent.agents.providers import FixtureProvider, LLMRequest, ProviderError
from personal_research_agent.budget import Budget, BudgetExceeded
from personal_research_agent.models import ExecutionOrigin, ProofStatus
from personal_research_agent.research.evaluator import evaluate_program
from personal_research_agent.research.theory import ProofStatusError, TheoryEvidence, TheoryState, apply
from personal_research_agent.store import Store

from .conftest import LIMITS


class _Timeouts:
    origin = ExecutionOrigin.fixture
    calls = 0

    def complete(self, request, timeout):
        self.calls += 1
        raise ProviderError("TIMEOUT", "simulated provider timeout")


def _req():
    return LLMRequest(task_type="clarify_problem", developer_text="q", user_payload={}, output_schema={},
                      schema_name="x", max_output_tokens=100)


# T06 ------------------------------------------------------------------------------------------
def test_t06_provider_timeouts_and_duplicates_stay_within_limits(store, budget):
    prov = _Timeouts()
    gw = LLMGateway(prov, store, budget, None, max_retries=1, sleep=lambda s: None)
    with pytest.raises(ProviderError):
        gw.call(_req(), action_id="a1")
    assert prov.calls == 2                                    # 1 try + 1 bounded retry, then stop
    assert budget.used("llm_calls") == 2                      # failed attempts are charged
    events = [e["payload"]["code"] for e in store.events("llm_call_failed")]
    assert events == ["TIMEOUT", "TIMEOUT"]


# T07 ------------------------------------------------------------------------------------------
def test_t07_parallel_reservations_cannot_share_the_last_unit(tmp_path):
    path = tmp_path / "state.sqlite"
    Store(path, "t").close()
    limits = dict(LIMITS, max_actions=1)
    results = []

    def worker():
        s = Store(path, "t")
        b = Budget(s, limits, time.time() + 60)
        try:
            b.reserve({"actions": 1}, action_id=f"act-{threading.get_ident()}")
            results.append("ok")
        except BudgetExceeded:
            results.append("refused")
        finally:
            s.close()

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == ["ok", "refused", "refused", "refused"]


def test_t07_settlement_is_idempotent_and_failures_are_charged(store, budget):
    res = budget.reserve({"pilots": 1, "actions": 1}, "a1")
    budget.settle(res, {"pilots": 1, "actions": 1})
    budget.settle(res, {"pilots": 1, "actions": 1})          # resume must not charge twice
    assert budget.used("pilots") == 1 and budget.used("actions") == 1


# T08 ------------------------------------------------------------------------------------------
def test_t08_negative_result_is_success_and_code_fault_is_failure(tmp_path, runs_root):
    from personal_research_agent.backends.base import BackendError
    from personal_research_agent.controller import ActionOutcome, Controller
    from personal_research_agent.models import ActionPurpose, ActionStatus

    root = Path(__file__).resolve().parents[2]
    ctrl = Controller.create(root / "examples/mdp_uncertainty.yaml", root / "profiles/peiran.yaml",
                             root / "configs/offline.yaml", "t08", None, runs_root)
    neg = ctrl.execute_action("cpu_pilot", ActionPurpose.preliminary_check, {"k": 1},
                              lambda a: ActionOutcome(ActionStatus.succeeded, "hypothesis refuted by counterexample", True, []))
    assert neg.status == ActionStatus.succeeded

    def broken(a):
        raise BackendError("PILOT_ERROR", "ZeroDivisionError in pilot code")

    fault = ctrl.execute_action("cpu_pilot", ActionPurpose.preliminary_check, {"k": 2}, broken)
    assert fault.status == ActionStatus.failed and "PILOT_ERROR" in fault.error


# T10 ------------------------------------------------------------------------------------------
def test_t10_finite_checks_never_prove_and_failed_proofs_never_disprove():
    s = TheoryState(statement="for all H", scope="general")
    apply(s, TheoryEvidence("finite_instance", "e1", holds=True))
    assert s.status == ProofStatus.draft
    with pytest.raises(ProofStatusError):
        apply(s, TheoryEvidence("checker", "e2", checker="numpy", checker_exit_code=0))
    s2 = TheoryState(statement="for all H", scope="general")
    apply(s2, TheoryEvidence("derivation", "e3", holds=False))
    assert s2.status == ProofStatus.gap_found
    with pytest.raises(ProofStatusError):
        apply(s2, TheoryEvidence("counterexample", "e4", assumptions_satisfied=None))
    apply(s2, TheoryEvidence("counterexample", "e5", assumptions_satisfied=True))
    assert s2.status == ProofStatus.disproved


# T12 ------------------------------------------------------------------------------------------
EXPECTED = {"scenario": "A", "horizon": 2, "p": "1/2"}


def _program(tmp_path: Path, name: str, body: str) -> Path:
    d = tmp_path / name
    d.mkdir()
    p = d / "program.py"
    p.write_text(body, encoding="utf-8")
    return p


def test_t12_evaluator_rejects_bad_artifacts(tmp_path):
    good = _program(tmp_path, "good", "import json\njson.dump({'scenario':'A','horizon':2,'p':'1/2','policy':"
                    "{'':0,'0:0':1,'0:1':0}}, open('policy.json','w'))\n")
    r = evaluate_program(good, tmp_path / "r_good", EXPECTED, timeout=30)
    assert r.correct and r.metrics["combined_score"] == 1.5 and r.metrics["exact_value"] == "3/2"
    selfrep = _program(tmp_path, "self", "import json\njson.dump({'scenario':'A','horizon':2,'p':'1/2','policy':{'':0,'0:0':1,'0:1':0},"
                       "'value': 99}, open('policy.json','w'))\n")
    r2 = evaluate_program(selfrep, tmp_path / "r_self", EXPECTED, timeout=30)
    assert not r2.correct and "own score" in r2.error and r2.metrics["combined_score"] == -1e9
    missing = _program(tmp_path, "missing", "print('nothing')\n")
    assert "missing artifact" in evaluate_program(missing, tmp_path / "r_m", EXPECTED, timeout=30).error
    nan = _program(tmp_path, "nan", "import json\njson.dump({'scenario':'A','horizon':2,'p':'1/2','policy':{'':float('nan')}}, open('policy.json','w'))\n")
    assert not evaluate_program(nan, tmp_path / "r_n", EXPECTED, timeout=30).correct
    slow = _program(tmp_path, "slow", "import time\ntime.sleep(30)\n")
    r5 = evaluate_program(slow, tmp_path / "r_s", EXPECTED, timeout=1)
    assert not r5.correct and "timed out" in r5.error and r5.wall_seconds < 10
    assert json.loads((tmp_path / "r_s" / "correct.json").read_text())["correct"] is False


# T17 ------------------------------------------------------------------------------------------
def test_t17_deadlines_and_backend_budget_capabilities(store, tmp_path):
    from personal_research_agent.backends.ai_scientist_v3 import AIScientistV3Backend
    from personal_research_agent.backends.base import BackendError, CapabilityReport
    from personal_research_agent.config import BackendConfig

    b = Budget(store, dict(LIMITS, action_wall_seconds=600), time.time() + 5)
    assert b.action_deadline_seconds(cleanup_margin=1) <= 4.01          # min(action cap, remaining run time)
    backend = AIScientistV3Backend(BackendConfig(kind="ai_scientist_v3", require_strict_budget=["usd"]), tmp_path)
    report = CapabilityReport("ai_scientist_v3", True, {}, {"usd": "best_effort (recorded, not capped)", "wall_seconds": "strict"})
    with pytest.raises(BackendError) as exc:
        backend.check_budget_capability(report)
    assert exc.value.code == "UNSUPPORTED_BUDGET_CAPABILITY"
    ok = AIScientistV3Backend(BackendConfig(kind="ai_scientist_v3", require_strict_budget=["wall_seconds"]), tmp_path)
    ok.check_budget_capability(report)
    # backend-reported cost enters the same ledger as an extra settled row
    res = Budget(store, dict(LIMITS, api_usd=5), time.time() + 60).reserve({"actions": 1}, "backend_act")
    bb = Budget(store, dict(LIMITS, api_usd=5), time.time() + 60)
    bb.settle(res, {"actions": 1, "usd": 1.25}, cost_type="actual")
    assert bb.used("usd") == 1.25
