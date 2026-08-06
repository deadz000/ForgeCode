"""SubAgent 的 run_to_completion：复用主 run 循环，返回最终文本。

通过模块函数绑定到 Agent 上（见 agent/__init__.py 末尾）。
"""

from __future__ import annotations

import asyncio
import contextvars
from typing import Any

from forgecode.conversation.history import Conversation
from forgecode.permission import Mode, Outcome

# 嵌套阻断上下文标记：进入子 Agent 循环期间置 True，
# Agent 工具入口据此拦截「子 Agent 再启动 Agent」（替代文档的 QuerySource）。
IN_SUBAGENT: contextvars.ContextVar[bool] = contextvars.ContextVar("forgecode_in_subagent", default=False)


class MaxTurnsReached(Exception):  # noqa: N818 — 文档 API 命名（spec F9）
    """子 Agent 触达 max_turns 时抛出的终止异常。"""

    def __init__(self, final_text: str = "") -> None:
        super().__init__("subagent reached max turns")
        self.final_text = final_text


async def run_to_completion(
    self: Any,  # Agent；绑定为方法，循环导入故用 Any
    conv: Conversation,
    task: str,
    events: asyncio.Queue[Any] | None = None,
) -> str:
    """执行子 Agent「跑到底」循环，返回最后一条 assistant 文本。

    复用 ``self.run`` 的全部逻辑（ReAct / 权限 / hook / 上下文管理），区别：
    - 内部消费事件，不 yield 给调用方；最终返回 final_text
    - max_turns 由 ``self.max_turns`` 决定（0 用全局 MAX_ITERATIONS）
    - 可选 events 队列转发内部事件（TaskManager / TUI 据此聚合）
    - 触达 max_turns 时抛 ``MaxTurnsReached``
    - 进入循环期间置 IN_SUBAGENT 上下文标记（嵌套阻断）
    """
    from forgecode.agent import NOTICE_MAX_ITER

    token = IN_SUBAGENT.set(True)
    try:
        if task:
            conv.add_user(task)

        mode = self.permission_mode or Mode.DEFAULT
        cancel = asyncio.Event()
        final_text = ""
        max_turns_hit = False

        async for ev in self.run(conv, mode, cancel):
            if events is not None:
                _put(events, ev)
            if ev.approval is not None:
                await _resolve_approval(self, ev.approval)
            if ev.text:
                final_text += ev.text
            if ev.notice == NOTICE_MAX_ITER:
                max_turns_hit = True
            if ev.err is not None:
                raise ev.err
            if ev.done:
                break

        text = _last_assistant_text(conv) or final_text
        if max_turns_hit:
            raise MaxTurnsReached(text)
        return text
    finally:
        IN_SUBAGENT.reset(token)


def _last_assistant_text(conv: Conversation) -> str:
    """返回最后一条纯文本 assistant 消息内容；无则空串。"""
    for m in reversed(conv.messages):
        if m.role == "assistant" and m.content and not m.tool_calls:
            return m.content
    return ""


async def _resolve_approval(self: Any, req: Any) -> None:
    """消费子 Agent 内部产出的 Approval 事件，避免 await respond 死锁。"""
    if self.approval_upgrader is not None:
        outcome, ok = await self.approval_upgrader(req)
        if ok:
            req.respond.set_result(outcome)
            return
    req.respond.set_result(Outcome.DENY_ONCE)


def _put(events: asyncio.Queue[Any], ev: Any) -> None:
    try:
        events.put_nowait(ev)
    except asyncio.QueueFull:
        pass
