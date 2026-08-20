# TUI 交互优化

本轮（2026-08）系统性 UI 交互优化记录：改动清单、新组件、验收要点。

## 改动清单（对应提交）

| 编号 | 内容 | 提交 |
|---|---|---|
| A1 | 通用方向键选择题组件（`tui/choices.py`），审批从原生 `input()` 迁移 | `9e23c4c` |
| A2 | 计时反馈改造：回合开始 `Thinking...`、轮次 `▶ 第N轮`，删除 `\r` 原地刷新与状态栏死代码 | `bcba604` |
| A3 | 流式输出实时 Markdown 渲染（节流 + 未闭合代码块截断兜底） | `719a12c` |
| — | 修复工具执行中 Ctrl+C 导致会话永久不可用（对话结构闭合兜底） | `7f879d3` |
| A4 | 终端 resize 适配（边框惰性取宽；曾误用不存在的 `Application.on_resize` 导致启动崩溃，已修复 `5ff5672`） | `1da026c` + `5ff5672` |
| A5 | 工具调用默认折叠 + `/tool` 命令展开详情（`_tool_log` 上限 200 条） | `7dc2ac3` |
| A6 | 斜杠命令参数补全（`Command.argument_completer`） | `78d604c` |
| A7 | `/help` 按分类分组（对话/界面/信息/技能） | `c62396b` |
| A8 | 状态栏新增 session id + 缩写 cwd | `9eb9eea` |
| A9 | `/resume` 方向键选择 + 左右键翻页（`ChoiceQuestion` 分页） | 最新 |
| A10 | Ctrl+C 退出提示中文化，逻辑抽为 `_ctrl_c_handler` | `11a0128` |

## 新组件与命令

- `tui/choices.py`：`ChoiceQuestion` / `ask_choice`，单选/多选、`page_size` 分页（←/→ 翻页）、Esc 取消。纯函数 `render_choice_lines` / `move_cursor` / `toggle_index` 可单测。
- `/tool`：`/tool`（最近 10 条）`/tool <序号>`（展开完整参数与结果）`/tool last` `/tool clear`。
- `Command.argument_completer`：`/worktree` `/team` `/tool` `/thinking` 的参数补全。

## 验收要点（真实终端冒烟）

1. 触发审批（如 ASK 模式下执行写操作）：↑/↓ 选择 + Enter 确认，Esc 取消，选项高亮正确。
2. `/resume`：↑/↓ 移动、←/→ 翻页（>10 个会话时）、Enter 恢复、Esc 取消。
3. 工具执行后结果只显示一行摘要 + 耗时 + `/tool 1 展开`；`/tool 1` 打印完整结果。
4. 流式回答期间即有 Markdown 排版（代码块/列表），结束后无排版跳变；超长回答不卡顿。
5. 调整终端窗口大小，输入盒边框与状态栏随宽度实时重绘。
6. 输入 `/worktree ` 后按 Tab 出现子命令候选；`/help` 分组展示。
7. 回合开始时显示 `Thinking...`，多轮任务中显示 `▶ 第2轮` 等；工具执行中 Ctrl+C 后会话仍可继续对话（无 API 报错）。
8. 状态栏显示 `[session前8位] 模式 │ 模型 │ cwd │ tokens │ 耗时`。

## 测试覆盖

新增/更新测试文件：`tests/test_tui_choices.py`、`tests/test_tui_app.py`、`tests/test_tui_complete.py`、`tests/test_tui_resume.py`、`tests/test_command_tool.py`、`tests/test_agent.py`（中断回归）、`tests/test_command_builtins.py`。

全量：`uv run pytest`（除 `test_mcp_manager.py` 3 个预存 Windows stderr 断言失败）。
