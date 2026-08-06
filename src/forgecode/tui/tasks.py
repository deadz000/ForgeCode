"""后台任务通知：<task-notification> / <team-update> 渲染与消费。"""

from __future__ import annotations

from typing import Any

_CONTENT_LIMIT: int = 8000


def build_task_notification(bt: Any) -> str:
    """把后台任务终态渲染为注入主对话 reminder 区的通知块（spec F19/N7）。"""
    if bt.status.name == "FAILED" and bt.err is not None:
        result_line = f"Error: {bt.err}"
    else:
        result_line = bt.result
    return (
        "<task-notification>\n"
        f'Task {bt.id} (name="{bt.name}"): {bt.status.name.lower()}\n'
        f"Result: {result_line}\n"
        "</task-notification>"
    )


def build_team_update_reminder(msgs: list[Any]) -> str:
    """把队员发来的 Lead 消息渲染为 <team-update> reminder（F41a）。"""
    lines: list[str] = ["队员发来新消息:"]
    for m in msgs:
        content = m.content or ""
        if len(content) > _CONTENT_LIMIT:
            content = content[:_CONTENT_LIMIT] + "\n…(截断)"
        lines.append(f"[team={m.team_name} 来自 {m.from_} type={m.type}]: {m.summary}")
        if content:
            lines.append(content)
    return "\n".join(lines)
