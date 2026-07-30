"""补充消息注入机制：system-reminder 标签包裹 + 规划模式按轮次注入。"""

from __future__ import annotations


def system_reminder(body: str) -> str:
    """将 body 包裹在 <system-reminder> 标签中。

    标签语义让模型理解这是系统补充上下文而非用户提问——不针对它直接回复。
    """
    return f"<system-reminder>\n{body}\n</system-reminder>"


# ── 规划模式提醒常量 ───────────────────────────────

_PLAN_REMINDER_FULL = (
    "你当前处于**计划模式（Plan Mode）**。\n"
    "- 你只能使用只读工具（read_file、glob、grep）来调研代码库。\n"
    "- 不允许写文件、编辑文件或执行 shell 命令。\n"
    "- 请产出一个清晰、分步的执行计划，然后停下来等待用户审批。\n"
    "- 用户用 /do 批准后，你才能开始实际执行（写文件/编辑/运行命令）。\n"
    "- 计划应包含：步骤编号、每步要做什么、涉及哪些文件、预期结果。"
)

_PLAN_REMINDER_CONCISE = (
    "仍在计划模式中——仅可用只读工具（read_file、glob、grep），继续调研并完善计划，等待 /do 批准后执行。"
)


def plan_reminder(full: bool) -> str:
    """返回包裹好标签的规划模式提醒。

    full=True  → 完整版（首轮 + 每 N 轮重复）
    full=False → 精简版（其余轮次）
    """
    body = _PLAN_REMINDER_FULL if full else _PLAN_REMINDER_CONCISE
    return system_reminder(body)


# ── /do 执行指令 ────────────────────────────────────

EXECUTE_DIRECTIVE = "请按上面的计划开始执行。"
