# 给 Claude Code 的实施任务：桌面 Work 与服务器科研执行对接

版本：1.0 · 2026-11-26（America/Chicago）  
目标仓库：Peiran225/auto-research；参考分支：GPT-version  
性质：需要 Claude Code 实现的规格；本文件内的新命令尚不能视为已经存在。

## 0. 任务与已确定分工

请在当前服务器项目中完成实际代码、配置、必要测试与文档。复用现有实现，不重新执行原计划 M0–M8，不只再返回一份计划。

用户已经确定：

| 职责 | 执行者 |
| --- | --- |
| Q1–Q5：问题澄清、文献、背景联系、查新批评、研究决策及结果分析 | ChatGPT 桌面 Work 当前会话 |
| 本次软件改造、实验任务准备、代码编写与修复 | Claude Code |
| 正式实验代码迭代、消融、实验论文初稿 | AI-Scientist-v3，内部 coding agent 选择 Claude |
| 数值计算、训练、数据与产物保存 | UTA 服务器 |
| 桌面内置 SSH 所需的 Codex app server | 连接与远程运行环境；不据此把编码任务改派给 Codex |

最终形成：Work 保存研究规格 → 服务器命令检查/准备任务 → 独立运行实验 → Work 读取结果并决定下一步。第一版通过桌面 SSH 的文件和命令访问对接；无需 MCP、HTTP 服务、Tunnel 或新的 Web 页面。

## 1. 先检查并保护已有工作

1. 读取当前 AGENTS.md、CLAUDE.md、README、CODEX_IMPLEMENTATION_PLAN.md、IMPLEMENTATION_STATUS.md、WORK_RESEARCH_PLAN.md、依赖与锁文件。
2. 检查实际主机、项目路径、Git 分支和未提交修改。参考分支是 GPT-version，但以当前可核查代码为准；不强制切分支、不 reset、不丢弃修改。必要时使用保留当前工作的独立工作分支。
3. 保留原 CODEX_IMPLEMENTATION_PLAN.md 作为软件历史。当前改造以本任务和 WORK_RESEARCH_PLAN.md 的执行分工为准。不要改写旧验收记录来宣布新集成完成。
4. 检查 Python/uv 环境、已有 pra 入口、v3 checkout 与固定版本、Claude CLI 版本和同一运行用户的认证状态。检查可用 GPU 不构成使用全部 GPU 的授权。
5. 为本次改造建立 WORK_INTEGRATION_STATUS.md，分开记录实现、真实接入、研究结论。最后列出可复现命令和剩余阻塞。
6. 本次在服务器保存代码；不推送远程、不发消息、不投稿。例行可逆实现与检查按现有授权继续，不逐步询问。

## 2. 已核对的现有缺口（实施时重新验证）

2026-11-26 读取的 GPT-version 源码显示：

- cli.py 的 pra run 调用原 Controller；pra import 只导入论文。没有外部 ResearchSpec 的独立执行命令。--until 不是导入实验规格后从任意阶段开始执行的接口。
- config.py 的 LLMConfig 只接受 fixture/openai，RunConfig 要求 llm，并将 live 与原 API 预算绑定。不要只写 provider: work 或删掉 API key 就认为已完成适配。
- models.py 的 ExecutionOrigin 只有 fixture/offline_local/live。Work 研究记录要有准确的来源语义；不能伪装成 fixture 或杜撰 API 返回元数据。
- v3 后端已有 probe/materialize_task/validate_task/launch/poll/resume/collect_evidence，可复用。
- materialize_task 当前只接受 mdp_policy；并会删除已有的同名任务目录。需要避免重建覆盖正在运行或已有证据的任务快照。
- v3 probe 当前以某些环境变量或 .env 文件存在来推断认证；这既可能漏掉有效的 Claude 交互登录，也不足以证明非交互调用可用。
- v3 的美元/token 预算是 best_effort。wall deadline 的终止动作在 poll 中；没有持续监督时不能宣称断线后仍严格执行期限。

源码入口见文末链接。实际代码若已修复，保留并说明已有行为，不重复实现。

## 3. 必需交付

1. WORK_RESEARCH_PLAN.md：采用随包计划，依据实际命令作必要校准；保留研究约束，不重新写成软件开发路线。
2. 独立的实验执行入口与配置模型，接收 Work 已确定的规格，不依赖旧前端模型 API。
3. 任务状态、日志、不可变快照与结果清单，支持查询、收集、取消、重连和防重复提交。
4. Claude/v3 能力与认证检查，以及把具体编码任务自动交给 Claude 的 prepare 入口；真实后端调用以实际支持的接口、账户与预算为准。
5. configs/work_execution.cpu.yaml：可实际运行的 CPU 验收配置；以及 work_execution.v3.example.yaml 模板，不能以未填写模板假称可执行。
6. examples/work_spec_mdp.json：与真实 schema 一致的 CPU 示例，可直接校验和运行。
7. docs/WORK_COMMANDS.md：从本机实际运行验证过的命令整理出来，逐项标出验证层级、输出路径、退出码及未执行项。
8. 必要测试与 WORK_INTEGRATION_STATUS.md；不提供空函数或只打印成功的替代实现。

## 4. 外部规格与模型配置边界

### 4.1 独立配置

为 experiment 命令建立只负责实验的配置路径，或复用真正等价的已有路径。不要为执行一个已知实验而加载/探测旧前端 GPT 模型、请求 OPENAI_API_KEY、要求前端 pricing，或调用 make_research_spec。

Work 当前使用的模型从用户实际界面选择及可取得元数据记录。无法取得实际模型、token、模式或费用时写 unknown/not_available；不要补造 Response ID、ModelBinding、API usage。旧 API 模式继续保留，不能因支持 Work 而弱化旧模式的验证。

预算至少区分：Work 平台用量（本 runner 不控制）、Claude/v3 agent 用量、服务器计算资源。原 llm YAML 不控制 Work 的模型和平台额度。继承适用的既有授权，但不把此前某次 $20 campaign 当成自动续费的无限预算。

### 4.2 规格输入

输入必须包含或关联：研究任务/候选版本、protocol ID/version/hash、study_stage、已确定的 research_branch、假设与可证伪条件、数据/划分、基线、评价指标、代码/任务包快照、资源与停止标准。理论分支继续保存假设、命题、证明义务和反例检查范围。

复用 ResearchSpec 的字段与验证。可添加带版本的 Work 导入 envelope，或者明确扩展来源类型；具体选择以最小兼容改动为准。外部文献报告、Work 推断、真实工具观察分开存储；导入本身不把主张设成 verified。

关键字段发生变化时生成新的候选/协议版本；旧证据不自动支持新版本。快照哈希由代码计算。拒绝错误引用、缺失任务包和未经支持的配置，不以生成 schema 样例冒充有效研究规格。

## 5. CLI 目标契约

建议新增命令组 pra experiment；如果已有等价实现可以复用并在文档中说明。以下为待实现契约，不是本文件声称已经可执行的现有命令。

| 子命令 | 必需能力 |
| --- | --- |
| validate --spec PATH --config PATH | 结构、资源、快照与能力检查；不默认发起模型请求 |
| submit --spec PATH --config PATH --job-id ID --request-id ID | 原子记录任务后启动，快速返回 job_id 与状态 |
| status --job-id ID | 返回进度、状态、耗时、资源、错误及下一步 |
| collect --job-id ID | 从已有产物生成/读取结果包；不重新执行实验或模型调用 |
| cancel --job-id ID | 停止本任务管理的进程/作业，保留已有证据，重复取消安全 |
| prepare --request PATH --config PATH | 在具体研究规格下自动调用 Claude 准备任务包并收回检查结果；必须实现，实际模型调用按第 7 节的条件验证 |

现有 v3 resume 可由内部恢复逻辑调用；需要用户可见恢复入口时可增加 resume 子命令。恢复实验与取回结果必须区分：不能仅为再次读取结果而启动新进程。

机器输出使用结构化 JSON，日志进 stderr 或文件。错误包含 code、message、missing、retryable 与可执行的下一步；不要把所有情况归为 failed。查询和收集必须能在原前端 key 缺失时工作。

### 5.1 持久任务

- 用现有 SQLite 或一个独立小表存 job_id、request_id、规格哈希、代码/任务快照、状态、进程或调度器 ID、启动时间、deadline、日志及产物位置。
- 相同 request_id + 相同输入返回原 job；相同 request_id + 不同输入明确拒绝。并发重复提交也不得产生两份实验。
- job_id 及输出目录不可碰撞；task snapshot 不覆盖、不删除旧运行目录。任务外路径和未登记任务类型拒绝。
- 进程身份不能只靠一个可能复用的 PID；使用调度器作业 ID 或记录可核对的进程身份，恢复时先核对，再决定状态。
- 任务状态与临时断线区分；不确定时标 interrupted/unknown 并给核查方法，不能立即重跑。

### 5.2 独立运行与限制

优先复用服务器已有的合法作业机制；没有时实现最小监督进程。提交会话断开后，监督进程仍负责期限、资源和结束记录。裸 nohup 加一个 PID 不足以证明可靠恢复与预算约束。

监督应覆盖 prepare/v3/preflight/训练子进程，按已授权设备、并行度、重复次数与期限执行；取消/超时时只清理本任务的进程组或作业。不得依赖 Work 一直调用 status 才触发超时。

每个预算维度报告 enforcement=strict/best_effort/unavailable。若需要硬美元限制但后端只支持估计，应返回能力缺口；不声称 api_usd 字段会硬停账单。不自动提额或扩大设备范围。

## 6. Claude 和 v3 接入

1. 复用固定 v3 checkout；读取该版本 config schema、setup-task 和 harness 契约、CLI help。不要随意更新上游或猜测配置字段。
2. backend.agent.name 使用 claude；model/effort 采用用户明确选择且实际版本支持的配置，不从 Work 模型复制，不猜模型 ID。
3. 在将启动任务的同一账户、登录 shell、容器或原生环境中检查 claude --version、可执行文件和官方支持的认证状态。若当前版本支持，使用 claude auth status（只保留脱敏状态）。CLI 安装和认证状态分别报告。
4. 不把 .env 存在当作认证成功；不因没有 ANTHROPIC_API_KEY 就断言已有 Claude 登录无效。不得读取并展示缓存 token、密钥或完整环境。
5. 已登录不等于 v3 的非交互运行已通过。先检查实际命令/参数，再在明确的现有授权范围内做最小真实调用；未具备条件则交付完整代码和精确阻塞，标 not_run。
6. 先验证原生或容器路线的真实可行性；不要为“能跑”静默移除隔离或跳过权限。缺 Docker/LaTeX 不妨碍完成 CPU 接口，但影响的阶段应单独报告。
7. v3 hand-written 任务沿用正式契约；不手工生成 task_contract.json，不误入 contract-only 阶段。保留 doctor/dry-run/真实执行的区分。

## 7. 自动把任务交给 Claude

已有 task kit 可直接运行。新问题先由 Work 给出具体研究规格及代码验收条件，再由 Claude 准备任务包。

对首次 H-JEPA，不能把一段宽泛 idea 直接交给当前 mdp_policy materializer。需要固定可取得的基线来源、数据/小规模子集、代码接口、独立 evaluator、资源和明确比较协议；协议由 Work 形成，代码由 Claude 实现。条件不足时返回具体缺项。

为避免用户每轮手动给 Claude 复制 prompt，必须实现受控 prepare 入口，或复用具有同等能力的已验证命令：

- 输入指向本任务的编码要求文件、候选与协议版本、允许修改的项目路径、测试命令和资源上限。
- 使用安装版本支持的 Claude 非交互接口；官方 CLI 提供 claude -p 和结构化输出。运行前核对本机 help，不复制不兼容字段。
- subprocess 使用参数数组，指令通过 stdin 或任务文件传递；不要将任意用户/论文文本拼成 shell 命令。
- 使用任务工作目录或隔离工作树，明确允许的工具与路径；不使用跳过权限的参数来解决连接或非交互问题。
- 准备任务也返回 job_id，保存会话 ID、代码变更、检查结果和失败原因。正式实验训练由后续实验 runner/v3 启动，不能依赖 Claude 回答结束后某个未记录后台进程继续运行。
- 不用最近一次会话隐式续接并行任务；需要恢复时按持久记录的特定会话 ID 处理。若使用返回的累计成本，记录增量避免重复结算；估算成本不能冒充账单实际值。
- 通用任意 idea → task kit 转换不属于首版承诺。首版支持至少一个准备好的任务，并实现接受具体编码要求的 prepare 路径；真实调用未验证时标 not_run，不能以手动把 prompt 交给 Claude 冒充自动对接。

prepare 用于把一个具体实验变成可运行任务。进入正式 v3 investigation 后，代码改进和消融继续由 v3 内部 Claude 执行，不在外部再做一套重复的科研编码循环。

## 8. 结果交接

每个任务的可读结果摘要必须指向实际文件：

- job_id、candidate_revision_id、protocol ID/version/hash、task/code snapshot。
- execution_status、raw backend status、完成/缺失阶段、开始结束时间和退出信息。
- 每次运行的实际配置、数据版本/划分、种子、原始指标及评价器产物。
- 日志位置、必要错误片段、复现命令、产物哈希清单、资源与成本的可观察范围。
- 是否存在真实 v3 初稿、其路径及哈希；缺稿明确 not_generated。
- missing、warnings、next_action；缺少的数值保留缺失，不填 0。

collect 不直接判定科学 supported/refuted。Work 根据协议与证据作科学判断；执行状态、研究结论和文稿状态分别保存。进程完成/exit 0/PDF 编译都不能代替证据核验。

大权重留服务器；Work 默认读取摘要、指标表和指定日志片段，需要时访问对应图表/源数据。当前 Work 会话须实际能访问返回路径；只有目录字符串不能证明文件已被读取。

## 9. 验收顺序

### A. 确定性 CPU 验收（本次默认可做）

配置上限：1 个并行任务、至多 2 个 CPU 核、5 分钟、GPU=0；实验 runner 不调用外部模型。这里的限制不宣称 Claude 开发会话或 Work 平台自身免费。

使用现有 MDP 计算/评价器实现真实计算，不能用打印固定答案的 fixture。先验证基础接口，再检查下列实际风险：

1. 原前端 API key 缺失且前端 provider 被禁止调用时，validate/submit/status/collect 可运行；无 clarify/read_paper/make_research_spec/json_repair 等原前端事件。
2. 缺任务包/错协议/未支持配置被明确拒绝，不静默降级。
3. 重复和并发提交只产生一个真实任务；相同标识不同输入被拒绝。
4. 提交端退出后任务仍可查询；停止查询也能在期限内终止超时任务；取消只影响自有进程。
5. 任务快照不会被下次 materialize 删除；恢复遇到改变的快照明确拒绝或创建新版本。
6. collect 可重复运行且不触发模型、重跑或重复记账；失败/缺失指标保持真实含义。
7. 必要的旧配置/数据兼容性检查通过，原有离线能力不被破坏。

保存命令、退出码、原始输出和产物路径。只读检查、dry-run、fixture、真实 CPU 计算分别标注。

### B. Claude/v3 真实接入验收（条件具备时做）

先验证 prepare 能把一份范围明确的小编码任务交给真实 Claude 并读回文件与检查结果，再用固定任务做一次最小、有限的真实 Claude/v3 investigation。要求认证可用、参数已验证、具有适用的明确预算。已有授权足够时继续；否则准确列出缺少项，不把 A 或 dry-run 写成 B 已完成。

### C. 用户桌面 Work 端验收（只能在实际会话验证）

在将承担科研的那个 Work 会话中，确认服务器 hostname、项目绝对路径，并在专用验收目录写入/读回一个小文件；随后由该会话提交 A 的任务并实际读取指标。不能由服务器 Claude 或另一个 Codex 会话替用户伪造这项已通过。

如果 Work 只有云端环境或无法访问目标 shell，连接问题保持 blocked，并给基于实际界面的下一步；不要把“已有 SSH 配置”当作当前 Work 已获得访问权限。

### D. H-JEPA 科研运行

只有 Work 完成具体候选和协议、Claude 准备对应 task kit 后再进行。CPU 对接通过不代表 H-JEPA 基线或 GPU 实验已完成。

## 10. 最终报告与停止点

交付实际修改、必要测试结果、docs/WORK_COMMANDS.md、示例配置/规格、WORK_INTEGRATION_STATUS.md。每一层写 implemented/verified/not_run/blocked，并说明证据。

如果缺连接、凭据、数据或后端能力，完成其他可做部分后集中报告缺项。不要在没有问题时停在“是否继续实现”；不要凭空生成科研指标、实验图或成功状态。

已结束的 Work 任务不会因为一个服务器任务完成就被此 CLI 自动唤醒。服务器保存结果、当前活动会话查询、重开后恢复均可实现；跨会话主动触发下一轮需要单独确认产品支持并接入。本次不承诺全天无人值守研究。

## 11. 核对来源

- 原计划：https://github.com/Peiran225/auto-research/blob/GPT-version/CODEX_IMPLEMENTATION_PLAN.md
- 当前 CLI：https://github.com/Peiran225/auto-research/blob/GPT-version/src/personal_research_agent/cli.py
- 当前配置：https://github.com/Peiran225/auto-research/blob/GPT-version/src/personal_research_agent/config.py
- 当前数据对象：https://github.com/Peiran225/auto-research/blob/GPT-version/src/personal_research_agent/models.py
- 当前 v3 后端：https://github.com/Peiran225/auto-research/blob/GPT-version/src/personal_research_agent/backends/ai_scientist_v3.py
- 桌面 SSH：https://learn.chatgpt.com/docs/remote-connections#connect-to-an-ssh-host
- Claude CLI：https://code.claude.com/docs/en/cli-reference
- Claude 非交互调用：https://code.claude.com/docs/en/headless

这些来源支持接口核对，不表示本机已经通过真实接入。执行时保留实际版本与命令证据。
