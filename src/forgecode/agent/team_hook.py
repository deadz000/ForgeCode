"""TeamHook Protocol + TeammateContext + IncomingMessage。

agent 包不直接 import team 包（避免循环）；Team 行为通过 Protocol 与
contextvars 注入。spawn 时用 with_teammate_context 包裹 run_to_completion，
run 循环内通过 teammate_context_from_ctx() 读取。
"""

from __future__ import annotations

import contextvars
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Protocol

# 当前执行上下文中的 TeammateContext（None 表示非队员）
_teammate_ctx: contextvars.ContextVar[Any] = contextvars.ContextVar("forgecode_teammate", default=None)


@dataclass
class IncomingMessage:
    """队员收到的邮箱消息摘要（轻量，独立于 team.mailbox.Message）。"""

    from_: str
    type: str
    summary: str
    content: str = ""
    payload: dict[str, Any] | None = None
    timestamp: int = 0


@dataclass
class TeammateContext:
    """队员运行上下文：由 team 包在 spawn 时构造并注入。

    backend_type 为字符串枚举值（"tmux"/"iterm2"/"in-process"），
    避免 agent 包反向依赖 team 包造成循环导入。
    """

    team_name: str
    member_name: str
    agent_id: str
    backend_type: str
    # 邮箱读写闭包（由 team 包注入，屏蔽 mailbox 类型）
    read_unread: Callable[[], Awaitable[tuple[list[int], list[IncomingMessage]]]]
    mark_read: Callable[[list[int]], Awaitable[None]]
    send_message: Callable[..., Awaitable[None]] | None = None
    mailbox_dir: str = ""


@dataclass
class TeamSpawnRequest:
    """Agent 工具 team_name 分支传给 TeamHook 的参数。"""

    team_name: str
    member_name: str
    agent_type: str
    model: str
    prompt: str
    plan_mode_required: bool = False
    sub_agent: Any = None  # in-process 用：预构造的子 Agent
    conv: Any = None  # in-process 用：子对话


class TeamHook(Protocol):
    """Agent 工具委托的 Team 行为接口（避免 agent 反向依赖 team）。"""

    async def spawn_teammate(self, req: TeamSpawnRequest) -> str: ...
    def is_teammate_context(self, ctx: Any) -> tuple[str, str, bool]: ...


@contextmanager
def with_teammate_context(tc: TeammateContext | None) -> Iterator[None]:
    """在上下文内注入 TeammateContext。"""
    if tc is None:
        yield
        return
    token = _teammate_ctx.set(tc)
    try:
        yield
    finally:
        _teammate_ctx.reset(token)


def teammate_context_from_ctx() -> TeammateContext | None:
    """取回当前 TeammateContext；非队员上下文返回 None。"""
    value = _teammate_ctx.get()
    return value if isinstance(value, TeammateContext) else None


__all__ = [
    "IncomingMessage",
    "TeamHook",
    "TeamSpawnRequest",
    "TeammateContext",
    "teammate_context_from_ctx",
    "with_teammate_context",
]
