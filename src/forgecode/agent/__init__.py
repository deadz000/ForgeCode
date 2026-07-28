"""Agent ReAct 循环编排：多轮→工具调用→结果回灌→持续直到任务完成。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import IntEnum
from typing import Any

from forgecode.conversation.history import (
    Conversation,
    ToolCall,
    ToolResult,
)
from forgecode.prompt import build_system_prompt, gather_environment, plan_reminder
from forgecode.providers import BaseProvider, Request, System, Usage
from forgecode.tool import DEFAULT_TIMEOUT, Registry

# ── 常量 ──────────────────────────────────────────

MAX_ITERATIONS: int = 25
MAX_UNKNOWN_RUN: int = 3
PLAN_REMINDER_INTERVAL: int = 4  # 每隔 N 轮重复一次完整规划提醒

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


class Agent:
    def __init__(self, provider: BaseProvider, registry: Registry, version: str = "") -> None:
        self._provider = provider
        self._registry = registry
        self._version = version

    async def run(
        self,
        conv: Conversation,
        mode: Mode = Mode.NORMAL,
        cancel: asyncio.Event | None = None,
    ) -> AsyncIterator[Event]:
        if cancel is None:
            cancel = asyncio.Event()

        # ── 采集环境 + 装配稳定系统提示 ──
        env = gather_environment(self._version, self._provider.config.model)
        env_text = env.render()
        sys = build_system_prompt()

        defs = (
            self._registry.read_only_definitions()
            if mode == Mode.PLAN
            else self._registry.definitions()
        )
        unknown_run = 0

        for it in range(1, MAX_ITERATIONS + 1):
            yield Event(iter=it)

            if cancel.is_set():
                await _finish_cancelled(conv)
                return

            # ── 按轮次计算 reminder ──
            reminder = ""
            if mode == Mode.PLAN:
                full = it == 1 or (it - 1) % PLAN_REMINDER_INTERVAL == 0
                reminder = plan_reminder(full)

            # ── 流式请求 ──
            result: dict[str, Any] = {}
            async for ev in _stream_once(
                self._provider, conv, sys, env_text, defs, reminder, cancel, result
            ):
                yield ev

            ok: bool = result.get("ok", False)
            if not ok:
                if cancel.is_set():
                    await _finish_cancelled(conv)
                    return
                await _ensure_assistant_tail(conv, NOTICE_STREAM_ERR)
                return

            text: str = result.get("text", "")
            calls: list[ToolCall] = result.get("calls", [])
            usage: Usage | None = result.get("usage")

            if usage is not None:
                yield Event(usage=usage)

            # ── 无工具 → 自然完成 ──
            if not calls:
                conv.add_assistant(text or "（任务完成）")
                yield Event(done=True)
                return

            # ── 有工具 → 执行 ──
            conv.add_assistant_with_tool_calls(text, calls)

            if _all_unknown(self._registry, calls):
                unknown_run += 1
            else:
                unknown_run = 0

            batched_result: dict[str, Any] = {}
            async for ev in _execute_batched(self._registry, calls, cancel, batched_result):
                yield ev

            results: list[ToolResult] = batched_result.get("results", [])
            completed: bool = batched_result.get("completed", False)
            conv.add_tool_results(results)

            if not completed:
                await _ensure_assistant_tail(conv, NOTICE_CANCELLED)
                return

            if unknown_run >= MAX_UNKNOWN_RUN:
                yield Event(notice=NOTICE_UNKNOWN_TOOLS)
                await _ensure_assistant_tail(conv, NOTICE_UNKNOWN_TOOLS)
                yield Event(done=True)
                return

        # 迭代上限
        yield Event(notice=NOTICE_MAX_ITER)
        await _ensure_assistant_tail(conv, NOTICE_MAX_ITER)
        yield Event(done=True)


# ── stream_once（async generator） ────────────────


async def _stream_once(
    provider: BaseProvider,
    conv: Conversation,
    sys: str,
    env_text: str,
    defs: list,
    reminder: str,
    cancel: asyncio.Event,
    result: dict[str, Any],
) -> AsyncIterator[Event]:
    """单轮流式请求。事件实时 yield，结果通过 result dict 传回。"""
    text = ""
    calls: list[ToolCall] = []
    usage: Usage | None = None

    req = Request(
        messages=conv.messages,
        tools=defs,
        system=System(stable=sys, environment=env_text),
        reminder=reminder,
    )

    try:
        async for se in provider.stream(req):
            if cancel.is_set():
                result["ok"] = False
                return

            if se.err is not None:
                yield Event(err=se.err)
                result["ok"] = False
                return

            if se.text:
                text += se.text
                yield Event(text=se.text)

            if se.thinking:
                yield Event(thinking=se.thinking)

            if se.tool_calls:
                calls = se.tool_calls

            if se.usage:
                usage = se.usage

            if se.done:
                break
    except Exception as e:
        yield Event(err=e)
        result["ok"] = False
        return

    result["text"] = text
    result["calls"] = calls
    result["usage"] = usage
    result["ok"] = True


# ── execute_batched（async generator） ────────────


async def _execute_batched(
    registry: Registry,
    calls: list[ToolCall],
    cancel: asyncio.Event,
    result: dict[str, Any],
) -> AsyncIterator[Event]:
    """保序分批并发执行。事件实时 yield，结果通过 result dict 传回。"""
    results: list[ToolResult | None] = [None] * len(calls)
    i = 0

    while i < len(calls):
        if cancel.is_set():
            _fill_cancelled(results, i)
            result["results"] = _pack_results(results)
            result["completed"] = False
            return

        if registry.is_read_only(calls[i].name):
            j = i
            while j < len(calls) and registry.is_read_only(calls[j].name):
                j += 1

            for k in range(i, j):
                yield Event(
                    tool=ToolEvent(
                        name=calls[k].name,
                        args=_args_preview(calls[k].input),
                        phase=Phase.START,
                    )
                )

            async def _run_one(k: int) -> None:
                call = calls[k]
                exec_result = await registry.execute(call.name, call.input, timeout=DEFAULT_TIMEOUT)
                tr = ToolResult(
                    tool_call_id=call.id,
                    content=exec_result.content,
                    is_error=exec_result.is_error,
                )
                results[k] = tr

            await asyncio.gather(*[_run_one(k) for k in range(i, j)])

            for k in range(i, j):
                r = results[k]
                assert r is not None
                yield Event(
                    tool=ToolEvent(
                        name=calls[k].name,
                        phase=Phase.END,
                        result=_summary(r.content),
                        is_error=r.is_error,
                    )
                )

            i = j
        else:
            call = calls[i]
            yield Event(
                tool=ToolEvent(
                    name=call.name,
                    args=_args_preview(call.input),
                    phase=Phase.START,
                )
            )
            exec_result = await registry.execute(call.name, call.input, timeout=DEFAULT_TIMEOUT)
            tr = ToolResult(
                tool_call_id=call.id,
                content=exec_result.content,
                is_error=exec_result.is_error,
            )
            results[i] = tr
            yield Event(
                tool=ToolEvent(
                    name=call.name,
                    phase=Phase.END,
                    result=_summary(exec_result.content),
                    is_error=exec_result.is_error,
                )
            )
            i += 1

    result["results"] = _pack_results(results)
    result["completed"] = True


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
        r if r is not None else ToolResult(tool_call_id="", content=NOTICE_CANCELLED, is_error=True)
        for r in results
    ]


def _fill_cancelled(results: list[ToolResult | None], start: int) -> None:
    for k in range(start, len(results)):
        if results[k] is None:
            results[k] = ToolResult(tool_call_id="", content=NOTICE_CANCELLED, is_error=True)


def _all_unknown(registry: Registry, calls: list[ToolCall]) -> bool:
    return all(registry.get(c.name) is None for c in calls)


async def _ensure_assistant_tail(conv: Conversation, fallback: str) -> None:
    if conv.last_role() != "assistant":
        conv.add_assistant(fallback)


async def _finish_cancelled(conv: Conversation) -> None:
    await _ensure_assistant_tail(conv, NOTICE_CANCELLED)
