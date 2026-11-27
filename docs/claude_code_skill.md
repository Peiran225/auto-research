# auto-research

一个在 Claude Code 里运行的自动科研 agent：输入一句话 idea 和目标会议，按 9 步流程产出
排好序的研究方向、选定的 idea、实验代码与结果，以及一篇 LaTeX 论文。

## 怎么用

在 Claude Code 里打开本仓库，然后在输入框里输入：

```
/auto-research new "MDP 里不同形式的不确定性是否等价" --venue neurips
```

- `--venue`：`neurips` / `icml` / `iclr` / `corl` / `icra` / `iros` / `rss`
- `--metric "<指标>"`：可选；不写的话第 3 步给出候选，第 8 步再定

中途会在三个检查点停下来让你决定：

| 检查点 | 时机 | 你要做的 |
|---|---|---|
| A | 拆关键词并打分后 | 确认或修改关键词和分数 |
| B | 研究方向排序稳定后 | 选一个方向（或改权重重排） |
| C | 写好 idea 方案后 | 批准实验计划和计算预算 |

其他命令：

| 命令 | 作用 |
|---|---|
| `/auto-research status <项目名>` | 看进度、检查点决定和当前排名 |
| `/auto-research resume <项目名>` | 中断后从断点继续 |
| `/auto-research profile` | 从 Google Scholar 重新生成你的背景画像 |

## 9 步流程与输出文件

每个 idea 的结果都在 `research/projects/<项目名>/` 下：

| 步骤 | 内容 | 输出 |
|---|---|---|
| 0 | 背景画像（Google Scholar，只用最近 3 年的论文打分） | `research/profile/profile.json` |
| 1–2 | 拆关键词，按和你背景的关联度、对 idea 的重要度打分；关联低但重要的补背景 | `01_keywords.json`、`02_background_gaps.md` |
| 3 | 领域核心问题、常用指标和 benchmark | `03_field_core.md` |
| 4 | 找 related work，每篇标注对应的关键词 | `papers.jsonl`、`04_related_work.md` |
| 5 | 每篇和你的关系、还没做什么、做了有没有意义；再补一批交叉论文 | `papers.jsonl` 中的分析字段、`05_analysis.md` |
| 6 | 候选方向的创新度、难度、影响力打分 | `06_candidates.json` |
| 7 | 排序迭代：查"前 3 名是否已有人做过"→ 重新打分，直到排序稳定 | `07_ranking_log.md` |
| 8 | 定下第一个 work 的 idea | `08_idea.md` |
| 9 | 写代码跑实验 → 写 LaTeX → 模拟审稿，最多改 3 轮 | `09_experiments/`、`09_paper/`、`09_review_log.md` |

## 仓库结构

| 路径 | 作用 |
|---|---|
| `.claude/skills/auto-research/SKILL.md` | 总指挥：定义 `/auto-research` 命令、流程顺序、检查点、两个迭代循环 |
| `.claude/skills/auto-research/rubrics/` | 1–5 分打分标准、各会议的审稿要求 |
| `.claude/skills/auto-research/templates/` | 每一步输出文件的格式样例 |
| `.claude/agents/ar-*.md` | 9 个子 agent，每个负责一步 |
| `research/profile/` | `scholar.json`（Scholar 链接、`recent_years`）、`my_papers.md`（可选补充说明）、生成的画像 |
| `research/tools/validate_project.py` | 每步结束后检查输出格式、引用是否已核实、正文数字是否来自实验结果 |
| `research/tools/rank_stability.py` | 判断第 7 步排序是否稳定（前 3 名不变且创新度无 ≥1 的变化，最多 4 轮） |
| `research/tools/make_results_macros.py` | 实验汇总 CSV → 论文用的 LaTeX 宏 |
| `research/tools/scholar_fetch.py` | 拉取 Google Scholar 主页（或保存的 HTML / BibTeX 导出），附 arXiv 摘要 |
| `research/projects/` | 每个 idea 一个子目录 |

想调整 agent 的行为（打分标准、检索论文数量、审稿要求等），直接编辑对应的 markdown 文件即可。

## 注意

- **网络**：云端会话的环境需要允许 `scholar.google.com`、`arxiv.org`、`export.arxiv.org`。
- **Scholar 验证码**：如果 Scholar 拦截，把主页另存为 HTML，或在 Scholar 上全选论文导出 BibTeX，然后运行
  `python research/tools/scholar_fetch.py --html <文件>` 或 `--bibtex <文件>`。
- **算力**：云端容器为 4 核 CPU、无 GPU，实验会设计成小规模；需要真机的机器人方向风险很高。
- **防编造**：论文只引用打开核对过的文献；正文实验数字只能来自结果文件；不被实验支持的论点写进局限性。
- **保存结果**：跑完后提交并推送 `research/projects/<项目名>/`，云端容器回收后未提交的内容会丢失。

## 测试

```bash
python -m pytest -q
```

工具只用 Python 标准库；测试需要 `pytest`（见 `requirements-dev.txt`）。
