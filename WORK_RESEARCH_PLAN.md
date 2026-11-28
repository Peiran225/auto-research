# Work 桌面科研执行计划

版本：1.0｜日期：2026-11-26（America/Chicago）｜用途：供 ChatGPT 桌面 Work 持续执行、Claude Code 接手实现与会话恢复。

## 1. 已确认的目标、分工与当前状态

目标闭环：Work 明确问题、读文献、形成候选和实验规格 → 通过桌面 SSH 提交学校服务器 → AI-Scientist-v3 编排研究实验 → Work 收集证据、分析、修订候选与下一行动。

| 执行者 | 负责内容 | 交接产物 |
| --- | --- | --- |
| ChatGPT 桌面 Work | Q1–Q5 科研判断、真实阅读、候选、实验设计、理论分析、证据审计、结果解释 | 版本化研究记录、冻结 ResearchSpec、下一行动、研究报告 |
| Claude Code | 一次性接口改造、代码实现与修复、必要的具体 taskkit 准备 | 可执行工具、真实 baseline/evaluator、验证记录 |
| AI-Scientist-v3 | 正式实验中的研究代码迭代、investigation、消融、posthoc 与首份实验论文草稿 | 原始运行目录、候选代码、指标、消融、论文初稿 |
| v3 内部 Claude agent | 在 v3 的编排和预算内实现、修改、测试研究代码 | v3 记录的代码版本与运行产物 |
| 学校服务器 | 计算、持久化实验、任务监督、独立超时与资源限制 | job receipt、状态、预算账本、可核验结果包 |

1. 保留 `CODEX_IMPLEMENTATION_PLAN.md` 作为历史实施规格；本文件接管 Work 科研工作流，不要求重做 M0–M8。
2. 已有 CLI、类型、数据库、MDP 示例和 v3 adapter 优先复用；仅补齐 Work 交接、实验入口、远程运行与守护的必要差额。
3. Work 本身承担研究对话，不绕回前端 Responses API；历史 API 配置与 ModelBinding 不作为 Work 启动条件。
4. 当前提供的代码只证明接口实现文本存在。`backend.materialize_task` 仅支持 `mdp_policy`；实际服务器安装、运行能力及 Work→UTA 连接尚无本会话可核验证据。
5. 当前 adapter 的美元/token 约束为 best_effort；超时处理依赖轮询。不得据此宣称断线后仍有硬限制，须完成服务器守护并实测。
6. 本文件依据原计划第 3–10、12 节与提供的 `models.py`、`backend.py`、`config.py`、`cli.py` 制定；未执行服务器任务、模型调用或 GPU 实验。

## 2. 科学记录与证据规则

每个 query 采用“输入材料及版本＋具体问题＋允许工具与预算＋证据要求＋结构化答案”，不使用专家、教授、审稿人身份设定，不要求答案一定支持或一定反对候选。

- 每项陈述区分 `fact / inference / hypothesis / unknown`。fact 再区分用户给定、文献报告、工具观察；文献报告不等于独立复现。
- 文献事实引用 canonical ID、版本、来源、实际读取位置；可用页码、章节、定理、公式、图表、段落，不猜位置。记录全文获取状态及实际 `read_scope`，二者不可混同。
- 正文状态至少区分 `abstract_only / partial_text / full_text / unavailable`；搜索片段、摘要不能支持未读定理、实现或完整实验结论。“本次未找到”保持读取与检索范围。
- inference 列前提、适用条件、证据与可能改变判断的反证；hypothesis 列可检验预测和否证条件；unknown 对应 null、缺失项与核查方法，不记作零分或 low。
- 论文、证据分别去重；镜像、同一结果的复述和多次模型回答不增加独立证据。保存来源版本、定位、哈希、同源组与依赖关系。
- 关键假设、机制、问题范围、主指标、对照或主要贡献改变即创建新 CandidateRevision；协议改变即创建新 protocol version/hash，重新核查旧证据适用性。
- 事实来源与验证状态分开：fixture、真实 CPU 计算、外部文献、Work 判断、v3 实验分别标识。fixture 不进入真实研究结论或正式写作上下文。
- 每项行动有 `succeeded / no_change / failed / skipped_budget` 等明确结果。负实验可以是成功执行；程序错误不能作为科学反证。
- 熟悉度、学习成本、领域价值、个人偏好、资源限制分别记录；分档有 rubric 与依据，不输出未经校准的创新概率或录用概率。
- 引用结构检查通过不等于语义支持成立；Q4 必须检查原文/实际产物是否支持主张。修复次数有界，缺证据不能靠反复改写消除。

研究者背景种子：Peiran Yu；optimization、bilevel optimization、nonconvex minimax、convergence analysis、optimization for machine learning、multimodal learning。来源为用户提供的上下文；未读本人论文的具体能力保持未核验。

“机制明确、比较条件对齐、主张与证据一致、结论能指导选择”保留为带条件的讨论推断偏好。不得把某次赶截止日期、减少实验等局部决定升级为全局偏好，也不由历史 GPU 信息推断当前算力。

## 3. 工作目录、checkpoint 与事实归属

每次研究建立稳定 `research_run_id`，目录建议为 `runs/work_<id>/`。Work 可读取的工作目录保存科研记录；学校服务器保存实验执行事实。目录迁移可改变路径，不改变 ID、版本与哈希。

| 文件/目录 | 必须保存的内容 |
| --- | --- |
| `checkpoint.md` | 机器可读 YAML 头及简短恢复正文：阶段、状态、引用版本、预算摘要、活动 job、最后已收集结果、下一行动与阻塞 |
| `WORK_LOG.md` | 每轮新增证据、判断改变、选择理由、实际动作与简短恢复说明 |
| `profile.json`、`problem_spec.json` | 背景来源/条件、术语解释、假设、目标、指标状态及缺失项 |
| `queries/`、`papers/` | Q1–Q5 输入指纹、逐问题答案、来源记录、真实读取范围与定位 |
| `candidates/`、`protocols/` | 不可变候选修订、冻结 ResearchSpec、研究分支、候选/协议哈希 |
| `evidence/`、`rankings/` | 证据及关联、Assessment、Unknown、部分排序、反证与变化依据 |
| `requests/`、`jobs/` | 前者保存 task spec/准备请求与校验报告；后者保存 receipt、状态快照、结果 manifest，引用服务器原始产物 |
| `reports/` | decision report、claim-to-evidence map、audit report、理论说明与实际存在的文稿 |

checkpoint 至少含：`schema_version, research_run_id, checkpoint_revision, updated_at, stage, operation_status, planning_outcome, research_outcome, manuscript_status, stop_reason`。
同时记录：`profile_hash, current_candidate_revisions, current_protocol_refs, evidence_manifest_hash, ranking_ref, completed_action_fingerprints, active_jobs, collected_result_hashes, budget, blockers, next_action, resume_instruction`。
`active_jobs` 必须含 server alias、job ID、attempt ID、spec/task snapshot hash、receipt 路径、最后观测时间和状态；状态过旧时明确 unknown，不猜完成。
`budget` 引用已有授权的来源、范围、硬/软上限、已预留/实际/估算/unpriced 用量、剩余额度与截止时间。Work 无法获取的 token、费用及后台配置写 unknown，不填 0。
每次 query、行动、提交、收集、候选/协议修订及暂停后更新 checkpoint；采用临时文件校验后原子替换，保留上一修订，防止半写入被恢复。
Work 科研记录为判断及版本的事实源；服务器现有 SQLite/事务账本为 job、attempt、运行状态和预算扣账的事实源。checkpoint 仅缓存带时间的执行快照，不反向伪造服务器状态。
Claude 应增加 Work 专用来源标识与 provenance/schema 边界，复用可用业务类型；不将 Work 判断标为 fixture，也不冒充 `QueryResult.execution_origin=live` 的 API 调用。现有 live 分支要求 ModelBinding，不能填虚构 binding 绕过。
只记录本次 Work 界面实际可见的产品/模型标签、会话时间与工具能力；不可见的 response ID、token、API model、reasoning.mode/effort 均不声称已知或已配置。
新会话先读 checkpoint、原始输入、当前候选/协议、关键证据及最后行动；不要仅凭上轮自然语言摘要继续研究。

## 4. 启动与连接：先证明本次 Work 能操作服务器

1. 本次 Work 会话检查自己是否有能操作目标服务器的工具：已连接远程项目的 shell，或可用的本机 shell 加 SSH；记录实际工具、环境和时间。Codex/Claude 曾连接成功不能证明 Work 自动继承该连接。
2. 使用用户已配置或随后明确提供的 SSH alias/账号与路径。缺少必要连接信息时先继续离线科研准备，并集中记录缺项；不猜账号、主机或学校目录。
3. 在用户指定服务器工作目录写入小文件，再通过当前会话工具实际读取并核对内容与哈希；记录 `hostname`、当前用户、工作路径、退出码和无凭据的日志。直接远程 shell 不要求额外生成 Mac 本地副本；该步骤验证真实读写能力。
4. 查询服务器现有仓库、v3 commit、Python/锁文件、容器与调度方式，确认允许的计算节点/队列。读取配置不等于授权启动收费 agent 或 GPU。
5. 确定 SSH 传输与远程命令路径、结果包位置、重连方式；无需引入 MCP 或公共网络服务。凭据仅保留在已有凭据机制中，不写入任务包或日志。
6. 尚无可用 Work shell、授权连接或可写目录时设 `blocked_dependency`，给出确切缺项和下一验证步骤；可以完成 Q1–Q4 与待提交规格，不宣称自动闭环已运行。

连接验收只说明该会话当时的能力；恢复或换环境后进行轻量复核。长实验与硬限制必须由服务器自身监督，不能依赖 Work 一直在线或 SSH 终端持续打开。

## 5. Q1–Q5 的实际执行顺序

### Q1：明确 idea 与研究对象

输入：用户 idea、目标会议、背景来源、已有定义与真实资源约束。先列解释分支和稳定 ID，再对每一可推进解释写变量、输入输出、可观测信息、目标与必要假设。
询问结论类型：机制解释、等价条件、反例、算法、收敛结论或经验改进；目标会议只决定定位，不保证录用。不预设 robustness/performance，指标保持 undecided 至任务明确。
“层级世界模型中的 multi-level optimization”分别解释表示/时间/策略/规划层级，并区分多个 loss、交替更新与下层解映射的真实嵌套依赖。
“MDP 中不同形式不确定性是否等价”明确不确定对象、时间依赖、策略信息、决策目标、策略类、时域及等价定义，拒绝过宽的统一等价命题。
产物：Concept、ProblemSpec、解释分支、检索词和 Unknown。验收：每个候选解释均有可支持/反驳的结果类型；足以改变方向的歧义已明确或作为工作假设保留。

### Q2：检索、阅读与领域问题地图

按“领域瓶颈、最近邻、反驳证据、已有方法的潜在联系”分别检索；保存日期、实际查询、返回 ID、去重和未取得全文原因。不把检索失败当作领域空白。
先筛元数据，再针对具体未知读取原文。每篇回答问题/任务、关键变量与机制、作者贡献、理论假设、实验基线/指标/预算、适用限制以及与候选的关系。
每条结论链接到原文定位；记录“作者明确限制”与“Work 推断限制”。获取全文后仍按实际章节记录 read_scope，保留未读且影响判断的部分。
将所读论文整理为“问题—证据—任务/指标—基线—条件分歧”地图，独立评估领域价值；个人熟悉度不改变这一地图。
产物：PaperRecord、Evidence/EvidenceLink、问题地图、reading_status、remaining_questions。验收：核心领域问题及最近邻差异可从实际读取材料复核，未知没有被摘要填补。

### Q3：条件化背景联系与候选生成

将个人背景映射到具体数学结构、变量、目标或算法机制，逐项说明成立条件、已知/未知/反证及最少学习任务。主题词相同不足以证明方法适用。
候选分别写：待回答问题、假设、机制、最近邻实质差异、可证伪预测、最低成本检查、学习成本、工程/理论/实验难度、放弃条件。
考察机制不同且有依据的备选，不为凑数生成方向，也不强行将所有问题改成 bilevel。初始最多 6 个活动候选；其余保存为暂缓而非删除。
产物：方法对应关系、分维度 Assessment、CandidateRevision。验收：每个活动候选至少有一个可执行检查，科学价值与个人适配的依据分开。

### Q4：查新、批评、理论与主张审计

逐 claim 对照最近邻：同条件下已有工作覆盖什么，候选增加什么；检查术语替换、重新参数化、已有结论推论及实验设置差异。不能同条件比较时明确缺项。
检查瓶颈是否真实、机制能否被实验区分、假设是否满足；主动查找足以改变选择的反证，不按支持票数淹没适用反例。
分别标记 `covered / possibly_distinct / contradicted / unresolved`；没有找到缺陷只报告检查范围。新颖性、重要性仍是有条件推断。
可在独立上下文重读命题与原材料，但多次模型意见不算独立科学证据。产物包括逐 claim 审计、Unknown、版本修订建议和旧证据适用性变化。

### Q5：更新决定、选择行动与冻结研究规格

每轮先识别新增/重复/冲突证据，只更新受影响判断；应用已核实的反例、实质覆盖、硬资源约束。证据不足的候选留在 unresolved。
部分排序必须包含 preferred、ties、unresolved、rejected 及理由；pairwise 允许 prefer_a/prefer_b/tie/insufficient_evidence，并链接排序变化依据。
行动优先级：便宜且足以推翻推荐的检查 → 决定前列选择的未知 → 同等作用下更低成本 → 必要的不同机制备选检查。不宣称精确计算了信息价值。
每项行动写 target_unknown、目标 claim/版本、输入指纹、输入文件、预期产物、可区分结果分支、各分支如何改判、成本上限与停止条件。
指纹至少包含行动类型/purpose、目标问题、候选版本及来源/协议哈希；输入未变的已完成行动不重做。仅因模型意见不同不构成新证据或重试理由。
正式推荐须满足：问题/机制明确、最近邻相关部分实质阅读、领域价值有据、最低验证达标、下一阶段资源足够、便宜的决定性检查已完成；偏好敏感时保留条件推荐或 tie。
pilot 可以在正式推荐前执行；formal 必须通过投入门槛。两者都需冻结真实协议。研究分支须从 auto 解析为 theoretical/empirical/mixed，缺项不能猜填。

## 6. 交给服务器的任务契约与拟新增命令

下列 `pra experiment ...` 全部是交给 Claude 实现并验收的新增接口，当前不是已有命令。参数为统一建议契约；Claude 需生成 `docs/WORK_COMMANDS.md`，以其中经过实测且与实际 `--help` 一致的命令为操作依据。

| 拟新增入口 | 行为与完成凭证 |
| --- | --- |
| `pra experiment validate --spec PATH --config PATH` | 不调用外部 agent；验证 schema、版本、预算能力及已准备 taskkit；需要的 baseline/evaluator 检查在明确资源范围内执行并单独记录；返回 validation report |
| `pra experiment submit --spec PATH --config PATH --job-id ID --request-id REQUEST_ID` | 原子预留预算、持久化任务身份与监督配置，再异步提交；返回 job receipt；request ID 作为幂等键，相同请求/spec 不重复启动 |
| `pra experiment status --job-id ID` | 只读返回原始/规范化状态、阶段、最近心跳、资源、deadline、缺失 telemetry；不触发研究或费用 |
| `pra experiment collect --job-id ID` | 生成/取回带哈希的结果 manifest 与小结果包；可重复收集且不重复计账；大产物保留服务器 |
| `pra experiment cancel --job-id ID` | 请求停止该 job 的受管进程、子进程/容器/调度任务；返回请求与最终停止状态，二者不得混淆 |
| `pra experiment prepare --request PATH --config PATH` | 在具体 coding request 下调用 Claude 准备任务包；实现相同能力的受控命令也可；新代码阶段要做到自动交接，此入口必须通过验证 |

prepare 不复制 v3 的正式编码/搜索循环；调用 Claude 时继承已有明确授权预算，否则先交付可审阅任务与缺项。仅完成已有任务包的 submit/collect 时，验收范围不得包含“新实验代码的自动准备”。
这些入口读取独立实验配置，复用后端类型与账本；不得为了让无前端 API 的 Work 能提交任务而削弱历史 live 模式校验。

task spec 最少包含以下契约组：

| 契约组 | 必需字段或内容 |
| --- | --- |
| 身份与来源 | schema_version、research_run_id、action_id、candidate_revision_id、protocol_id/version/hash、输入引用/哈希、purpose、study_stage |
| 科学目标 | hypothesis、falsification、scope、branch、continue/abandon criteria；理论任务另含 proof obligations |
| 执行输入 | taskkit ID/version/hash、baseline 与代码 commit、数据/环境版本与切分、固定 evaluator、依赖/容器、实际入口 |
| 比较协议 | 主指标与方向、有效性条件、对照、训练/推理预算、种子/重复策略、proxy 与最终指标、噪声处理 |
| 资源与授权 | CPU/RAM、GPU 设备与 GPU-hours、wall/action deadline、workers、cycles、evaluations、replications、货币/调用上限及硬度、授权引用 |
| 后端配置 | 固定 v3 commit/锁文件/容器、内部 agent=Claude 的实际配置与可见版本、允许阶段、独立于 Work 的模型记录 |
| 产物与恢复 | 预期 artifact roles、服务器根目录、job ID、request ID/幂等键、任务快照、停止/失败标准、允许的恢复阶段 |

submit receipt 至少返回：job/attempt ID、接收时间、server/run_dir、spec/task snapshot hash、代码和环境版本、预算预留 ID、监督/调度 ID、deadline 与状态入口。
服务器启动前再次校验冻结输入及 baseline 验证状态；目标、指标、评价器改变必须新协议，不能在旧 receipt 下偷偷替换任务。
hand-written task 默认采用 investigation、ablations、posthoc、paper；不手写 `task_contract.json`，不冒用 sealed final，不无条件加入 final_evaluation。

## 7. taskkit、理论与两条研究路线

### 7.1 首个 CPU taskkit：MDP

优先复用已有 `mdp_policy`，验证 scaffold、baseline、evaluator-owned scoring、有限分数、correctness、每次重复产物以及失败分类；拒绝 candidate 自报分数、缺产物和非有限数值。
用真实枚举/精确动态规划重算两步 MDP：动作二元，奖励立即可见；A 的隐藏参数整局固定，B 每步独立，二者策略均可访问自己的历史；另设不使用历史的对照。
预期验收值 A 最优历史策略 3/2、B 最优 1、A 无历史策略 1；这些是既有演示 oracle，不是新发现。不得通过剥夺 B 的记忆制造差异。
保存计算产物、协议、命令、推导与范围明确说明；只支持有限实例及信息价值差异，不证明所有 MDP 不确定性均不等价。流程 fixture 与实际枚举证据分开。

### 7.2 层级世界模型与 H-JEPA 候选

`mdp_policy` 可验证交接与计算链路，不能代表 H-JEPA/世界模型任务已可运行。先由 Work 核对最近邻和候选机制，再给 Claude 一份具体 taskkit 规格。
taskkit 必须有真实可运行 baseline、可合法访问的数据/环境、正确的数据切分与预处理、可测的指标、evaluator、资源估计和小规模复现。未满足则保持 blocked，而非生成模拟训练结果。
区分层级网络结构、多个 loss 与真正下层解依赖，明确有限步近似、学习信号与要改变的量；机制实验对齐模型规模、数据、训练和推理计算。
声称长期规划改进时需要规划相关评价，不能仅凭预测误差；声称跨任务复用时需要未用于方法选择的任务。先冻结 pilot，再决定是否值得 formal。
首版不承诺“任意一句 idea 自动变成任务包”，但必须有接受具体编码要求、自动交给 Claude 并收回检查结果的 prepare 路径。至少一个真实 baseline/evaluator 验证过的具体 taskkit 是运行验收前提；新增 H-JEPA taskkit 单独验收。

### 7.3 理论分支

保存 theorem_statement、量词、assumptions、policy/information class、proof obligations、引理依赖、反例搜索计划与 review_method；不为接入 v3 编造 combined_score。
proof_status 使用 unproven/draft/gap_found/reviewed/formally_verified/disproved；reviewed 注明人工、LLM 或其他检查，可信证明检查器实际通过才可标 formally_verified。
数值结果只支持检查过的有限实例；满足全部假设的真实反例可以否证，证明未完成只表示未决。假设变化后重审依赖与旧证据。
mixed 拆成理论与实验行动，共用总预算；一个分支成功不使另一分支自动成立。正式实验仍交 v3，Work 负责理论分析和证据审计。

## 8. 执行、等待、收集与恢复

开始：读取 checkpoint → 校验本会话 SSH → 核对现有活动 job → 选择 Q5 的下一行动 → 冻结 spec → validate → 预留并 submit → receipt 写入 checkpoint。不能在未知旧 job 状态下再提交一次。
等待：短任务在当前 Work 任务存活时有界查询 status；报告阶段、最近有效进展与剩余预算。长任务交服务器监督，Work 可继续不冲突的文献/审计工作，或保存 checkpoint 后暂停。
断开：SSH/Work 消失不能使实验失去 deadline。服务器监督须独立停止进程组、容器/调度子任务，记录实际消耗和终止原因；单纯 nohup/tmux 或 Work 的 poll 不算预算守护。
恢复：重新证明连接，读 receipt 与服务器账本，核对 run/task snapshot 与阶段；先 reconciliation，再决定继续、收集、取消或在已有预算内重试。
同一逻辑行动的失败重试使用新 attempt，保留原失败与成本；未知 job 不重跑；已完成行动不重复执行、证据导入或扣账。任务漂移创建关联新 run/协议。
Work 任务结束后，SSH 或 MCP 的存在不会自动唤醒分析；跨会话自动触发、排程和通知是另行验证项。当前可验收的是会话内闭环及跨会话可恢复，不宣称无限后台自治。

结果契约最少返回：身份/版本/哈希、raw_status、normalized_status、完成/失败阶段、时间与退出原因、预算实际/估算/unpriced、环境、metrics、correctness、manuscript 状态及 artifact manifest。
manifest 每项含 artifact ID、role、服务器路径、大小、哈希、协议/候选版本、`present/missing/not_applicable/not_run` 与原因。大模型权重、数据、完整日志留服务器，只按审计需要读取片段或指定文件。
默认收集小型结构化指标、各重复结果、协议/配置、关键事件、选中代码引用、成本摘要、必要图表与文稿清单；派生摘要保留对应原始产物及生成方法。
状态保留 no_winner、not_qualified、degraded、failed、interrupted 等差别；有 PDF 或进程退出码 0 都不代表主张成立。缺失指标不填 0，未产文稿写 not_generated 和具体原因。
Work 在 Q4 逐条核查结果来源、版本、数据切分、对照公平性、重复与不确定性、机制区分及反证，再由 Q5 更新 supported/refuted/inconclusive；计算故障另记 execution_error。
冻结后的最终评价不得被静默反复用于选方法；proxy 与最终指标分开。结果诱发新假设可记录，但须新候选/协议再验证，不回写成预先提出。

## 9. 预算、停止与交付门槛

初始确定性验收实验使用 CPU、GPU-hours=0、外部 agent/API 金额=0；真实 baseline/evaluator 与固定计算无需模型调用。这里不包含正在进行的 Work/Claude 开发会话自身平台用量。建议每项验证 60 秒、整组 300 秒、并行 1，按实际依赖可显式修订。
Work 首轮科研建议最多 6 轮、20 项行动、24 次搜索、12 篇针对性正文阅读、3 个 pilot、连续 2 轮无新信息即复核停止；这些为可调整初值，不是最优科研预算。
Work 无法看到的内部 token、后台调用及费用不当作可执行上限；使用可观察的行动/检索/阅读/时长限制。v3 内部 Claude 费用与计算均计入对应已授权研究总预算。
已有明确授权的预算、设备和范围直接继承，不重复请示；无收费授权时完成 CPU 验收和可审阅规格。检测到凭据或 GPU 不自动扩大授权。
服务器对可执行硬维度独立控制；并行任务原子预留，失败/重试计账，总 deadline 不因阶段/重连重置。美元/token 若只能 best_effort，明确报告；若任务要求 strict 而无法兑现，拒绝启动该收费行动并保留可继续工作。

| 状态维度 | 允许结果及解释 |
| --- | --- |
| operation_status | created/running/paused/blocked_dependency/completed/failed：说明执行状态 |
| planning_outcome | recommended/no_viable_candidate/inconclusive/not_run：说明选题结果 |
| research_outcome | supported/refuted/inconclusive/not_run：说明已审计的研究结论 |
| manuscript_status | not_run/not_generated/draft/evidence_checked/ready_for_human_review：说明实际文稿阶段 |

仅所有候选实质淘汰且没有未决候选时可报告 no_viable_candidate；预算/轮数/no_change 耗尽输出 inconclusive，不硬选冠军，不声称排序收敛。
每次停止保留已知、未知、反证、下一项最高价值检查、已花预算、活动 job、确切恢复动作及路径。依赖失败不否定科学假设，也不静默更换后端模型。
正式实验初稿由 v3 paper 阶段提供；Work 收集并逐 claim 审计、指出修改及解释结果，不另建第二套实验论文写作循环。理论说明可由 Work 根据已核验推导整理。
数字和图表来自真实产物及可复算过程；只有实际文件才交付 manuscript、references、TeX/PDF。文稿缺失、编译未验证及未决主张如实标明。

## 10. 按证据推进的验收与下一步

| 阶段 | 应执行的工作 | 通过证据 |
| --- | --- | --- |
| A：必要改造 | Claude 阅读现有仓库约束，复用 backend/schema，补 experiment 入口、Work 边界、事务/守护与契约 | 实际帮助、改动清单、CPU 验证记录；无前端模型探测/收费调用 |
| B：一个真实 taskkit | MDP baseline/evaluator、伪分数/缺产物/非有限结果拒绝、协议漂移检查 | 真实计算与原始产物；fixture 与计算证据分离 |
| C：本会话桌面 SSH | Work 亲自做服务器读写哈希测试与目录/版本核对 | 本次会话的命令、返回值、时间与文件证据 |
| D：CPU 交接闭环 | submit→status→collect；重复提交、重复收集、取消、断线超时和恢复 | 单一 job 身份、无重复扣账、服务器独立终止、哈希匹配结果 |
| E：一次真实科研循环 | Work 完成 Q1–Q5，提交具体 pilot，审计结果并修订候选/排序 | 版本连续的 checkpoint、原始证据、明确改判依据与下一行动 |
| F：有授权的 v3 集成 | 固定版本 doctor/dry-run 后，CPU 任务真实 Claude investigation，再按需要启用其他阶段 | 实际 agent 运行、成本、阶段、恢复和产物；仅 CPU 不表示不收费 |
| G：正式方向研究 | 真实任务 baseline/data/evaluator 通过后，冻结 formal；v3 实验与初稿，Work 审计 | claim-to-evidence、有效比较、实际稿件或明确缺稿、负结果/未决记录 |

专项验收覆盖：unknown 不淘汰、熟悉度不替代价值、反证触发重评、部分排序、候选版本失效检测、数值/证明区别、负结果/故障区别、预算拒绝及恢复幂等。
报告分别写 Engineering、Integration、Research 完成度；CPU 工具验收不等于真实 agent 集成，真实 v3 完成不等于科学贡献成立，稿件生成不等于论文可发表。
现在的下一步：Claude 完成 A/B 的必要改造，同时 Work 从已有材料开展 Q1/Q2；获得本次 Work 可验证的 SSH 能力后依次完成 C/D/E。F 继承已有收费授权，条件缺失则保留 not_run/blocked_dependency 及精确待执行规格。完整自动化验收还须包括 Work 通过 prepare 把具体编码任务交给 Claude 并读回实际结果。
