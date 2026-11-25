# 决策报告：mdp_uncertainty

> **来源说明**：本次为离线验收运行（offline_local）。澄清、文献、领域地图、候选与排序判断来自明确标记的 fixture（合成测试数据），只用于检验决策流程，不构成文献结论或新颖性判断。实际计算（如 MDP 枚举）在单独的 computation 命名空间中，可以作为证据。

## 状态

| 字段 | 值 |
|---|---|
| operation_status | completed |
| planning_outcome | inconclusive |
| research_outcome | refuted |
| manuscript_status | not_generated |
| stop_reason | no_available_action |
| strategy | personalized_loop |
| rounds | 5 |
| model binding | 无（fixture 运行不创建真实模型绑定） |
| checkpoint / 恢复入口 | `runs/acceptance_mdp/state.sqlite`，`pra resume --run-id acceptance_mdp` |

## 1. idea 被明确成了哪些问题

- **I1**（kept）：Same hidden reward parameter, fixed per episode (A) vs redrawn i.i.d. per step (B); compare optimal values under the same history-dependent policy class.
- **I2**（open）：Bayesian (expected) vs robust (worst-case) treatment of the same uncertainty set.
- **I3**（rejected_too_broad）：All forms of MDP uncertainty are equivalent. —— 拒绝原因：no uncertainty object, policy class or equivalence_definition is fixed; not testable as stated

指标状态：`undecided`（输入未指定指标时保持 undecided）。

待澄清项：
- Which equivalence notion is intended: equal optimal value, same optimal policy, or the same decision problem?
- Is the comparison under expected return or worst-case return?

## 2. 与你的研究的关系、需要学习的内容

| 概念 | 已有能力（来自 profile） | 领域重要性 | 依据 |
|---|---|---|---|
| Bayes-adaptive MDP | low | unknown | no matching expertise record in the profile |
| robust MDP | low | medium | no matching expertise record in the profile |
| minimax optimization | medium | medium | profile expertise 'nonconvex minimax optimization' (stated, not verified; source user_context_2026-11-24) |
| value of information | low | high | no matching expertise record in the profile |

学习任务（熟悉度与科学价值分开记录）：
- learning task: value of information / Bayes-adaptive MDPs（core quantity of FP1; no matching profile record）

方法联系（条件与状态）：
- nonconvex minimax optimization → outer policy minimisation vs nature's per-step maximisation in rectangular robust MDPs；状态 supported；条件：(s,a)-rectangularity
- bilevel optimization → outer policy optimisation over an inner belief update in Bayes-adaptive planning；状态 hypothesis；条件：belief update is a solution map of an inner problem

## 3. 领域问题、关键文献与最近邻

- **FP1** When does persistent parameter uncertainty make history valuable?（single_source；指标：optimal value under a fixed policy class）
- **FP2** When do robust (worst-case) formulations reduce to per-step games?（single_source；指标：robust value）
- **FP3** When can per-step randomness be marginalised into an ordinary MDP?（single_source；指标：optimal value）

| 文献 | 来源 | 正文状态 | 实际读取范围 |
|---|---|---|---|
| [SYNTHETIC FIXTURE] Value of information in Bayes-adaptive MDPs | fixture（合成） | partial_text | §1, §2, §3 |
| [SYNTHETIC FIXTURE] Marginalising per-step i.i.d. parameters | fixture（合成） | partial_text | §1, §2, §3 |
| [SYNTHETIC FIXTURE] Rectangular robust MDPs as per-step games | fixture（合成） | partial_text | §1, §2, §3 |

未检索到不等于不存在；离线运行没有执行真实检索。

## 4. 候选、部分排序与变化原因

- **rev_CAND-A_v1**（rejected，分支 theoretical）：Equivalence of fixed and i.i.d. parameter uncertainty under one history-dependent policy class
  - 假设：For finite-horizon MDPs with a hidden reward parameter, fixed-per-episode and i.i.d.-per-step parameter uncertainty with the same marginal give the same optimal value under the same history-dependent policy class
- **rev_CAND-B_v1**（active，分支 theoretical）：The value gap between fixed and i.i.d. parameters is the value of history
  - 假设：In the binary-action family with immediately observed rewards r_t = 1[a_t = theta_t], V*_B(history) equals V*_A(open-loop), so the gap V*_A(history) - V*_B(history) equals the value of using history in A
- **rev_CAND-C_v1**（rejected，分支 theoretical）：Rectangular robust MDPs as minimax games (link to the user's minimax work)
  - 假设：Robust value under rectangular sets equals a per-step minimax game value
- **rev_CAND-A_v2**（active，分支 theoretical）：Equivalence of fixed and i.i.d. parameter uncertainty under open-loop policies
  - 假设：Under history-independent (open-loop) policies, fixed-per-episode and i.i.d.-per-step parameter uncertainty with the same marginal give the same optimal value
  - 版本变化：C1 refuted by an exact counterexample under history-dependent policies; narrowed to the open-loop policy class（父版本 rev_CAND-A_v1）

最新排序（第 4 轮）：preferred=[]，ties=[]，unresolved=['rev_CAND-A_v2', 'rev_CAND-B_v1']

- 淘汰 rev_CAND-C_v1：substantive coverage: every claim covered by paper_fixture_mdp_robust_rectangular#§2 [fixture evidence: flow test only]

| 轮次 | 变化 |
|---|---|
| 1 | {"candidates": ["rev_CAND-A_v1"], "change": "rejected", "evidence": [{"evidence_ids": ["ev_18eb277fbaf2e033"]}]} |
| 1 | {"change": "unresolved", "evidence": [{"evidence_ids": ["ev_18eb277fbaf2e033"]}], "from": ["rev_CAND-A_v1", "rev_CAND-B_v1"], "to": ["rev_CAND-B_v1"]} |
| 2 | {"change": "unresolved", "evidence": [{"evidence_ids": ["ev_18eb277fc090d974"]}], "from": ["rev_CAND-B_v1"], "to": ["rev_CAND-A_v2", "rev_CAND-B_v1"]} |

| 候选版本 | 维度 | 状态 | 判断 | 依据 |
|---|---|---|---|---|
| rev_CAND-A_v1 | scientific_value | known | medium | would connect FP1 and FP3 if true |
| rev_CAND-A_v1 | novelty | unknown | null | no live search was run; unknown is not low |
| rev_CAND-A_v1 | feasibility | known | high | small instances are solved exactly by enumeration |
| rev_CAND-B_v1 | scientific_value | known | high | addresses FP1 directly |
| rev_CAND-B_v1 | novelty | unknown | null | C2 appears covered; C1 needs a live search |
| rev_CAND-B_v1 | feasibility | known | medium | finite family is cheap; a general proof is harder |
| rev_CAND-C_v1 | novelty | known | low | statement covered by Theorem 2 (synthetic) |
| rev_CAND-C_v1 | scientific_value | disputed | null | re-evaluated after refutation: substantive coverage: every claim covered by paper_fixture_mdp_robust_rectangular#§2 [fix |
| rev_CAND-C_v1 | novelty | disputed | null | re-evaluated after refutation: substantive coverage: every claim covered by paper_fixture_mdp_robust_rectangular#§2 [fix |
| rev_CAND-C_v1 | feasibility | disputed | null | re-evaluated after refutation: substantive coverage: every claim covered by paper_fixture_mdp_robust_rectangular#§2 [fix |
| rev_CAND-A_v1 | scientific_value | disputed | null | re-evaluated after refutation: applicable verified refutation: verified counterexample satisfying the claim's assumption |
| rev_CAND-A_v1 | novelty | disputed | null | re-evaluated after refutation: applicable verified refutation: verified counterexample satisfying the claim's assumption |
| rev_CAND-A_v1 | feasibility | disputed | null | re-evaluated after refutation: applicable verified refutation: verified counterexample satisfying the claim's assumption |
| rev_CAND-A_v2 | scientific_value | known | low | close to a direct consequence of marginalisation |
| rev_CAND-A_v2 | novelty | unknown | null | needs a live search |
| rev_CAND-A_v2 | feasibility | known | high | finite check is cheap |

## 5. 已执行行动、成本、负结果与未决问题

| 行动 | 目的 | 结果 | 摘要 |
|---|---|---|---|
| query:clarify_problem | information_gathering | succeeded | clarify_problem: 7 answers, 7 records |
| query:read_paper | information_gathering | succeeded | read_paper: 8 answers, 3 records |
| query:read_paper | information_gathering | succeeded | read_paper: 8 answers, 3 records |
| query:read_paper | information_gathering | succeeded | read_paper: 8 answers, 3 records |
| query:map_field | information_gathering | succeeded | map_field: 4 answers, 1 records |
| query:link_background | information_gathering | succeeded | link_background: 8 answers, 7 records |
| query:propose_candidates | information_gathering | succeeded | propose_candidates: 4 answers, 9 records |
| query:check_candidate | information_gathering | succeeded | check_candidate: 8 answers, 3 records |
| query:check_candidate | information_gathering | succeeded | check_candidate: 8 answers, 3 records |
| query:check_candidate | information_gathering | succeeded | check_candidate: 8 answers, 1 records |
| query:update_decision | information_gathering | succeeded | update_decision: 9 answers, 1 records |
| cpu_pilot | preliminary_check | succeeded | exact enumeration (H=2, p=1/2): V*_A(history)=3/2, V*_B(history)=1, V*_A(open-loop)=1 |
| query:make_research_spec | preliminary_check | succeeded | make_research_spec: 5 answers, 1 records |
| query:update_decision | information_gathering | succeeded | update_decision: 9 answers, 1 records |
| counterexample_search | preliminary_check | succeeded | claim voi_identity holds on all 12 instances of the finite family (H in [1, 2, 3], p in ['1/2', '1/3', '2/3', '1/4']); finite-instance support only |
| query:make_research_spec | preliminary_check | succeeded | make_research_spec: 5 answers, 1 records |
| query:check_candidate | information_gathering | succeeded | check_candidate: 8 answers, 3 records |
| query:update_decision | information_gathering | succeeded | update_decision: 9 answers, 1 records |
| check_theory | preliminary_check | succeeded | proof status draft (llm) |
| query:check_theory | preliminary_check | succeeded | check_theory: 5 answers, 1 records |
| query:update_decision | information_gathering | succeeded | update_decision: 9 answers, 1 records |
| counterexample_search | preliminary_check | succeeded | claim eq_open holds on all 12 instances of the finite family (H in [1, 2, 3], p in ['1/2', '1/3', '2/3', '1/4']); finite-instance support only |
| query:make_research_spec | preliminary_check | succeeded | make_research_spec: 5 answers, 1 records |
| query:update_decision | information_gathering | succeeded | update_decision: 9 answers, 1 records |
| query:check_claim_evidence | audit | succeeded | check_claim_evidence: 4 answers, 1 records |

预算使用（fixture 调用单独计为 fixture，不计作真实模型调用或费用）：

| 维度 | 已用 | 上限 |
|---|---|---|
| llm_calls | 21.0 | 40.0 |
| input_tokens | 45132.0 | 200000.0 |
| output_tokens | 19494.0 | 80000.0 |
| search_queries | 5.0 | 24.0 |
| full_text_reads | 3.0 | 12.0 |
| pilots | 3.0 | 3.0 |
| actions | 4.0 | 20.0 |
| gpu_hours | 0.0 | 0.0 |
| usd | 0.0 | 0.0 |

研究主张（pilot/formal 分开标注）：

- For finite-horizon MDPs with a hidden reward parameter, fixed-per-episode and i.i.d.-per-step parameter uncertainty with the same marginal give the same optimal value under the same history-dependent policy class —— refuted，proof_status=disproved，stage=pilot，audit=passed
- In the binary-action family with immediately observed rewards r_t = 1[a_t = theta_t], V*_B(history) equals V*_A(open-loop), so the gap V*_A(history) - V*_B(history) equals the value of using history in A —— unproven，proof_status=draft，stage=pilot，audit=passed
- Under history-independent (open-loop) policies, fixed-per-episode and i.i.d.-per-step parameter uncertainty with the same marginal give the same optimal value —— unproven，proof_status=draft，stage=pilot，audit=passed

未决问题：
- [high] Which equivalence notion is intended: equal optimal value, same optimal policy, or the same decision problem?
- [medium] Is the comparison under expected return or worst-case return?
- [high] learning task: value of information / Bayes-adaptive MDPs
- [high] Is the (narrowed) CAND-A statement already known in the literature?
- [high] Is the value-of-history characterisation already known?

## 6. 推荐的研究规格或停止原因

- rev_CAND-A_v2 门槛未通过：not in the preferred set of the partial ranking (decisive dimension unknown); decisive dimensions unknown: ['novelty']; no nearest neighbour read substantively from a live source (fixture/synthetic or abstract-only reading does not count); cheap disqualifying checks still open: ['unk_novelty_A']
- rev_CAND-B_v1 门槛未通过：not in the preferred set of the partial ranking (decisive dimension unknown); decisive dimensions unknown: ['novelty']; no nearest neighbour read substantively from a live source (fixture/synthetic or abstract-only reading does not count); cheap disqualifying checks still open: ['unk_novelty_B']
- no executable, non-duplicate, affordable action remained
- research_outcome=refuted from pilot (theoretical branch: counterexamples are disproofs) claims: claim_rev_CAND-A_v1_C1=refuted/disproved; claim_rev_CAND-B_v1_C1=unproven/draft; claim_rev_CAND-A_v2_C1=unproven/draft
- 下一项最有价值的检查：Which equivalence notion is intended: equal optimal value, same optimal policy, or the same decision problem?
