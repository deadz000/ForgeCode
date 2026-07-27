"""Agent ReAct 循环编排：多轮→工具调用→结果回灌→持续直到任务完成。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Coroutine
from dataclasses import dataclass
from enum import IntEnum
from typing import Any

from forgecode.conversation.history import (
    Conversation,
    ToolCall,
    ToolResult,
)
from forgecode.prompt import PLAN_MODE_REMINDER
from forgecode.providers import BaseProvider, Usage
from forgecode.tool import DEFAULT_TIMEOUT, Registry

# ── 常量 ──────────────────────────────────────────

MAX_ITERATIONS: int = 25
MAX_UNKNOWN_RUN: int = 3

NOTICE_MAX_ITER = "（已达最大迭代轮数 25，自动停止；可继续发消息推进。）"
NOTICE_UNKNOWN_TOOLS = "（连续多轮只请求到未注册的工具，自动停止。）"
NOTICE_STREAM_ERR = "（请求出错，本轮已中断。）"
NOTICE_CANCELLED = "（已取消。）"

# ── Mode ──────────────────────────────────────────


class Mode(IntEnum):
    NORMAL = 0
    PLAN = 1


# ── Agent 事件 ────────────────────────────────────


class Phase(IntEnum):
    START = 0
    END = 1


@dataclass
class ToolEvent:
    name: str
    args: str = ""
    phase: Phase = Phase.START
    result: str = ""
    is_error: bool = False


@dataclass
class Event:
    text: str = ""
    thinking: str = ""
    tool: ToolEvent | None = None
    usage: Usage | None = None
    iter: int = 0
    notice: str = ""
    done: bool = False
    err: Exception | None = None


# ── Agent ─────────────────────────────────────────

PushFn = Callable[[Event], Coroutine[Any, Any, None]]


class Agent:
    def __init__(self, provider: BaseProvider, registry: Registry) -> None:
        self._provider = provider
        self._registry = registry

    async def run(
        self,
        conv: Conversation,
        mode: Mode = Mode.NORMAL,
        cancel: asyncio.Event | None = None,
    ) -> AsyncIterator[Event]:
        if cancel is None:
            cancel = asyncio.Event()

        # push 闭包——子函数通过它往同一个 async generator 推事件
        events: list[Event] = []

        async def push(ev: Event) -> None:
            events.append(ev)

        defs = (
            self._registry.read_only_definitions()
            if mode == Mode.PLAN
            else self._registry.definitions()
        )
        suffix = PLAN_MODE_REMINDER if mode == Mode.PLAN else ""
        unknown_run = 0

        for it in range(1, MAX_ITERATIONS + 1):
            # flush pending events
            for ev in events:
                yield ev
            events.clear()

            yield Event(iter=it)

            if cancel.is_set():
                await _finish_cancelled(conv)
                return

            text, calls, usage, ok = await _stream_once(
                self._provider, conv, defs, suffix, cancel, push
            )
            for ev in events:
                yield ev
            events.clear()

            if not ok:
                if cancel.is_set():
                    await _finish_cancelled(conv)
                    return
                await _ensure_assistant_tail(conv, NOTICE_STREAM_ERR)
                return

            if usage is not None:
                yield Event(usage=usage)

            if not calls:
                conv.add_assistant(text or "（任务完成）")
                yield Event(done=True)
                return

            conv.add_assistant_with_tool_calls(text, calls)

            if _all_unknown(self._registry, calls):
                unknown_run += 1
            else:
                unknown_run = 0

            results, completed = await _execute_batched(
                self._registry, calls, cancel, push
            )
            for ev in events:
                yield ev
            events.clear()

            conv.add_tool_results(results)

            if not completed:
                await _ensure_assistant_tail(conv, NOTICE_CANCELLED)
                return

            if unknown_run >= MAX_UNKNOWN_RUN:
                yield Event(notice=NOTICE_UNKNOWN_TOOLS)
                await _ensure_assistant_tail(conv, NOTICE_UNKNOWN_TOOLS)
                yield Event(done=True)
                return

        yield Event(notice=NOTICE_MAX_ITER)
        await _ensure_assistant_tail(conv, NOTICE_MAX_ITER)
        yield Event(done=True)


# ── stream_once ───────────────────────────────────


async def _stream_once(
    provider: BaseProvider,
    conv: Conversation,
    defs: list,
    suffix: str,
    cancel: asyncio.Event,
    push: PushFn,
) -> tuple[str, list[ToolCall], Usage | None, bool]:
    """单轮流式请求。事件经 push 发出，返回 (text, calls, usage, ok)。"""
    text = ""
    calls: list[ToolCall] = []
    usage: Usage | None = None

    try:
        async for se in provider.stream(conv.messages, defs, suffix):
            if cancel.is_set():
                return "", [], None, False

            if se.err is not None:
                await push(Event(err=se.err))
                return "", [], None, False

            if se.text:
                text += se.text
                await push(Event(text=se.text))

            if se.thinking:
                await push(Event(thinking=se.thinking))

            if se.tool_calls:
                calls = se.tool_calls

            if se.usage:
                usage = se.usage

            if se.done:
                break
    except Exception as e:
        await push(Event(err=e))
        return "", [], None, False

    return text, calls, usage, True


# ── execute_batched ───────────────────────────────


async def _execute_batched(
    registry: Registry,
    calls: list[ToolCall],
    cancel: asyncio.Event,
    push: PushFn,
) -> tuple[list[ToolResult], bool]:
    """保序分批并发执行。"""
    results: list[ToolResult | None] = [None] * len(calls)
    i = 0

    while i < len(calls):
        if cancel.is_set():
            _fill_cancelled(results, i)
            return _pack_results(results), False

        if registry.is_read_only(calls[i].name):
            j = i
            while j < len(calls) and registry.is_read_only(calls[j].name):
                j += 1

            for k in range(i, j):
                await push(
                    Event(
                        tool=ToolEvent(
                            name=calls[k].name,
                            args=_args_preview(calls[k].input),
                            phase=Phase.START,
                        )
                    )
                )

            async def _run_one(k: int) -> None:
                call = calls[k]
                result = await registry.execute(
                    call.name, call.input, timeout=DEFAULT_TIMEOUT
                )
                tr = ToolResult(
                    tool_call_id=call.id,
                    content=result.content,
                    is_error=result.is_error,
                )
                results[k] = tr

            await asyncio.gather(*[_run_one(k) for k in range(i, j)])

            for k in range(i, j):
                r = results[k]
                assert r is not None
                await push(
                    Event(
                        tool=ToolEvent(
                            name=calls[k].name,
                            phase=Phase.END,
                            result=_summary(r.content),
                            is_error=r.is_error,
                        )
                    )
                )

            i = j
        else:
            call = calls[i]
            await push(
                Event(
                    tool=ToolEvent(
                        name=call.name,
                        args=_args_preview(call.input),
                        phase=Phase.START,
                    )
                )
            )
            result = await registry.execute(
                call.name, call.input, timeout=DEFAULT_TIMEOUT
            )
            tr = ToolResult(
                tool_call_id=call.id,
                content=result.content,
                is_error=result.is_error,
            )
            results[i] = tr
            await push(
                Event(
                    tool=ToolEvent(
                        name=call.name,
                        phase=Phase.END,
                        result=_summary(result.content),
                        is_error=result.is_error,
                    )
                )
            )
            i += 1

    return _pack_results(results), True


# ── 辅助函数 ──────────────────────────────────────


def _args_preview(inp: str) -> str:
    if len(inp) > 80:
        return inp[:77] + "..."
    return inp


def _summary(content: str) -> str:
    lines = content.split("\n")[:8]
    s = "\n".join(lines)
    if len(content.split("\n")) > 8:
        s += "\n..."
    return s


def _pack_results(results: list[ToolResult | None]) -> list[ToolResult]:
    return [
        r
        if r is not None
        else ToolResult(
            tool_call_id="", content=NOTICE_CANCELLED, is_error=True
        )
        for r in results
    ]


def _fill_cancelled(results: list[ToolResult | None], start: int) -> None:
    for k in range(start, len(results)):
        if results[k] is None:
            results[k] = ToolResult(
                tool_call_id="", content=NOTICE_CANCELLED, is_error=True
            )


def _all_unknown(registry: Registry, calls: list[ToolCall]) -> bool:
    return all(registry.get(c.name) is None for c in calls)


async def _ensure_assistant_tail(conv: Conversation, fallback: str) -> None:
    if conv.last_role() != "assistant":
        conv.add_assistant(fallback)


async def _finish_cancelled(conv: Conversation) -> None:
    await _ensure_assistant_tail(conv, NOTICE_CANCELLED)
