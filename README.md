# personal-research-agent (`pra`)

一个受预算约束、可恢复、可审计的个性化科研 agent，按 `CODEX_IMPLEMENTATION_PLAN.md`（v1.1）实现。
输入一句 idea、目标会议和研究者档案，系统完成：澄清问题 → 领域地图与文献证据 → 结合个人背景形成候选 →
证据驱动的部分排序循环 → 理论/小规模 CPU 验证 → 交给 AI-Scientist-v3 做正式实验与实验论文初稿 → 证据审计与报告。

实现状态、已验证与未验证的部分见 [`IMPLEMENTATION_STATUS.md`](IMPLEMENTATION_STATUS.md)；
实际执行过的验收命令与输出见 [`docs/acceptance_log.md`](docs/acceptance_log.md)。
本仓库早先的 Claude Code 技能版（`/auto-research`）说明移到了 [`docs/claude_code_skill.md`](docs/claude_code_skill.md)。

## 1. 安装

```bash
uv venv .venv && uv sync --extra dev        # 或: python -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/pra --help
```

依赖固定在 `uv.lock`（Python ≥ 3.11；开发环境为 3.13）。

## 2. 离线流程（不需要任何凭据、不联网）

```bash
.venv/bin/python -m pytest -q
.venv/bin/pra doctor --config configs/offline.yaml
.venv/bin/pra run --task examples/mdp_uncertainty.yaml --profile profiles/peiran.yaml --config configs/offline.yaml --run-id acceptance_mdp
.venv/bin/pra verify --run-id acceptance_mdp
.venv/bin/pra run --task examples/world_model.yaml --profile profiles/peiran.yaml --config configs/offline.yaml --run-id acceptance_world_model
.venv/bin/pra verify --run-id acceptance_world_model
```

`offline_local` 模式在任何模型探测之前分流：模型与文献调用来自 `tests/fixtures/` 中明确标为合成数据的 fixture，
运行期间网络被程序封锁（`netguard.forbid_network`）。决策流程用 fixture 驱动；**实际计算**（MDP 精确枚举、
有限族反例搜索、嵌套 vs 交替优化的玩具检查）真实执行，存放在独立的 `computation` 证据命名空间，只有这些内容会进入研究说明。

MDP 示例单独运行：

```bash
.venv/bin/python -m personal_research_agent.research.mdp_demo --out /tmp/mdp
```

## 3. 命令

| 命令 | 作用 |
|---|---|
| `pra doctor --config C [--check-live]` | 列出能力与具体缺项；`--check-live` 只访问免费端点（模型元数据、arXiv），不启动收费任务 |
| `pra run --task T --profile P --config C --run-id R [--strategy S] [--until PHASE]` | 在配置允许范围内运行闭环；`--strategy` 为 `one_shot / evidence_loop / personalized_loop`，写入该 run 的配置快照 |
| `pra status --run-id R` | operation / planning / research / manuscript 四个状态与预算 |
| `pra resume --run-id R` | 幂等恢复：已完成的行动不重做、不重复扣账；中断的轮次重新进入；终态直接说明无需重跑 |
| `pra report --run-id R` | 只重新生成报告，不调用模型、检索或后端 |
| `pra verify --run-id R` | 检查引用、产物哈希、预算账本、claim–evidence 链接、研究说明中的数值与 fixture 污染 |
| `pra import --run-id R --source S` | 导入你提供的论文：arXiv URL/ID、DOI、论文 URL、本地 PDF/文本（离线只接受本地文件） |
| `pra compare R1 R2 R3` | 同预算的三种决策策略比较（§12.1） |
| `pra v3-validate --config C` | 用固定版本 AI-Scientist-v3 的脚手架生成 MDP CPU 任务，并用上游检查器真实跑 baseline 和反例程序（不启动 agent） |

**返回码**：`0` 正常结束（包括有效的负结果、未决结果和 `--until` 暂停）；`2` 配置错误（含任务文件漂移）；
`3` 运行失败或 `verify` 未通过；`4` 依赖不可用（模型、Pro 模式、凭据或后端）。

## 4. 输出（`runs/<run_id>/`）

| 文件 | 内容 |
|---|---|
| `state.sqlite` | 唯一事务事实源（记录、事件、预算账本、行动指纹、运行锁） |
| `config_snapshot.json` | 冻结的配置、任务、档案与哈希 |
| `reports/decision_report.md` | 中文决策报告：问题澄清、与你研究的关系与学习任务、领域问题与文献、候选的部分排序及变化原因、行动与成本、负结果、未决问题、推荐或停止原因 |
| `reports/research_note.md` | 只基于本次实际计算与已审计 claim 的研究说明（数字在写入时从产物文件读取） |
| `reports/research_spec.json` · `evidence_manifest.json` · `claim_evidence_map.json` · `audit_report.md` | 研究规格、预期产物逐项状态（present/missing/not_applicable/not_run）、claim 与证据映射、审计结果 |
| `artifacts/<action_id>/` | 实际计算产物（JSON/CSV）及完成标记 |
| `export/*.jsonl` | 由数据库重新生成的导出 |

缺稿、无参考文献或无法编译时，不创建空壳文件，在 `evidence_manifest.json` 中写明原因。

## 5. 真实运行（live）需要补充的最少配置

1. `cp configs/live.example.yaml configs/live.yaml`，填写：
   - `backend.checkout / python / agsci`：固定在 `f8ae47d324edcb6c0d430552f1c7729748c0d411` 的 AI-Scientist-v3 checkout（`uv sync` 后）；
   - `backend.agent.name`（以及可选的 `model`）：v3 自己的 agent 配置，与前端 GPT-6 Pro 无关；
   - `llm.pricing.input_per_mtok / output_per_mtok`：用于执行 `limits.api_usd`（不填则调用记为 unpriced）；
   - 有限的 `limits`（calls、tokens、actions、时长、搜索、pilot、`api_usd` > 0）。
2. 在 shell 中导出 `OPENAI_API_KEY`（只从环境读取，不写入任何文件）；v3 agent 的凭据按其 `docs/install.md` 放在 checkout 的 `.env`。
3. `pra doctor --config configs/live.yaml --check-live`，确认 `missing` 为空。
4. `pra run --task ... --config configs/live.yaml --run-id <id>`。

前端模型绑定固定为 OpenAI Responses `model="gpt-6-astra"`、`reasoning={"mode": "pro"}`，不发送 effort，
不允许按任务覆盖、不设回退模型；模型或 Pro 模式不可用时返回 `blocked_dependency`，不会改用其他模型、
standard 模式或 fixture。绑定在 run 创建时冻结并写入数据库，`resume` 复用同一绑定。

## 6. 代码结构

```
src/personal_research_agent/
  cli.py  config.py  models.py  store.py  budget.py  controller.py  profiles.py  netguard.py
  agents/      binding.py (ModelBinding)  providers.py (OpenAI Responses + fixture)  gateway.py  query.py  schemas.py
  literature/  providers.py (arXiv, OpenAlex, URL/DOI/本地导入, fixture)  service.py  base.py
  decision/    ranking.py (部分排序)  rules.py (否决、门槛、停止、行动优先级)
  research/    mdp_demo.py  nested_vs_alternating.py  theory.py  pilots.py  evaluator.py  mdp_policy_scoring.py
  backends/    base.py (ResearchBackend 协议)  local.py  ai_scientist_v3.py
  reporting/   reports.py  audit.py  verify.py  compare.py
prompts/       有版本号的问题式查询模板（Q1–Q5、公共证据契约、JSON 修复、摘要压缩）
configs/ profiles/ examples/   配置、研究者档案、两个任务
tests/pra/     T01–T22 必要测试；tests/fixtures/ 合成数据及其生成脚本
```
