"""SessionRuntime：跨 Agent.run 调用持有的长生命周期状态容器。"""

from __future__ import annotations

from dataclasses import dataclass, field

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
    # Hook 注入的待装配 reminder（本轮取出后清空）
    pending_reminders: list[str] = field(default_factory=list)
    # Hook 引擎（由 App 注入，供 emit 与 only_once 重置）
    hook_engine: object | None = None
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


def append_reminders(self: SessionRuntime, prompts: list[str]) -> None:
    """追加待注入的 hook prompt 到队列。"""
    self.pending_reminders.extend(prompts)


def take_reminders(self: SessionRuntime) -> list[str]:
    """取出并清空待注入队列。"""
    out = list(self.pending_reminders)
    self.pending_reminders.clear()
    return out


def reset_for_new_session(self: SessionRuntime, ses_ctx: SessionContext) -> None:
    """原子重置 compact 子状态与计数器，将 session 指向新上下文。

    注意：context_window 保留不变；writer 与 conv 重建由调用方负责。
    同时清空 pending_reminders 与 hook 引擎的 only_once 集合。
    """
    self.replacement = ContentReplacementState()
    self.recovery = RecoveryState()
    self.auto_tracking = CompactCircuitBreaker()
    self.session = ses_ctx
    self.usage_anchor = 0
    self.anchor_msg_len = 0
    self.turn_count = 0
    self.pending_reminders.clear()
    if self.hook_engine is not None:
        self.hook_engine.reset_for_new_session()
    if self.active_skills is not None:
        self.active_skills.clear()


# 将函数绑定为 SessionRuntime 的方法
SessionRuntime.append_reminders = append_reminders  # type: ignore[attr-defined]
SessionRuntime.take_reminders = take_reminders  # type: ignore[attr-defined]
SessionRuntime.reset_for_new_session = reset_for_new_session  # type: ignore[attr-defined]
