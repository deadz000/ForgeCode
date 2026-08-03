"""后台任务通知：<task-notification> 渲染与消费。"""

from __future__ import annotations

from typing import Any


def build_task_notification(bt: Any) -> str:
    """把后台任务终态渲染为注入主对话 reminder 区的通知块（spec F19/N7）。"""
    if bt.status.name == "FAILED" and bt.err is not None:
        result_line = f"Error: {bt.err}"
    else:
        result_line = bt.result
    return (
        "<task-notification>\n"
        f"Task {bt.id} (name=\"{bt.name}\"): {bt.status.name.lower()}\n"
        f"Result: {result_line}\n"
        "</task-notification>"
    )
