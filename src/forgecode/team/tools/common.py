"""Team 工具共享逻辑：确定当前 Team 上下文。"""

from __future__ import annotations

from typing import Any

from forgecode.agent.team_hook import teammate_context_from_ctx


def current_team_name(mgr: Any, explicit: str = "") -> str | None:
    """解析当前调用者所属 Team。

    优先：显式参数 → TeammateContext.team_name → Manager.active_team_name。
    """
    if explicit:
        return explicit
    tc = teammate_context_from_ctx()
    if tc is not None:
        return tc.team_name
    return getattr(mgr, "active_team_name", None)


def is_lead_call() -> bool:
    """当前调用是否为 Lead（无 TeammateContext）。"""
    return teammate_context_from_ctx() is None
