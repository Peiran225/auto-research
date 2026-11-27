"""Report generation (plan §10). Deterministic templates; every number in the research note is
read from an artifact file at write time, never typed in. ``pra report`` calls only this module
and makes no model, search or backend calls (T16)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..models import (
    Assessment, CandidateRevision, Claim, Concept, Evidence, EvidenceLink, ManuscriptStatus, PaperRecord,
    ProblemSpec, QueryResult, RankingSnapshot, ResearchAction, ResearchSpec, Unknown, sha256_text,
)
from .audit import writing_context

if TYPE_CHECKING:  # pragma: no cover
    from ..controller import Controller


def _rel(ctrl, p: Path) -> str:
    return str(p.relative_to(ctrl.run_dir))


def _artifact_json(ctrl, name: str) -> tuple[Path | None, dict | None]:
    hits = sorted((ctrl.run_dir / "artifacts").rglob(name)) if (ctrl.run_dir / "artifacts").exists() else []
    if not hits:
        return None, None
    return hits[0], json.loads(hits[0].read_text(encoding="utf-8"))


# ------------------------------------------------------------------ research note (computation only)
def research_note(ctrl) -> str | None:
    ctx = writing_context(ctrl.store, ctrl.run_dir)
    mdp_path, mdp = _artifact_json(ctrl, "mdp_values.json")
    nva_path, nva = _artifact_json(ctrl, "nested_vs_alternating.json")
    if not ctx["claims"] and mdp is None and nva is None:
        return None
    L: list[str] = [f"# Research note — {ctrl.task.task_id}", "",
                    "Scope: this note uses only computations executed by this run and their audited claims. "
                    "Literature, novelty and decision material from fixtures are excluded by construction.", ""]
    if mdp is not None:
        v = mdp["values"]
        L += [
            "## Two-step MDP: fixed vs. per-step parameter uncertainty (validation example)", "",
            "**Status:** problem-clarification / falsification demonstration. It is a validation example with known "
            "values, not a novel contribution, and it does not show that all forms of MDP uncertainty are non-equivalent.", "",
            "**Setting.** Horizon 2, actions a_t ∈ {0,1}, reward r_t = 1[a_t = θ_t] observed immediately, P(θ=1)=1/2. "
            "A: θ drawn once and fixed for the episode. B: θ_t drawn i.i.d. each step. Both scenarios use the same "
            "policy class: deterministic maps from the agent's own past actions and rewards to the next action "
            "(randomised policies cannot exceed the best deterministic one because the value is linear in the "
            "mixture weights). A history-independent (open-loop) class is the control.", "",
            "**Computed values** (exhaustive enumeration of "
            f"{mdp['counts']['history_policies']} history policies and {mdp['counts']['open_loop_policies']} open-loop "
            "policies, exact rational arithmetic):", "",
            "| quantity | value |", "|---|---|",
            f"| V*_A, history policies | {v['A_history_optimal']['exact']} |",
            f"| V*_B, history policies | {v['B_history_optimal']['exact']} |",
            f"| V*_A, open-loop policies | {v['A_open_loop_optimal']['exact']} |",
            f"| V*_B, open-loop policies | {v['B_open_loop_optimal']['exact']} |", "",
            f"Independent cross-checks: belief-state DP for A gives {mdp['cross_checks']['A_belief_dp']}; "
            f"per-step DP for B gives {mdp['cross_checks']['B_per_step_dp']}. Optimal A policies: "
            + "; ".join(f"`{p}`" for p in mdp["argmax"]["A_history"]) + ".", "",
            "**Short derivation.** In A the first reward reveals θ exactly (r_1 = 1 means θ = a_1, r_1 = 0 means "
            "θ = 1 − a_1), so a history policy earns 1/2 at step 1 and 1 at step 2. In B, θ_2 is independent of "
            "(a_1, r_1), so history carries no information about the future and every policy earns 1/2 per step. "
            "Without history, A also earns 1/2 per step. The difference therefore comes from the temporal "
            "dependence of the hidden parameter and the information the history carries about it, not from "
            "restricting B's memory: both scenarios were given the same history access.", "",
            f"Artifacts: `{_rel(ctrl, mdp_path)}` (values) and the per-policy CSV next to it. "
            "Reproduce: `python -m personal_research_agent.research.mdp_demo --out <dir>`.", "",
        ]
    if nva is not None:
        cf = nva["closed_form"]
        L += ["## Toy check: nested solution dependence vs. alternating updates (clarification pilot)", "",
              "**Status:** clarification pilot on a quadratic toy problem; it is not evidence about world models.", "",
              f"With y*(x) = a x / (1+λ) (a={nva['setting']['a']}, λ={nva['setting']['lam']}, c={nva['setting']['c']}), "
              f"nested training converges to x = {cf['x_nested']:.6f}, alternating two-loss training to "
              f"x = {cf['x_alternating']:.6f}; upper-objective gap {nva['upper_objective_gap']:.6f}. Numerical runs "
              f"match the closed forms: {nva['numerical_matches_closed_form']}. So 'multiple losses with alternating "
              "updates' and 'nested solution dependence' are different problems and must be distinguished before "
              f"any world-model claim. Artifact: `{_rel(ctrl, nva_path)}`.", ""]
    if ctx["claims"]:
        L += ["## Audited claims", "", "| claim | scope | status | proof status | evidence |", "|---|---|---|---|---|"]
        for c in ctx["claims"]:
            L.append(f"| {c.statement} | {c.scope} | {c.status} | {c.proof_status.value if c.proof_status else '-'} | "
                     f"{', '.join(c.evidence_link_ids)} |")
        L += ["", "Finite-instance support never upgrades a general statement to proven; refutations rest on "
                  "verified counterexamples that satisfy the statement's assumptions.", ""]
        for ev in ctx["evidence"]:
            L.append(f"- `{ev.id}` ({ev.kind.value}, protocol {ev.protocol_version}): {ev.observation} "
                     f"[artifact `{ev.artifact_path}`]")
    return "\n".join(L) + "\n"


# ------------------------------------------------------------------ decision report (zh)
def decision_report(ctrl) -> str:
    st = ctrl.store
    d = ctrl.drun
    problems = st.list(ProblemSpec)
    ps = problems[-1] if problems else None
    latest_concepts: dict[str, Concept] = {}
    for c in st.list(Concept):                     # later records (field importance added) replace earlier ones
        latest_concepts[c.canonical_name] = c
    concepts = list(latest_concepts.values())
    unknowns = st.list(Unknown)
    revs = st.list(CandidateRevision)
    snaps = st.list(RankingSnapshot)
    actions = st.list(ResearchAction)
    evidence = st.list(Evidence)
    papers = st.list(PaperRecord)
    fixture = ctrl.origin.value == "fixture"
    L = [f"# 决策报告：{ctrl.task.task_id}", ""]
    if fixture:
        L += ["> **来源说明**：本次为离线验收运行（offline_local）。澄清、文献、领域地图、候选与排序判断来自明确标记的 "
              "fixture（合成测试数据），只用于检验决策流程，不构成文献结论或新颖性判断。实际计算（如 MDP 枚举）在单独的 "
              "computation 命名空间中，可以作为证据。", ""]
    L += ["## 状态", "", "| 字段 | 值 |", "|---|---|",
          f"| operation_status | {d.operation_status.value} |", f"| planning_outcome | {d.planning_outcome.value} |",
          f"| research_outcome | {d.research_outcome.value} |", f"| manuscript_status | {d.manuscript_status.value} |",
          f"| stop_reason | {d.stop_reason.value if d.stop_reason else '-'} |", f"| strategy | {d.strategy} |",
          f"| rounds | {d.round} |", f"| model binding | {d.model_binding_id or '无（fixture 运行不创建真实模型绑定）'} |",
          f"| checkpoint / 恢复入口 | `runs/{d.run_id}/state.sqlite`，`pra resume --run-id {d.run_id}` |", ""]
    if d.error:
        L += [f"**未完成原因**：{d.error}", ""]
    L += ["## 1. idea 被明确成了哪些问题", ""]
    if ps:
        for i in ps.interpretations:
            L.append(f"- **{i.id}**（{i.status}）：{i.description}"
                     + (f" —— 拒绝原因：{i.rejection_reason}" if i.rejection_reason else ""))
        L += ["", f"指标状态：`{ps.metrics_status}`（输入未指定指标时保持 undecided）。", ""]
        if ps.open_items:
            L += ["待澄清项："] + [f"- {o}" for o in ps.open_items] + [""]
    L += ["## 2. 与你的研究的关系、需要学习的内容", "", "| 概念 | 已有能力（来自 profile） | 领域重要性 | 依据 |", "|---|---|---|---|"]
    for c in concepts:
        L.append(f"| {c.canonical_name} | {c.existing_capability.value if c.existing_capability else 'unknown'} | "
                 f"{c.field_importance.value if c.field_importance else 'unknown'} | {c.existing_capability_basis or ''} |")
    learn = [u for u in unknowns if u.question.startswith("learning task")]
    if learn:
        L += ["", "学习任务（熟悉度与科学价值分开记录）："] + [f"- {u.question}（{u.missing_material or ''}）" for u in learn]
    links = [e["payload"] for e in st.events("background_links")]
    if links:
        L += ["", "方法联系（条件与状态）："]
        for c in links[-1].get("correspondences", []):
            L.append(f"- {c['profile_item']} → {c['mechanism_map']}；状态 {c['status']}；条件：{'; '.join(c.get('conditions', []))}")
    L += ["", "## 3. 领域问题、关键文献与最近邻", ""]
    if ps and ps.field_problems:
        for f in ps.field_problems:
            L.append(f"- **{f['id']}** {f['problem']}（{f['status']}；指标：{', '.join(f.get('metrics', [])) or '未定'}）")
    L += ["", "| 文献 | 来源 | 正文状态 | 实际读取范围 |", "|---|---|---|---|"]
    for p in papers:
        L.append(f"| {p.title} | {p.provider}{'（合成）' if p.provider == 'fixture' else ''} | {p.text_status.value} | "
                 f"{', '.join(p.read_scope[:6])}{'…' if len(p.read_scope) > 6 else ''} |")
    L += ["", "未检索到不等于不存在；离线运行没有执行真实检索。", "", "## 4. 候选、部分排序与变化原因", ""]
    for r in revs:
        L.append(f"- **{r.id}**（{r.status}，分支 {r.research_branch.value}）：{r.title}")
        L.append(f"  - 假设：{r.hypothesis}")
        if r.change_reason:
            L.append(f"  - 版本变化：{r.change_reason}（父版本 {r.parent_revision_id}）")
    if snaps:
        last = snaps[-1]
        L += ["", f"最新排序（第 {last.round} 轮）：preferred={last.preferred_candidates}，ties={last.ties}，"
                  f"unresolved={last.unresolved_candidates}", ""]
        for k, v in last.rejected_candidates.items():
            L.append(f"- 淘汰 {k}：{v}")
        L += ["", "| 轮次 | 变化 |", "|---|---|"]
        for s in snaps:
            for ch in s.changed_from_previous:
                L.append(f"| {s.round} | {json.dumps(ch, ensure_ascii=False)[:220]} |")
    asm = st.list(Assessment)
    if asm:
        L += ["", "| 候选版本 | 维度 | 状态 | 判断 | 依据 |", "|---|---|---|---|---|"]
        for a in asm:
            if a.subject_type == "candidate":
                L.append(f"| {a.subject_revision} | {a.dimension} | {a.state.value} | "
                         f"{a.judgment.value if a.judgment else 'null'} | {a.rationale[:120]} |")
    L += ["", "## 5. 已执行行动、成本、负结果与未决问题", "", "| 行动 | 目的 | 结果 | 摘要 |", "|---|---|---|---|"]
    for a in actions:
        L.append(f"| {a.action_type} | {a.purpose.value} | {a.status.value} | {(a.result_summary or a.error or '')[:160]} |")
    b = ctrl.budget.snapshot()
    L += ["", "预算使用（fixture 调用单独计为 fixture，不计作真实模型调用或费用）：", "",
          "| 维度 | 已用 | 上限 |", "|---|---|---|"] + [f"| {k} | {v['used']} | {v['limit']} |" for k, v in b.items()]
    claims = st.list(Claim)
    if claims:
        L += ["", "研究主张（pilot/formal 分开标注）：", ""]
        for c in claims:
            L.append(f"- {c.statement} —— {c.status}，proof_status={c.proof_status.value if c.proof_status else '-'}，"
                     f"stage={c.study_stage.value if c.study_stage else '-'}，audit={c.audit_status}")
    open_u = [u for u in unknowns if u.status == "open"]
    if open_u:
        L += ["", "未决问题："] + [f"- [{u.importance.value}] {u.question}" for u in open_u]
    L += ["", "## 6. 推荐的研究规格或停止原因", ""]
    gates = st.events("gate_reports")
    if d.recommended_candidate_revision_id:
        L.append(f"推荐进入下一阶段：{d.recommended_candidate_revision_id}（“值得继续投入”，不表示新颖性或最终结果已证明）。")
    if gates:
        for g in gates[-1]["payload"]["reports"]:
            L.append(f"- {g['revision_id']} 门槛{'通过' if g['passed'] else '未通过'}：{'; '.join(g['failures']) or '—'}")
    for n in d.notes:
        L.append(f"- {n}")
    if open_u and d.planning_outcome.value != "recommended":
        nxt = sorted(open_u, key=lambda u: {"high": 0, "medium": 1, "low": 2}[u.importance.value])[0]
        L.append(f"- 下一项最有价值的检查：{nxt.question}")
    return "\n".join(L) + "\n"


# ------------------------------------------------------------------ manifests
def write_reports(ctrl) -> dict[str, Any]:
    rep = ctrl.run_dir / "reports"
    rep.mkdir(parents=True, exist_ok=True)
    st = ctrl.store
    out: dict[str, Any] = {}
    (rep / "decision_report.md").write_text(decision_report(ctrl), encoding="utf-8")
    out["decision_report.md"] = "present"
    note = research_note(ctrl)
    if note:
        (rep / "research_note.md").write_text(note, encoding="utf-8")
        out["research_note.md"] = "present"
    else:
        out["research_note.md"] = "not_run: no executed computation or audited claim"
    specs = [s.model_dump(mode="json") for s in st.list(ResearchSpec)]
    if specs:
        (rep / "research_spec.json").write_text(json.dumps(specs, indent=2, ensure_ascii=False), encoding="utf-8")
        out["research_spec.json"] = "present"
    else:
        out["research_spec.json"] = "not_run: no ResearchSpec was frozen"
    links = {l.id: l for l in st.list(EvidenceLink)}
    cmap = []
    for c in st.list(Claim):
        cmap.append({"claim_id": c.id, "statement": c.statement, "scope": c.scope, "status": c.status,
                     "proof_status": c.proof_status.value if c.proof_status else None,
                     "study_stage": c.study_stage.value if c.study_stage else None,
                     "candidate_revision_id": c.candidate_revision_id,
                     "protocol": f"{c.protocol_id}@{c.protocol_version}", "audit_status": c.audit_status,
                     "audit_findings": c.audit_findings, "usable_in_manuscript": c.usable_in_manuscript,
                     "links": [links[l].model_dump(mode="json") for l in c.evidence_link_ids if l in links]})
    (rep / "claim_evidence_map.json").write_text(json.dumps(cmap, indent=2, ensure_ascii=False), encoding="utf-8")
    out["claim_evidence_map.json"] = "present"
    audit_lines = ["# Audit report", ""]
    for c in st.list(Claim):
        audit_lines.append(f"- `{c.id}` {c.audit_status}: {'; '.join(c.audit_findings) or 'no findings'}")
    fixture_ev = [e.id for e in st.list(Evidence) if e.namespace == "fixture"]
    audit_lines += ["", f"Fixture evidence records (excluded from research note and manuscript context): {len(fixture_ev)}",
                    f"Query results: {len(st.list(QueryResult))} (origins: "
                    f"{sorted({q.execution_origin.value for q in st.list(QueryResult)})})"]
    (rep / "audit_report.md").write_text("\n".join(audit_lines) + "\n", encoding="utf-8")
    out["audit_report.md"] = "present"
    # manuscript: experimental drafts come from AI-Scientist-v3 only
    v3 = [e["payload"] for e in st.events("v3_manuscript")]
    if v3 and v3[-1].get("status") == "draft":
        ctrl.drun.manuscript_status = ManuscriptStatus.draft
        out["manuscript"] = f"present (upstream v3 draft: {v3[-1].get('files')})"
    else:
        ctrl.drun.manuscript_status = ManuscriptStatus.not_generated
        ctrl.drun.manuscript_reason = ("manuscript_missing: " + (v3[-1].get("reason") if v3 else
                                       "no AI-Scientist-v3 paper phase ran in this run (local backend); "
                                       "only a deterministic research note was written"))
        out["manuscript"] = f"missing: {ctrl.drun.manuscript_reason}"
    verified_lit = [p for p in st.list(PaperRecord) if p.verification_status.value == "verified"]
    out["references.bib"] = ("not_applicable: no verified live literature records" if not verified_lit else "present")
    if verified_lit:
        bib = []
        for p in verified_lit:
            key = (p.arxiv_id or p.canonical_id).replace(":", "_").replace("/", "_")
            bib.append(f"@misc{{{key},\n  title={{{p.title}}},\n  author={{{' and '.join(p.authors)}}},\n"
                       f"  year={{{p.year or ''}}},\n  note={{{p.url or p.canonical_id}}}\n}}")
        (rep / "references.bib").write_text("\n\n".join(bib) + "\n", encoding="utf-8")
    out["manuscript.tex"] = "not_generated: no upstream manuscript source"
    out["pdf"] = "not_generated: no manuscript source and no LaTeX toolchain in this environment"
    artifacts = {}
    for f in sorted((ctrl.run_dir / "artifacts").rglob("*")) if (ctrl.run_dir / "artifacts").exists() else []:
        if f.is_file():
            artifacts[_rel(ctrl, f)] = sha256_text(f.read_text(encoding="utf-8", errors="replace"))
    manifest = {"run_id": ctrl.drun.run_id, "execution_origin": ctrl.origin.value,
                "operation_status": ctrl.drun.operation_status.value, "planning_outcome": ctrl.drun.planning_outcome.value,
                "research_outcome": ctrl.drun.research_outcome.value, "manuscript_status": ctrl.drun.manuscript_status.value,
                "expected_products": out, "artifacts_sha256": artifacts,
                "evidence": [{"id": e.id, "kind": e.kind.value, "namespace": e.namespace, "verification": e.verification_status.value,
                              "artifact": e.artifact_path, "content_hash": e.content_hash} for e in st.list(Evidence)]}
    (rep / "evidence_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    ctrl.store.update(ctrl.drun)
    return out
