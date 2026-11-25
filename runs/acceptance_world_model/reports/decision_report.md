# 决策报告：hierarchical_world_model

> **来源说明**：本次为离线验收运行（offline_local）。澄清、文献、领域地图、候选与排序判断来自明确标记的 fixture（合成测试数据），只用于检验决策流程，不构成文献结论或新颖性判断。实际计算（如 MDP 枚举）在单独的 computation 命名空间中，可以作为证据。

## 状态

| 字段 | 值 |
|---|---|
| operation_status | completed |
| planning_outcome | inconclusive |
| research_outcome | not_run |
| manuscript_status | not_generated |
| stop_reason | no_available_action |
| strategy | personalized_loop |
| rounds | 2 |
| model binding | 无（fixture 运行不创建真实模型绑定） |
| checkpoint / 恢复入口 | `runs/acceptance_world_model/state.sqlite`，`pra resume --run-id acceptance_world_model` |

## 1. idea 被明确成了哪些问题

- **H1**（kept）：Temporal hierarchy: high-level model over abstract time, low-level over primitive steps (distinguish_representation_temporal_policy_and_planning_hierarchies).
- **M1**（kept）：Nested solution dependence: the high level is trained through the low level's solution map (distinguish_multiple_losses_alternating_updates_and_nested_solution_dependence).
- **M2**（kept）：Several losses minimised with alternating updates (no solution dependence).
- **X**（rejected_too_broad）：Every hierarchical world model is a multi-level optimisation problem. —— 拒绝原因：conflates network hierarchy with nested optimisation

指标状态：`undecided`（输入未指定指标时保持 undecided）。

待澄清项：
- Which decision signal and baseline decide success (identify_decision_signal_and_baseline): planning return, not prediction error?
- Is cross-task reuse claimed (evaluate_cross_task_reuse_if_claimed)? If so, which tasks are held out from method selection?

## 2. 与你的研究的关系、需要学习的内容

| 概念 | 已有能力（来自 profile） | 领域重要性 | 依据 |
|---|---|---|---|
| bilevel optimization | medium | medium | profile expertise 'bilevel optimization' (stated, not verified; source user_context_2026-11-24) |
| temporal abstraction | low | unknown | no matching expertise record in the profile |
| world model | low | high | no matching expertise record in the profile |

学习任务（熟悉度与科学价值分开记录）：
- learning task: world-model planning benchmarks and baselines（needed to test any planning claim）

方法联系（条件与状态）：
- bilevel optimization → x = high-level model, y = low-level model, y*(x) = low-level solution map; hypergradient via finite inner steps；状态 hypothesis；条件：actual solution dependence between levels

## 3. 领域问题、关键文献与最近邻

- **WP1** Learned models for long-horizon planning（single_source；指标：planning return）
- **WP2** How to train coupled levels (nested vs alternating)（disputed；指标：prediction error (insufficient for planning claims)）

| 文献 | 来源 | 正文状态 | 实际读取范围 |
|---|---|---|---|
| [SYNTHETIC FIXTURE] Temporal abstraction in hierarchical world models | fixture（合成） | partial_text | §1, §2, §3 |
| [SYNTHETIC FIXTURE] Bilevel training of latent dynamics | fixture（合成） | partial_text | §1, §2, §3 |
| [SYNTHETIC FIXTURE] Multi-loss world-model training with alternating updates | fixture（合成） | partial_text | §1, §2, §3 |

未检索到不等于不存在；离线运行没有执行真实检索。

## 4. 候选、部分排序与变化原因

- **rev_W1_v1**（active，分支 empirical）：Nested training of the high-level model through the low-level solution map
  - 假设：Training the high-level world model through the low-level solution map improves long-horizon planning return over alternating multi-loss training at matched compute
- **rev_W2_v1**（rejected，分支 empirical）：Alternating multi-loss training suffices
  - 假设：Alternating multi-loss updates reach the same solution as nested training, so nested optimisation adds nothing

最新排序（第 1 轮）：preferred=[]，ties=[]，unresolved=['rev_W1_v1']

- 淘汰 rev_W2_v1：applicable verified refutation: verified counterexample satisfying the claim's assumptions (closed_form)

| 轮次 | 变化 |
|---|---|
| 1 | {"candidates": ["rev_W2_v1"], "change": "rejected", "evidence": [{"evidence_ids": ["ev_18eb277ff2ce0e09"]}]} |
| 1 | {"change": "unresolved", "evidence": [{"evidence_ids": ["ev_18eb277ff2ce0e09"]}], "from": ["rev_W1_v1", "rev_W2_v1"], "to": ["rev_W1_v1"]} |

| 候选版本 | 维度 | 状态 | 判断 | 依据 |
|---|---|---|---|---|
| rev_W1_v1 | scientific_value | known | high | planning return is the field's bottleneck (synthetic) |
| rev_W1_v1 | novelty | unknown | null | no live search |
| rev_W1_v1 | feasibility | known | low | W1 needs GPU-scale training via v3; W2 is cheap |
| rev_W2_v1 | scientific_value | known | medium | planning return is the field's bottleneck (synthetic) |
| rev_W2_v1 | novelty | unknown | null | no live search |
| rev_W2_v1 | feasibility | known | high | W1 needs GPU-scale training via v3; W2 is cheap |
| rev_W2_v1 | scientific_value | disputed | null | re-evaluated after refutation: applicable verified refutation: verified counterexample satisfying the claim's assumption |
| rev_W2_v1 | novelty | disputed | null | re-evaluated after refutation: applicable verified refutation: verified counterexample satisfying the claim's assumption |
| rev_W2_v1 | feasibility | disputed | null | re-evaluated after refutation: applicable verified refutation: verified counterexample satisfying the claim's assumption |

## 5. 已执行行动、成本、负结果与未决问题

| 行动 | 目的 | 结果 | 摘要 |
|---|---|---|---|
| query:clarify_problem | information_gathering | succeeded | clarify_problem: 7 answers, 6 records |
| query:read_paper | information_gathering | succeeded | read_paper: 8 answers, 2 records |
| query:read_paper | information_gathering | succeeded | read_paper: 8 answers, 2 records |
| query:read_paper | information_gathering | succeeded | read_paper: 8 answers, 2 records |
| query:map_field | information_gathering | succeeded | map_field: 4 answers, 1 records |
| query:link_background | information_gathering | succeeded | link_background: 8 answers, 5 records |
| query:propose_candidates | information_gathering | succeeded | propose_candidates: 4 answers, 4 records |
| query:check_candidate | information_gathering | succeeded | check_candidate: 8 answers, 3 records |
| query:check_candidate | information_gathering | succeeded | check_candidate: 8 answers, 3 records |
| query:update_decision | information_gathering | succeeded | update_decision: 9 answers, 1 records |
| cpu_pilot | preliminary_check | succeeded | toy quadratic (a=1, lam=0.5, c=1): nested x*=1.615385, alternating x=1.000000, upper-objective gap=0.547009; numerical runs match closed forms: True |
| query:make_research_spec | preliminary_check | succeeded | make_research_spec: 5 answers, 1 records |
| query:update_decision | information_gathering | succeeded | update_decision: 9 answers, 1 records |
| query:check_claim_evidence | audit | succeeded | check_claim_evidence: 4 answers, 1 records |

预算使用（fixture 调用单独计为 fixture，不计作真实模型调用或费用）：

| 维度 | 已用 | 上限 |
|---|---|---|
| llm_calls | 13.0 | 40.0 |
| input_tokens | 18940.0 | 200000.0 |
| output_tokens | 10420.0 | 80000.0 |
| search_queries | 5.0 | 24.0 |
| full_text_reads | 3.0 | 12.0 |
| pilots | 1.0 | 3.0 |
| actions | 1.0 | 20.0 |
| gpu_hours | 0.0 | 0.0 |
| usd | 0.0 | 0.0 |

研究主张（pilot/formal 分开标注）：

- On a two-level quadratic instance, nested (solution-dependent) training and alternating two-loss training reach different solutions, so the two readings of multi-level optimisation are distinct problems —— supported，proof_status=draft，stage=pilot，audit=passed
- Alternating multi-loss updates reach the same solution as nested training, so nested optimisation adds nothing —— refuted，proof_status=disproved，stage=pilot，audit=passed

未决问题：
- [high] Which decision signal and baseline decide success (identify_decision_signal_and_baseline): planning return, not prediction error?
- [medium] Is cross-task reuse claimed (evaluate_cross_task_reuse_if_claimed)? If so, which tasks are held out from method selection?
- [high] learning task: world-model planning benchmarks and baselines
- [high] Is there a runnable world-model baseline with a planning-return evaluator?

## 6. 推荐的研究规格或停止原因

- rev_W1_v1 门槛未通过：not in the preferred set of the partial ranking (decisive dimension unknown); decisive dimensions unknown: ['novelty']; no nearest neighbour read substantively from a live source (fixture/synthetic or abstract-only reading does not count); resources for the next stage are not available (backend/branch); cheap disqualifying checks still open: ['unk_decision_signal', 'unk_wm_baseline']
- no executable, non-duplicate, affordable action remained
- research_outcome=not_run: only preliminary checks ran for empirical/mixed candidates; pilot findings (not research results): claim_rev_W1_v1_C1=supported/draft; claim_rev_W2_v1_C1=refuted/disproved
- 下一项最有价值的检查：Which decision signal and baseline decide success (identify_decision_signal_and_baseline): planning return, not prediction error?
