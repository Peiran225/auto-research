"""T11, T13–T16, T18–T22: resume, backend contracts, writing context, report/verify, routing,
model binding, query templates and the offline paths."""
import json
import os
import socket
from fractions import Fraction
from pathlib import Path

import pytest

from personal_research_agent.agents.binding import build_binding
from personal_research_agent.agents.providers import FixtureProvider, LLMRequest, OpenAIResponsesProvider, ProviderError
from personal_research_agent.agents.query import PROMPTS_DIR, load_template, persona_violations
from personal_research_agent.backends.ai_scientist_v3 import AIScientistV3Backend, collect_run_dir, parse_pipeline_status
from personal_research_agent.backends.base import BackendError
from personal_research_agent.backends.local import LocalBackend
from personal_research_agent.config import BackendConfig, ConfigError, LLMConfig, load_config
from personal_research_agent.models import (
    Answer, ExecutionOrigin, ManuscriptStatus, ResearchBranch, ResearchSpec, StudyStage,
)
from personal_research_agent.netguard import NetworkForbidden, forbid_network
from personal_research_agent.research import mdp_demo

from .conftest import ROOT, run_cli

TASK_MDP = str(ROOT / "examples/mdp_uncertainty.yaml")
TASK_WM = str(ROOT / "examples/world_model.yaml")
PROFILE = str(ROOT / "profiles/peiran.yaml")
OFFLINE = str(ROOT / "configs/offline.yaml")


def _run(run_id, task=TASK_MDP, *extra):
    return run_cli("run", "--task", task, "--profile", PROFILE, "--config", OFFLINE, "--run-id", run_id, *extra)


def _json(out: str) -> dict:
    return json.JSONDecoder().raw_decode(out[out.index("{"):])[0]


def _ledger(runs_root, run_id):
    import sqlite3
    c = sqlite3.connect(runs_root / run_id / "state.sqlite")
    rows = c.execute("SELECT dimension, attempt, state, actual FROM budget ORDER BY id").fetchall()
    c.close()
    return rows


# T22 + MDP oracle --------------------------------------------------------------------------------
def test_t22_mdp_values_are_computed_not_hard_coded():
    s = mdp_demo.solve_instance(2, Fraction(1, 2))
    assert (s["A"]["history_optimal"], s["B"]["history_optimal"], s["A"]["open_loop_optimal"]) == (Fraction(3, 2), 1, 1)
    # a different prior gives different values from the same code path (no constants in the output)
    s3 = mdp_demo.solve_instance(2, Fraction(1, 3))
    assert (s3["A"]["history_optimal"], s3["B"]["history_optimal"], s3["A"]["open_loop_optimal"]) == (Fraction(5, 3), Fraction(4, 3), Fraction(4, 3))
    assert mdp_demo.belief_dp_value_A(3, Fraction(1, 2)) == mdp_demo.solve_instance(3, Fraction(1, 2))["A"]["history_optimal"]


def test_t22_offline_runs_without_network_credentials_or_model_probe(runs_root, monkeypatch):
    from personal_research_agent import controller as ctl

    monkeypatch.setattr(ctl.Controller, "check_mapping", staticmethod(lambda *a: (_ for _ in ()).throw(AssertionError("probe"))))
    import openai
    monkeypatch.setattr(openai, "OpenAI", lambda *a, **k: (_ for _ in ()).throw(AssertionError("model client built offline")))
    code, out = _run("t22_mdp")
    assert code == 0, out
    summary = _json(out)
    assert summary["operation_status"] == "completed" and summary["research_outcome"] == "refuted"
    note = (runs_root / "t22_mdp" / "reports" / "research_note.md").read_text()
    assert "| V*_A, history policies | 3/2 |" in note and "not a novel contribution" in note
    code, out = _run("t22_wm", TASK_WM)
    assert code == 0, out
    wm = _json(out)
    assert wm["research_outcome"] == "not_run" and wm["manuscript_status"] == "not_generated"
    with forbid_network():
        with pytest.raises(NetworkForbidden):
            socket.create_connection(("example.com", 443), timeout=1)


# T11 --------------------------------------------------------------------------------------------
def test_t11_resume_does_not_repeat_or_double_charge_and_detects_task_drift(runs_root, tmp_path):
    code, out = _run("t11", TASK_MDP, "--until", "assess")
    assert code == 0 and '"operation_status": "paused"' in out
    before = _ledger(runs_root, "t11")
    import sqlite3
    c = sqlite3.connect(runs_root / "t11" / "state.sqlite")
    n_actions_before = c.execute("SELECT COUNT(*) FROM records WHERE kind='ResearchAction'").fetchone()[0]
    c.close()
    code, out = run_cli("resume", "--run-id", "t11")
    assert code == 0, out
    after = _ledger(runs_root, "t11")
    assert after[: len(before)] == before                               # history untouched, nothing re-charged
    c = sqlite3.connect(runs_root / "t11" / "state.sqlite")
    fps = c.execute("SELECT COUNT(*), COUNT(DISTINCT fingerprint) FROM action_fingerprints").fetchone()
    pilots = c.execute("SELECT COUNT(*) FROM records WHERE kind='ResearchAction' AND json LIKE '%\"action_type\":\"cpu_pilot\"%'").fetchone()[0]
    c.close()
    assert fps[0] == fps[1] and pilots == 1 and n_actions_before > 0
    code, out = run_cli("resume", "--run-id", "t11")
    assert code == 0 and "already completed" in out
    assert _ledger(runs_root, "t11") == after
    # drift: the task file changed after the run started
    task_copy = tmp_path / "task.yaml"
    task_copy.write_text(Path(TASK_MDP).read_text())
    code, _ = run_cli("run", "--task", str(task_copy), "--profile", PROFILE, "--config", OFFLINE, "--run-id", "t11d", "--until", "clarify")
    task_copy.write_text(Path(TASK_MDP).read_text().replace("等价", "相同"))
    code, out = run_cli("resume", "--run-id", "t11d")
    assert code == 2 and "task drift" in out


def test_t11_interrupted_action_is_reconciled_not_rerun_blindly(runs_root):
    from personal_research_agent.controller import Controller
    from personal_research_agent.models import ActionStatus, ResearchAction

    _run("t11b", TASK_MDP, "--until", "clarify")
    ctrl = Controller.open("t11b", runs_root)
    act = ctrl.store.list(ResearchAction)[0]
    res = ctrl.budget.reserve({"actions": 1}, act.id, act.attempt)
    act.status = ActionStatus.running
    ctrl.store.update(act)
    ctrl._reconcile()
    a2 = ctrl.store.require(act.id, ResearchAction)
    assert a2.status == ActionStatus.failed and "interrupted" in a2.error
    assert not ctrl.budget.open_reservations()                         # settled once at the reserved amount
    assert res.ids


# T13 / T14 / T21 ---------------------------------------------------------------------------------
def _write_events(d: Path, events: list[dict]):
    d.mkdir(parents=True, exist_ok=True)
    (d / "pipeline_events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))


def test_t13_backend_outcomes_manifest_mismatch_and_optional_phase_failure(tmp_path):
    rd = tmp_path / "run"
    _write_events(rd, [{"event": "phase_end", "phase": "investigation"},
                       {"event": "phase_end", "phase": "ablations", "status": "degraded"},
                       {"event": "pipeline_end", "status": "completed", "return_code": 0}])
    (rd / "task").mkdir()
    (rd / "task" / "task.md").write_text("changed after launch")
    (rd / "paper").mkdir()
    (rd / "paper" / "paper.pdf").write_bytes(b"%PDF-1.4")
    st = parse_pipeline_status(rd)
    assert st.normalized == "degraded" and st.raw_status == "completed"
    bundle = collect_run_dir(rd, expected_snapshot="deadbeef")
    assert bundle.protocol_hash_matches is False and bundle.notes
    assert "a correct, finite investigation score" in bundle.missing          # missing stays missing, not 0
    assert bundle.manuscript["status"] == "draft" and bundle.outcome == "inconclusive"   # a PDF is not support
    _write_events(tmp_path / "nw", [{"event": "pipeline_end", "status": "completed", "outcome": "completed_no_winner"}])
    assert parse_pipeline_status(tmp_path / "nw").normalized == "no_winner"
    _write_events(tmp_path / "int", [{"event": "phase_end", "phase": "investigation"}])
    assert parse_pipeline_status(tmp_path / "int").normalized == "interrupted"
    fake = tmp_path / "checkout"
    fake.mkdir()
    (fake / "pyproject.toml").write_text("")
    report = AIScientistV3Backend(BackendConfig(kind="ai_scientist_v3", checkout=str(fake)), tmp_path).probe()
    assert any("not the pinned" in m for m in report.missing) and report.available is False


def test_t14_hand_written_tasks_never_use_contract_phases(tmp_path):
    with pytest.raises(Exception):
        BackendConfig(kind="ai_scientist_v3", phases=["investigation", "final_evaluation"])
    b = AIScientistV3Backend(BackendConfig(kind="ai_scientist_v3", agent={"name": "codex"}), tmp_path)
    with pytest.raises(BackendError):
        b._argv(tmp_path, "r", tmp_path, ["investigation", "task_drafting"], {})
    argv = b._argv(tmp_path, "r", tmp_path, ["investigation", "ablations", "posthoc", "paper"], {})
    assert 'execution.phases="investigation,ablations,posthoc,paper"' in argv           # one argv element
    task = tmp_path / "task"
    task.mkdir()
    (task / "task_contract.json").write_text("{}")
    from personal_research_agent.backends.base import TaskBundle
    rep = b.validate_task(TaskBundle(task, "s", "h", "x"))
    assert any("task_contract.json present" in e for e in rep.errors)


def test_t21_v3_keeps_its_own_agent_config_and_formal_empirical_goes_to_v3(tmp_path):
    with pytest.raises(Exception):
        BackendConfig(kind="ai_scientist_v3", inherit_frontend_llm=True)
    b = AIScientistV3Backend(BackendConfig(kind="ai_scientist_v3", agent={"name": "codex", "model": "gpt-5.6-sol"}), tmp_path)
    argv = " ".join(b._argv(tmp_path, "r", tmp_path, ["investigation"], {}))
    assert "agent.name=codex" in argv and "agent.model=gpt-5.6-sol" in argv and "gpt-6-astra" not in argv and "reasoning" not in argv
    spec = ResearchSpec(id="s", origin=ExecutionOrigin.fixture, source="t", study_stage=StudyStage.formal, candidate_revision_id="r",
                        protocol_id="p", protocol_version=1, research_branch=ResearchBranch.empirical, hypothesis="h", falsification="f")
    with pytest.raises(BackendError) as exc:
        LocalBackend().run_pilot(spec, tmp_path / "o", 10)
    assert exc.value.code == "PURPOSE_BOUNDARY"


# T15 / T16 -------------------------------------------------------------------------------------
def test_t15_fixture_and_unverified_material_cannot_enter_writing_context(runs_root):
    from personal_research_agent.controller import Controller
    from personal_research_agent.models import Claim, Evidence
    from personal_research_agent.reporting.audit import check_claim, writing_context

    code, out = _run("t15")
    assert code == 0
    ctrl = Controller.open("t15", runs_root)
    ctx = writing_context(ctrl.store, ctrl.run_dir)
    assert ctx["claims"] and all(e.namespace == "computation" for e in ctx["evidence"])
    fixture_ev = [e for e in ctrl.store.list(Evidence) if e.namespace == "fixture"]
    assert fixture_ev and not set(e.id for e in fixture_ev) & set(e.id for e in ctx["evidence"])
    claim = ctx["claims"][0]
    links = {l.id: l for l in ctrl.store.list(__import__("personal_research_agent.models", fromlist=["EvidenceLink"]).EvidenceLink)}
    tampered = {e.id: (e.model_copy(update={"namespace": "fixture"}) if e.id == links[claim.evidence_link_ids[0]].evidence_id else e)
                for e in ctrl.store.list(Evidence)}
    assert any("fixture evidence" in f for f in check_claim(claim, links, tampered, ctrl.run_dir))
    general = claim.model_copy(update={"status": "supported", "scope": "general"})
    assert any("over-broad" in f for f in check_claim(general, links, {e.id: e for e in ctrl.store.list(Evidence)}, ctrl.run_dir))


def test_t16_report_and_verify_make_no_research_calls(runs_root, monkeypatch):
    from personal_research_agent.agents import providers
    from personal_research_agent.backends import local
    from personal_research_agent.literature import service

    _run("t16")
    before = _ledger(runs_root, "t16")
    boom = lambda *a, **k: (_ for _ in ()).throw(AssertionError("research call during report/verify"))
    monkeypatch.setattr(providers.FixtureProvider, "complete", boom)
    monkeypatch.setattr(service.LiteratureService, "search", boom)
    monkeypatch.setattr(local.LocalBackend, "run_pilot", boom)
    code, out = run_cli("report", "--run-id", "t16")
    assert code == 0, out
    code, out = run_cli("verify", "--run-id", "t16")
    assert code == 0 and '"ok": true' in out
    assert _ledger(runs_root, "t16") == before


# T18 --------------------------------------------------------------------------------------------
def test_t18_branch_routing_and_version_references(runs_root):
    with pytest.raises(ValueError):
        ResearchSpec(id="s", origin=ExecutionOrigin.fixture, source="t", study_stage=StudyStage.pilot, candidate_revision_id="r",
                     protocol_id="p", protocol_version=1, research_branch=ResearchBranch.auto, hypothesis="h", falsification="f")
    from personal_research_agent.controller import Controller
    from personal_research_agent.models import Claim, EvidenceLink, ResearchSpec as RS

    _run("t18")
    ctrl = Controller.open("t18", runs_root)
    specs = {(s.protocol_id, s.protocol_version): s for s in ctrl.store.list(RS)}
    assert len(specs) == len(ctrl.store.list(RS))                       # protocol versions are unique
    for c in ctrl.store.list(Claim):
        spec = specs[(c.protocol_id, c.protocol_version)]
        assert spec.candidate_revision_id == c.candidate_revision_id
        for lid in c.evidence_link_ids:
            assert ctrl.store.require(lid, EvidenceLink).candidate_revision_id == c.candidate_revision_id


# T19 --------------------------------------------------------------------------------------------
def _live_llm(**over):
    base = dict(provider="openai", api="responses", requested_product="GPT-6 Pro", model="gpt-6-astra",
                reasoning={"mode": "pro"}, mapping_verified_on="2026-11-24")
    base.update(over)
    return LLMConfig(**base)


class _FakeResp:
    def __init__(self, model, mode):
        self.model, self.id = model, "resp_1"
        self.reasoning = {"mode": mode}
        self.output_text = json.dumps({"answers": [], "payload": {}})
        self.usage = type("U", (), {"input_tokens": 10, "output_tokens": 5})()


class _FakeClient:
    def __init__(self, model="gpt-6-astra", mode="pro"):
        self.sent = []
        outer = self

        class R:
            def create(self, **kw):
                outer.sent.append(kw)
                return _FakeResp(model, mode)
        self.responses = R()


def test_t19_single_gpt6_pro_binding_without_effort_or_fallback(store, budget):
    for bad in (dict(model="gpt-6-pro"), dict(reasoning={"mode": "pro", "effort": "max"}), dict(reasoning={"mode": "standard"}),
                dict(fallback_models=["gpt-5"]), dict(allow_task_overrides=True)):
        with pytest.raises(Exception):
            _live_llm(**bad)
    binding = build_binding(_live_llm(), "r1", {"status": "test"})
    assert (binding.resolved_model, binding.reasoning_mode, binding.requested_effort) == ("gpt-6-astra", "pro", None)
    client = _FakeClient()
    prov = OpenAIResponsesProvider(binding, client=client)
    from personal_research_agent.agents.gateway import LLMGateway
    gw = LLMGateway(prov, store, budget, binding, max_retries=0)
    req = LLMRequest("clarify_problem", "d", {}, {}, "s", 100)
    gw.call(req, "a1")
    gw.call(LLMRequest("json_repair", "d", {}, {}, "s", 100), "a1")      # repair uses the same path and binding
    assert all(k["model"] == "gpt-6-astra" and k["reasoning"] == {"mode": "pro"} for k in client.sent)
    assert all("effort" not in k["reasoning"] for k in client.sent)
    with pytest.raises(ProviderError) as exc:
        OpenAIResponsesProvider(binding, client=_FakeClient(model="gpt-5.6-sol")).complete(req, 10)
    assert exc.value.code == "BINDING_MISMATCH"
    with pytest.raises(ProviderError) as exc:
        OpenAIResponsesProvider(binding, client=_FakeClient(mode="standard")).complete(req, 10)
    assert exc.value.code == "BINDING_MISMATCH"
    os.environ.pop("OPENAI_API_KEY", None)
    with pytest.raises(ProviderError) as exc:
        OpenAIResponsesProvider(binding).complete(req, 10)
    assert exc.value.code == "MISSING_CREDENTIALS"
    with pytest.raises(ValueError):
        LLMGateway(FixtureProvider(Path("."), "x"), store, budget, binding, max_retries=0)   # no fixture behind a real binding


def test_t19_resume_reuses_the_stored_binding(runs_root, tmp_path, monkeypatch):
    from personal_research_agent import controller as ctl
    from personal_research_agent.models import ModelBinding

    cfg = tmp_path / "live.yaml"
    text = (ROOT / "configs/live.example.yaml").read_text().replace("checkout: /path/to/AI-Scientist-v3", "checkout: /nonexistent")
    cfg.write_text(text)
    monkeypatch.setattr(ctl.Controller, "check_mapping", staticmethod(lambda c: {"status": "test, no network"}))
    c = ctl.Controller.create(Path(TASK_MDP), Path(PROFILE), cfg, "t19", None, runs_root)
    h = c.binding.binding_hash
    monkeypatch.setattr(ctl, "build_binding", lambda *a, **k: (_ for _ in ()).throw(AssertionError("re-resolved")))
    c2 = ctl.Controller.open("t19", runs_root)
    assert isinstance(c2.binding, ModelBinding) and c2.binding.binding_hash == h
    d = c2.run()                                     # no credentials: blocked, no silent fallback
    assert d.operation_status.value == "blocked_dependency" and "no fallback" in (d.error or "")


# T20 --------------------------------------------------------------------------------------------
def test_t20_templates_are_question_based_without_personas():
    for p in PROMPTS_DIR.glob("*.txt"):
        text = p.read_text(encoding="utf-8")
        assert not persona_violations(text), (p.name, persona_violations(text))
        assert text.startswith("template_version:")
    for name, n in [("clarify_problem", 7), ("read_paper", 8), ("link_background", 8), ("check_candidate", 8), ("update_decision", 9)]:
        assert len(load_template(name).questions) == n


def test_t20_answers_need_sources_premises_and_tests():
    with pytest.raises(ValueError):
        Answer(question_id="q1", statement="paper shows X", epistemic_status="fact", basis_type="source_report")
    with pytest.raises(ValueError):
        Answer(question_id="q1", statement="X", epistemic_status="fact", basis_type="source_report",
               source_refs=[{"source_id": "p", "read_scope": "full_text"}])           # no locator
    with pytest.raises(ValueError):
        Answer(question_id="q1", statement="likely X", epistemic_status="inference")
    with pytest.raises(ValueError):
        Answer(question_id="q1", statement="X may hold", epistemic_status="hypothesis")
    with pytest.raises(ValueError):
        Answer(question_id="q1", statement="guess", epistemic_status="unknown", missing_information="m")
    with pytest.raises(ValueError):
        Answer(question_id="q1", statement="novel", epistemic_status="inference", premise_ids=["q2"], basis_type="input_given")


def test_t20_runner_rejects_unresolvable_or_overclaimed_sources(runs_root):
    from personal_research_agent.agents.query import QueryInput
    from personal_research_agent.controller import Controller
    from personal_research_agent.models import PaperRecord

    _run("t20", TASK_MDP, "--until", "map_field")
    ctrl = Controller.open("t20", runs_root)
    paper = ctrl.store.list(PaperRecord)[0]
    tpl = load_template("map_field")
    qi = QueryInput("map_field", {}, input_refs=[paper.id])
    good = {"question_id": "q1", "statement": "s", "epistemic_status": "fact", "basis_type": "source_report",
            "source_refs": [{"source_id": paper.id, "locator": "§2", "read_scope": "partial_text"}]}
    answers = [good] + [{"question_id": f"q{i}", "statement": None, "epistemic_status": "unknown", "missing_information": "m"} for i in (2, 3, 4)]
    payload = {"field_problems": []}
    assert ctrl.runner._validate_raw({"answers": answers, "payload": payload}, None, tpl, qi) == []
    bad_loc = dict(good, source_refs=[{"source_id": paper.id, "locator": "Theorem 9", "read_scope": "partial_text"}])
    over = dict(good, source_refs=[{"source_id": paper.id, "locator": "§2", "read_scope": "full_text"}])
    foreign = dict(good, source_refs=[{"source_id": "paper_not_given", "locator": "§2", "read_scope": "partial_text"}])
    for bad, needle in [(bad_loc, "locator"), (over, "claims read_scope"), (foreign, "not part of the input")]:
        errs = ctrl.runner._validate_raw({"answers": [bad] + answers[1:], "payload": payload}, None, tpl, qi)
        assert any(needle in e for e in errs), errs
    missing_q = ctrl.runner._validate_raw({"answers": answers[:2], "payload": payload}, None, tpl, qi)
    assert any("not answered" in e for e in missing_q)


def test_offline_config_refuses_network_providers(tmp_path):
    text = (ROOT / "configs/offline.yaml").read_text().replace("provider: fixture\n  model: null", "provider: openai\n  model: gpt-6-astra", 1)
    p = tmp_path / "bad.yaml"
    p.write_text(text)
    with pytest.raises(ConfigError):
        load_config(p)


def test_strategy_comparison_uses_same_limits(runs_root):
    for s in ("one_shot", "evidence_loop", "personalized_loop"):
        code, out = _run(f"cmp_{s}", TASK_MDP, "--strategy", s)
        assert code == 0, out
    code, out = run_cli("compare", "cmp_one_shot", "cmp_evidence_loop", "cmp_personalized_loop")
    data = _json(out)
    assert data["same_limits"] is True
    rows = {r["strategy"]: r for r in data["runs"]}
    assert rows["one_shot"]["rounds"] == 0 and rows["evidence_loop"]["rounds"] > 0


def test_t11_completed_pilot_is_recovered_not_recomputed(runs_root, monkeypatch):
    """A pilot that finished computing before the process died is recovered from its marker on the
    next attempt: no second computation and no second pilot charge."""
    from personal_research_agent.backends import local
    from personal_research_agent.controller import Controller
    from personal_research_agent.models import ActionPurpose

    _run("t11r", TASK_MDP, "--until", "assess")
    ctrl = Controller.open("t11r", runs_root)
    rev_ = ctrl.revision_for_key("CAND-A")
    c = {"revision_ids": [rev_.id], "inputs": {"pilot_id": "mdp_exact_enumeration"}}
    calls = []
    real = local.LocalBackend.run_pilot

    def crash_after_compute(self, spec, out_dir, deadline):
        res = real(self, spec, out_dir, deadline)
        calls.append(1)
        return res

    monkeypatch.setattr(local.LocalBackend, "run_pilot", crash_after_compute)
    monkeypatch.setattr(Controller, "_record_pilot", lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        ctrl.execute_action("cpu_pilot", ActionPurpose.preliminary_check, c["inputs"], lambda a: ctrl._run_pilot(a, c),
                            None, [rev_.id])
    used = ctrl.budget.used("pilots")
    monkeypatch.undo()
    ctrl2 = Controller.open("t11r", runs_root)
    ctrl2._reconcile()
    act = ctrl2.execute_action("cpu_pilot", ActionPurpose.preliminary_check, c["inputs"], lambda a: ctrl2._run_pilot(a, c),
                               None, [rev_.id])
    assert act.status.value == "succeeded" and act.attempt == 2
    assert calls == [1] and ctrl2.budget.used("pilots") == used == 1
    assert ctrl2.store.events("pilot_result_recovered")


def test_t19_model_override_must_be_explicit_and_is_recorded():
    with pytest.raises(Exception):
        _live_llm(model="gpt-6.2-astra")                                  # no silent switch
    with pytest.raises(Exception):
        _live_llm(model="gpt-6.2-astra", user_model_override=True)       # reason required
    with pytest.raises(Exception):
        _live_llm(model="gpt-6.2-astra", user_model_override=True, override_reason="x", reasoning={"mode": "standard"})
    with pytest.raises(Exception):
        _live_llm(user_model_override=True, override_reason="not needed for the official id")
    cfg = _live_llm(model="gpt-6.2-astra", user_model_override=True, override_reason="user chose GPT-6.2 Astra")
    b = build_binding(cfg, "r2", {})
    assert b.resolved_model == "gpt-6.2-astra" and b.reasoning_mode == "pro"
    assert b.mapping_check["model_choice"].startswith("USER OVERRIDE") and "override" in b.source
    official = build_binding(_live_llm(), "r3", {})
    assert official.mapping_check["model_choice"].startswith("official")
    assert b.binding_hash != official.binding_hash


def test_task_input_reference_is_citable(runs_root):
    """Regression (first live run): answers citing the task material as `task:<id>` were rejected."""
    from personal_research_agent.agents.query import QueryInput
    from personal_research_agent.controller import Controller

    _run("t_taskref", TASK_WM, "--until", "clarify")
    ctrl = Controller.open("t_taskref", runs_root)
    tpl = load_template("map_field")
    qi = QueryInput("map_field", {}, input_refs=["task:hierarchical_world_model"])
    ans = [{"question_id": f"q{i}", "statement": "s", "epistemic_status": "fact", "basis_type": "input_given",
            "source_refs": [{"source_id": "task:hierarchical_world_model"}]} for i in range(1, 5)]
    assert ctrl.runner._validate_raw({"answers": ans, "payload": {"field_problems": []}}, None, tpl, qi) == []
    other = [dict(a, source_refs=[{"source_id": "task:some_other_task"}]) for a in ans]
    errs = ctrl.runner._validate_raw({"answers": other, "payload": {"field_problems": []}}, None, tpl, qi)
    assert any("not part of the input" in e for e in errs)


def test_background_polling_reports_progress_and_times_out(store, budget):
    """Pro-mode calls run in background mode: progress is reported while queued/in_progress and the
    request is cancelled at its timeout."""
    binding = build_binding(_live_llm(), "rbg", {})

    class Slow:
        def __init__(self):
            self.cancelled = []
            self.retrieved = 0
            outer = self

            class R:
                def create(self, **kw):
                    assert kw["background"] is True and kw["store"] is True
                    return type("Resp", (), {"id": "resp_x", "status": "queued"})()

                def retrieve(self, rid):
                    outer.retrieved += 1
                    return type("Resp", (), {"id": rid, "status": "in_progress"})()

                def cancel(self, rid):
                    outer.cancelled.append(rid)
            self.responses = R()

    client = Slow()
    clock = {"t": 0.0}
    import personal_research_agent.agents.providers as prov_mod
    prov = OpenAIResponsesProvider(binding, client=client, sleep=lambda s: clock.__setitem__("t", clock["t"] + s))
    seen = []
    prov.progress = lambda status, elapsed, rid=None: seen.append(status)
    import time as _t
    real = _t.time
    start = real()
    _t.time = lambda: start + clock["t"]
    try:
        with pytest.raises(ProviderError) as exc:
            prov.complete(LLMRequest("clarify_problem", "d", {}, {}, "s", 100), timeout=35)
    finally:
        _t.time = real
    assert exc.value.code == "TIMEOUT" and client.cancelled == ["resp_x"]
    assert seen[0] == "submitted" and "in_progress" in seen


def test_resume_retry_failed_reuses_completed_steps(runs_root):
    from personal_research_agent.controller import Controller
    from personal_research_agent.models import OperationStatus

    _run("t_retry", TASK_MDP, "--until", "map_field")
    ctrl = Controller.open("t_retry", runs_root)
    ctrl.drun.operation_status, ctrl.drun.error = OperationStatus.failed, "simulated provider bug"
    ctrl.store.update(ctrl.drun)
    before = _ledger(runs_root, "t_retry")
    code, out = run_cli("resume", "--run-id", "t_retry")
    assert "nothing to do" in out or _json(out)["operation_status"] == "failed"
    code, out = run_cli("resume", "--run-id", "t_retry", "--retry-failed")
    assert code == 0 and _json(out)["operation_status"] == "completed"
    assert _ledger(runs_root, "t_retry")[: len(before)] == before


def test_raise_limit_only_increases_is_recorded_and_reopens_budget_stops(runs_root, tmp_path):
    cfg = tmp_path / "tight.yaml"
    cfg.write_text((ROOT / "configs/offline.yaml").read_text().replace("max_pilots: 3", "max_pilots: 1"))
    code, out = run_cli("run", "--task", TASK_MDP, "--profile", PROFILE, "--config", str(cfg), "--run-id", "t_raise")
    assert code == 0
    code, out = run_cli("resume", "--run-id", "t_raise", "--raise-limit", "max_pilots=0")
    assert code == 2 and "can only be raised" in out
    code, out = run_cli("resume", "--run-id", "t_raise", "--raise-limit", "max_pilots=3")
    assert code == 0, out
    from personal_research_agent.controller import Controller
    ctrl = Controller.open("t_raise", runs_root)
    assert ctrl.config.limits.max_pilots == 3
    assert ctrl.drun.config_snapshot["limit_amendments"][0]["changes"]["max_pilots"] == {"from": 1, "to": 3.0}
    assert ctrl.store.events("limits_raised")


def test_locator_formats_and_bounded_reading(runs_root):
    """Regression (live run): descriptive locators were rejected without guidance, and whole papers
    were sent to the model."""
    from personal_research_agent.agents.query import split_locator
    from personal_research_agent.controller import Controller

    assert split_locator("p.3") == ["p.3"]
    assert split_locator("pp.3–5") == ["p.3", "p.4", "p.5"]
    assert split_locator("p.2; §1") == ["p.2", "§1"]
    assert split_locator("pp.1–2 摘要及引言；pp.3–4 §3.2") is None          # description, not a unit key
    _run("t_read", TASK_WM, "--until", "clarify")
    ctrl = Controller.open("t_read", runs_root)
    units = {f"p.{i}": ("world model hierarchical planning " if i == 17 else "filler text ") * 400 for i in range(1, 31)}
    picked = ctrl._select_units(units)
    assert sum(len(v) for v in picked.values()) <= ctrl.config.literature.max_chars_per_read + 8000
    assert "p.1" in picked and "p.2" in picked and "p.17" in picked and len(picked) < 30


def test_budget_stop_before_any_candidate_is_not_all_rejected(runs_root, tmp_path):
    cfg = tmp_path / "tiny.yaml"
    cfg.write_text((ROOT / "configs/offline.yaml").read_text().replace("max_input_tokens_total: 200000",
                                                                       "max_input_tokens_total: 9000"))
    code, out = run_cli("run", "--task", TASK_MDP, "--profile", PROFILE, "--config", str(cfg), "--run-id", "t_tiny")
    s = _json(out)
    assert code == 0 and s["planning_outcome"] == "inconclusive" and s["stop_reason"] == "budget_exhausted", s
    code, out = run_cli("resume", "--run-id", "t_tiny", "--reopen-at", "map_field",
                        "--raise-limit", "max_input_tokens_total=200000")
    s2 = _json(out[out.index("}") + 1:][out[out.index("}") + 1:].index("{"):] if out.count("{") > 2 else out)
    from personal_research_agent.controller import Controller
    ctrl = Controller.open("t_tiny", runs_root)
    assert ctrl.drun.operation_status.value == "completed" and ctrl.store.list(
        __import__("personal_research_agent.models", fromlist=["CandidateRevision"]).CandidateRevision)
    assert ctrl.store.events("run_reopened") and ctrl.store.events("limits_raised")
    assert len([e for e in ctrl.store.events("llm_call") if e["payload"]["task_type"] == "clarify_problem"]) == 1   # reused


def test_reservations_scale_with_observed_pro_mode_usage(store, budget):
    """Regression (live run): Pro mode billed ~15x the estimated input tokens, so fixed estimates were
    not upper bounds and the token cap was overrun."""
    from personal_research_agent.agents.gateway import LLMGateway

    binding = build_binding(_live_llm(), "rr", {})
    store.event("llm_call", {"origin": "live", "input_tokens": 18000, "input_estimate": 1200,
                             "output_tokens": 11000, "max_output_tokens": 8000})
    gw = LLMGateway(OpenAIResponsesProvider(binding, client=_FakeClient()), store, budget, binding, max_retries=0)
    rin, rout = gw._observed_ratios()
    assert rin == pytest.approx(15 * 1.25) and rout == pytest.approx(11000 / 8000 * 1.25)
    gw.call(LLMRequest("clarify_problem", "d" * 400, {}, {}, "s", 100), "a1")
    reserved = [e["payload"]["request"] for e in store.events("budget_reserved") if "llm_calls" in e["payload"]["request"]]
    assert reserved[-1]["input_tokens"] >= 200 * 15 and reserved[-1]["output_tokens"] >= 100 * 1.3
