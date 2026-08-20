# ⚒ ForgeCode

**命令行 AI 编程助手（Coding Agent）** —— 在终端里与 LLM 协作：读懂代码、搜索、修改文件、执行命令，完成真实编程任务。

![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB) ![License](https://img.shields.io/badge/License-MIT-blue)

---

## 项目说明

ForgeCode 是一个运行在终端（TUI）中的多轮 AI 编程代理。你输入需求，它通过 **ReAct 循环**（思考 → 调用工具 → 观察结果）自主读写文件、搜索代码、执行命令，逐步完成任务；你随时可以批准/拒绝工具执行、切换权限模式、恢复历史会话。

## 背景

大模型已能理解和生成代码，但把「对话」变成「干活」需要一套可靠的工具执行与权限体系。ForgeCode 聚焦终端场景，提供：

- **可审计的工具调用**：每一次读写/执行都有权限判定与展示；
- **可信任的安全边界**：黑名单 → 沙箱 → 规则 → 模式 → 人在回路五层防御；
- **可延续的工作上下文**：上下文压缩、记忆、会话存档/恢复；
- **可扩展的工程化能力**：Hook 生命周期、Skill 技能包、SubAgent、Worktree 隔离、Team 协作、MCP 外部工具。

## 技术栈

| 层 | 技术 |
|---|---|
| 语言 | Python 3.11+ |
| 交互 | [prompt_toolkit](https://github.com/prompt-toolkit/python-prompt-toolkit)（输入/补全/选择器）+ [Rich](https://github.com/Textualize/rich)（Markdown/流式渲染） |
| LLM | OpenAI / Anthropic 协议，统一 `StreamEvent` 抽象 |
| 配置 | PyYAML（全局 + 项目两层合并） |
| 扩展 | MCP（stdio/http 外部工具）、git worktree 隔离 |

## 核心架构

```
main.py ── 依赖组装入口
   │
   ├─ agent/       ReAct 循环：流式调用 → 工具执行 → 结果回灌
   │                 （保序分批并发、权限判定、Hook、上下文压缩）
   ├─ tool/        6 个核心工具：read_file / write_file / edit_file /
   │                 bash / glob / grep（30s 超时保护）
   ├─ permission/  五层防御：黑名单 → 沙箱 → 规则引擎 → 模式兜底 → 人在回路
   ├─ hook/        11 个生命周期事件（Session/Tool/UserMessage/Compact…）
   ├─ compact/     两层上下文压缩（大结果落盘 + LLM 摘要）
   ├─ memory/      项目级 + 用户级两级记忆
   ├─ session/     JSONL 会话存档 + /resume 恢复
   ├─ skills/      Skill 技能包（内置/用户/项目三层 Catalog）
   ├─ subagent/    子 Agent 调度 + 后台任务管理
   ├─ worktree/    Git Worktree 文件系统隔离
   ├─ team/        多 Agent 网状协作（tmux/iterm2/in-process 后端）
   ├─ mcp/         MCP 外部工具注入
   └─ tui/         终端界面：输入盒、流式 Markdown、方向键选择器、
                    工具调用折叠、斜杠命令系统
```

**Agent 循环**（每轮）：上下文管理 → 流式生成 → 工具调用 → 权限判定 → 保序分批并发执行 → 结果回灌。

## 功能特性

- 💬 多协议 LLM 对话（OpenAI / Anthropic，5xx 自动重试）
- 🛠 6 个内置工具 + MCP / Skill / SubAgent 扩展工具
- 🔐 五层权限防御，人在回路可批准/拒绝/永久允许
- 🪝 Hook 生命周期（会话、工具、消息、压缩 11 类事件，可拦截）
- 🧠 上下文自动压缩 + 两级记忆
- 📦 会话存档与恢复（`/resume`，方向键选择 + 翻页）
- 🎯 Skill 技能包 / 子 Agent 任务 / Worktree 隔离
- 🤝 Team 多 Agent 协作 + Coordinator 模式
- 🖥 终端交互：流式 Markdown 渲染、工具调用折叠展开（`/tool`）、
  斜杠命令参数补全、终端 resize 自适应

## 快速开始

```bash
# 1. 安装依赖
uv sync --dev

# 2. 配置 LLM provider（首次运行无配置会进入交互向导）
#    或手动编辑 ~/.forgecode/forgecode.yaml / ./forgecode.yaml
#    provider 需包含 name/protocol/model/base_url/api_key

# 3. 启动
uv run forgecode [--provider <name>]
```

> ⚠️ 配置含 API Key：`forgecode.yaml` 与 `.forgecode/` 均已 gitignore，禁止提交。

## 常用命令

| 命令 | 说明 |
|---|---|
| `/help` | 分类查看可用命令 |
| `/plan` · `/do` | 计划模式：只读规划 → 批准执行 |
| `/permission` | 查看/切换权限模式（Shift+Tab 快速切换） |
| `/compact` | 手动压缩上下文 |
| `/resume` | 恢复历史会话（↑/↓ 选择，←/→ 翻页） |
| `/tool` | 查看/展开工具调用详情 |
| `/memory` · `/session` · `/status` | 查看记忆/会话/运行状态 |
| `/worktree` · `/team` · `/skill` | 管理隔离/协作/技能 |
| `/exit` | 退出（空闲时 Ctrl+C 两次） |

## 开发

```bash
uv run ruff check src/ tests/      # 代码检查
uv run ruff format src/ tests/     # 格式化（双引号 + 110 列）
uv run mypy --strict src/          # 类型检查
uv run pytest                      # 测试
```

架构细节见 [AGENTS.md](AGENTS.md)；各功能模块文档见 [`docs/`](docs/)。

## 许可证

MIT
