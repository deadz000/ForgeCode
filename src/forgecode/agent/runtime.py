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
from forgecode.skills.active import ActiveSkills


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
    # 记忆更新：从首次 run 开始累计的自然完成轮数
    turn_count: int = 0
    # 已激活 Skill 列表
    active_skills: ActiveSkills | None = None
    # asyncio 单线程，无需显式锁


def new_runtime(workspace: str = ".") -> SessionRuntime:
    """构造默认 SessionRuntime（测试场景适用）。"""
    return SessionRuntime(
        replacement=ContentReplacementState(),
        recovery=RecoveryState(),
        auto_tracking=CompactCircuitBreaker(),
        session=new_session_context(workspace),
        active_skills=ActiveSkills(),
    )


def reset_for_new_session(self: SessionRuntime, ses_ctx: SessionContext) -> None:
    """原子重置 compact 子状态与计数器，将 session 指向新上下文。

    注意：context_window 保留不变；writer 与 conv 重建由调用方负责。
    """
    self.replacement = ContentReplacementState()
    self.recovery = RecoveryState()
    self.auto_tracking = CompactCircuitBreaker()
    self.session = ses_ctx
    self.usage_anchor = 0
    self.anchor_msg_len = 0
    self.turn_count = 0
    if self.active_skills is not None:
        self.active_skills.clear()


# 将函数绑定为 SessionRuntime 的方法
SessionRuntime.reset_for_new_session = reset_for_new_session  # type: ignore[attr-defined]
