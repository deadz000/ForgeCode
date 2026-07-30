"""SessionRuntime：跨 Agent.run 调用持有的长生命周期状态容器。"""

from __future__ import annotations

from dataclasses import dataclass

from forgecode.compact.state import (
    CompactCircuitBreaker,
    ContentReplacementState,
    RecoveryState,
    SessionContext,
    new_session_context,
)


@dataclass
class SessionRuntime:
    """TUI 持有、每轮传给 Agent 的跨轮复用状态。

    compact 是逻辑层，对状态零持有、可重入。
    """

    replacement: ContentReplacementState
    recovery: RecoveryState
    auto_tracking: CompactCircuitBreaker
    session: SessionContext
    context_window: int = 200000
    # 上一次主对话路径 stream 真实 usage 之和；摘要请求不更新
    usage_anchor: int = 0
    # anchor 当时 conv.length()
    anchor_msg_len: int = 0
    # asyncio 单线程，无需显式锁


def new_runtime(workspace: str = ".") -> SessionRuntime:
    """构造默认 SessionRuntime（测试场景适用）。"""
    return SessionRuntime(
        replacement=ContentReplacementState(),
        recovery=RecoveryState(),
        auto_tracking=CompactCircuitBreaker(),
        session=new_session_context(workspace),
    )
