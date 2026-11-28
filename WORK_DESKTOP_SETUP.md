# 从这里开始：Work 研究、Claude 写代码、学校服务器运行

版本：1.0 · 2026-11-26（America/Chicago）

本包提供计划与实施指令，尚未改动你的 GitHub 仓库，也没有连接或运行学校服务器。新实验命令需要 Claude 实现后才能使用。

## 1. 包里五个文件的用途

| 文件 | 谁读、做什么 |
| --- | --- |
| WORK_RESEARCH_PLAN.md | Work 的长期科研执行规则：研究、候选、证据、实验交接与结果分析 |
| CLAUDE_IMPLEMENTATION_TASK.md | Claude Code 的一次性开发任务：独立实验入口、后台执行、认证与验收 |
| CLAUDE_START_PROMPT.txt | 第一次交给服务器 Claude 的启动指令 |
| WORK_START_PROMPT.txt | 改造完成后，交给桌面 Work 开始科研的指令 |
| WORK_DESKTOP_SETUP.md | 本操作说明 |

把这些文件放到服务器 `~/auto-research` 项目根目录。可以使用已经连上服务器的 VS Code 完成这一次文件传递。如果同名文件已有新改动，让 Claude 比较合并，不覆盖掉用户工作。

之后有两条可并行进行的准备线：Claude 在服务器完成软件改造；你在桌面应用完成账户与 SSH 连接。最后在实际 Work 会话中验收。

## 2. 在已有 VS Code 服务器终端启动 Claude 改造

先进入项目，检查当前位置和已有 CLI：

```bash
cd ~/auto-research
hostname
pwd
git branch --show-current
git status --short
claude --version
```

已经能正常使用 Claude Code 时，直接启动：

```bash
claude
```

把 CLAUDE_START_PROMPT.txt 的完整内容粘贴进去。它会要求 Claude 读取完整实施任务、完成实际代码和 CPU 验收，并输出实测命令。不要把旧计划里“从 M0 开始实现全部 Agent”的启动段再粘贴一次。

Claude 如果缺认证，按当前 CLI 的登录提示操作。官方支持 `claude auth status` 查看状态；具体以本机版本的 help 为准。不要把密钥或登录缓存发到聊天里。首次人工登录不妨碍后面用受支持的非交互接口自动执行任务。[C1]

Claude 的最终交付应至少包含：

- 可直接运行的实验命令和配置。
- `docs/WORK_COMMANDS.md`，列出实际验证过的调用。
- `WORK_INTEGRATION_STATUS.md`，区分代码完成、CPU 运行、真实 Claude/v3 运行、桌面 Work 接入。
- 对 H-JEPA 尚需的基线、数据或协议，列出具体缺项。

## 3. 连接桌面应用到学校服务器

### 3.1 复用已有 SSH

Mac 连接学校 VPN，复用 VS Code 正在使用的 SSH Host 别名。桌面内置远程项目通过 Mac 的 `~/.ssh/config` 识别具体 Host。先在 Mac 终端验证同一别名能登录；不要另建第二套服务器账号。[O1]

### 3.2 内置 SSH 路线所需组件

官方内置 SSH 远程项目要求在服务器安装并认证 Codex，并且登录 shell 的 PATH 能找到它。它是远程代理运行环境，不改变“代码由 Claude 编写”的分工，也不是对模型用量免费的承诺。[O1]

在服务器检查：

```bash
command -v codex
codex --version
codex login status
```

如果尚未安装，官方 Linux 安装方式为：[O2]

```bash
curl -fsSL https://chatgpt.com/codex/install.sh | sh
```

按安装器提示设置 PATH，重新打开服务器终端后验证。无需在已经安装的环境重复安装。

如果尚未登录，可使用官方无浏览器设备登录方式：[O3]

```bash
codex login --device-auth
```

在 Mac 浏览器打开提示的网址，登录你的 ChatGPT 账户并输入一次性代码。设备码方式可能需要在个人安全设置或工作区权限中启用。完成后用 `codex login status` 验证。这里使用的是连接环境的账户认证，不是重新配置原 Python Agent 的 OpenAI API key。

### 3.3 在桌面添加主机和项目

桌面应用：Settings → Connections → 添加/启用 SSH 主机 → 选择服务器项目文件夹。完整路径以服务器里 `cd ~/auto-research` 后 `pwd` 的输出为准。[O1]

选择 ChatGPT → Work 开展科研。若连接管理或项目开发显示在 Codex 视图，可在那里完成连接检查；不能推断另一个 Work 会话自动继承同样的文件系统、shell 或会话状态。[O4]

## 4. 在真正用于科研的 Work 会话做连接验收

让该会话：

1. 报告其当前可用的执行环境；通过工具实际取得服务器 hostname、用户名和项目绝对路径。
2. 读取项目根目录的 WORK_RESEARCH_PLAN.md 和 Claude 交付的 docs/WORK_COMMANDS.md。
3. 在项目专用验收子目录写入一个小文件，再实际读回内容。保留主机、路径和检查输出。

允许通过已连接的远程项目运行命令，或在具备本机命令工具的 Work 会话中通过已经可用的 SSH 执行同一检查。普通 SSH 命令本身不要求服务器安装 Codex；服务器 Codex 要求来自桌面内置远程项目路线。

如果当前 Work 只能看到云端容器，或者只有 GitHub 阅读能力，连接验收未通过。先根据实际工具/界面修正执行环境；不要假称有服务器访问权限，也不要用另一段 Codex 会话的成功替代本项验证。

## 5. 第一次闭环验收

让 Work 按 docs/WORK_COMMANDS.md 调用已实现的 CPU 小实验：提交 → 查询 → 读取真实指标和日志 → 简短分析。默认验收任务不使用 GPU、不在实验 runner 内调用外部模型。

确认：

- 指标来自实际计算文件。
- 原前端 Q1–Q5 API 没有重新执行。
- 同一任务重复查询不会重新运行。
- 保存了任务编号、协议/代码版本、结果位置及检查点。

这证明机械交接可用。真实 Claude/v3 调用需要再做一轮有限的真实后端检查；只通过 dry-run 或 CPU 基线检查不能称为真实 v3 已接通。

## 6. 开始真实研究

在同一个已通过连接检查的 Work 会话中，粘贴 WORK_START_PROMPT.txt。开始时查看并选择你实际可用、希望用于科研的模型/模式；YAML 不能替你更改桌面 Work 的模型。不要凭名字或 reasoning effort 猜测 Pro 模式是否启用。

运行分成：

1. Work 按 Q1–Q5 检索、阅读、比较候选，形成具体可证伪假设和实验协议。
2. 需要新实验代码时，Work 写入编码要求；通过已实现的 prepare 命令调用 Claude，或使用已验证的同等命令入口。该入口属于本包要求的实施内容，未通过真实调用验证前，不算整个过程已自动接通。
3. Claude 准备一个真实可运行的任务包；正式研究由 v3 使用 Claude 执行。
4. Work 取回实际结果，审计并决定继续、修改或停止。

当前 mdp_policy 任务包只是连接/机制验收示例，不能当作 H-JEPA 实验证据。H-JEPA 必须有对应基线、数据、评价器和协议；其所需资源通过小规模测量后确定。

对长任务，服务器负责独立运行和保留结果。活动中的 Work 可以查询并继续分析；已结束的 Work 任务不会仅凭 SSH 自动被唤醒。需要跨会话、无人返回也自动继续时，另行验证平台调度/事件能力，不将此项混入首版验收。

## 官方与仓库来源

- [O1] https://learn.chatgpt.com/docs/remote-connections#connect-to-an-ssh-host
- [O2] https://learn.chatgpt.com/docs/codex/cli
- [O3] https://learn.chatgpt.com/docs/auth#login-on-headless-devices
- [O4] https://learn.chatgpt.com/docs/projects
- [C1] https://code.claude.com/docs/en/cli-reference
- [C2] https://code.claude.com/docs/en/headless
- 原计划：https://github.com/Peiran225/auto-research/blob/GPT-version/CODEX_IMPLEMENTATION_PLAN.md
- 当前后端：https://github.com/Peiran225/auto-research/blob/GPT-version/src/personal_research_agent/backends/ai_scientist_v3.py

本说明依据上述已查阅资料和当前仓库；账户入口、CLI 版本与服务器状态仍以实际检查为准。
