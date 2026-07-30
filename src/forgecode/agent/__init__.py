"""Agent ReAct 循环编排：多轮→权限判定→工具调用→结果回灌。"""

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
from forgecode.permission import Decision, Mode, Outcome
from forgecode.permission.engine import Engine
from forgecode.prompt import build_system_prompt, gather_environment, plan_reminder
from forgecode.providers import BaseProvider, Request, System, Usage
from forgecode.tool import DEFAULT_TIMEOUT, Registry

# ── 常量 ──────────────────────────────────────────

MAX_ITERATIONS: int = 25
MAX_UNKNOWN_RUN: int = 3
PLAN_REMINDER_INTERVAL: int = 4

NOTICE_MAX_ITER = "（已达最大迭代轮数 25，自动停止；可继续发消息推进。）"
NOTICE_UNKNOWN_TOOLS = "（连续多轮只请求到未注册的工具，自动停止。）"
NOTICE_STREAM_ERR = "（请求出错，本轮已中断。）"
NOTICE_CANCELLED = "（已取消。）"

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
class ApprovalRequest:
    """人在回路待批准事件。TUI 必须通过 respond Future 回传用户选择。"""

    name: str
    args: str
    reason: str
    respond: asyncio.Future[Outcome]  # noqa: RUF009


@dataclass
class Event:
    text: str = ""
    thinking: str = ""
    tool: ToolEvent | None = None
    usage: Usage | None = None
    approval: ApprovalRequest | None = None
    iter: int = 0
    notice: str = ""
    done: bool = False
    err: Exception | None = None


# ── Agent ─────────────────────────────────────────


class Agent:
    def __init__(
        self,
        provider: BaseProvider,
        registry: Registry,
        engine: Engine,
        version: str = "",
    ) -> None:
        self._provider = provider
        self._registry = registry
        self._engine = engine
        self._version = version

    async def run(
        self,
        conv: Conversation,
        mode: Mode = Mode.DEFAULT,
        cancel: asyncio.Event | None = None,
    ) -> AsyncIterator[Event]:
        if cancel is None:
            cancel = asyncio.Event()

        env = gather_environment(self._version, self._provider.config.model)
        env_text = env.render()
        sys = build_system_prompt()

        defs = self._registry.read_only_definitions() if mode == Mode.PLAN else self._registry.definitions()
        unknown_run = 0

        for it in range(1, MAX_ITERATIONS + 1):
            yield Event(iter=it)

            if cancel.is_set():
                await _finish_cancelled(conv)
                return

            reminder = ""
            if mode == Mode.PLAN:
                full = it == 1 or (it - 1) % PLAN_REMINDER_INTERVAL == 0
                reminder = plan_reminder(full)

            result: dict[str, Any] = {}
            async for ev in _stream_once(self._provider, conv, sys, env_text, defs, reminder, cancel, result):
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

            if not calls:
                conv.add_assistant(text or "（任务完成）")
                yield Event(done=True)
                return

            conv.add_assistant_with_tool_calls(text, calls)

            if _all_unknown(self._registry, calls):
                unknown_run += 1
            else:
                unknown_run = 0

            batched_result: dict[str, Any] = {}
            async for ev in _execute_batched(
                self._registry, self._engine, calls, mode, cancel, batched_result
            ):
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

        yield Event(notice=NOTICE_MAX_ITER)
        await _ensure_assistant_tail(conv, NOTICE_MAX_ITER)
        yield Event(done=True)


# ── stream_once ───────────────────────────────────


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


# ── execute_batched（含权限判定）───────────────────


async def _execute_batched(
    registry: Registry,
    engine: Engine,
    calls: list[ToolCall],
    mode: Mode,
    cancel: asyncio.Event,
    result: dict[str, Any],
) -> AsyncIterator[Event]:
    """保序分批并发执行，每工具前走权限判定。"""
    results: list[ToolResult | None] = [None] * len(calls)
    i = 0

    while i < len(calls):
        if cancel.is_set():
            _fill_cancelled(results, i)
            result["results"] = _pack_results(results)
            result["completed"] = False
            return

        read_only = registry.is_read_only(calls[i].name)

        if read_only:
            # 只读批：逐个 check（只读永不 Ask），Deny 项跳过执行
            j = i
            while j < len(calls) and registry.is_read_only(calls[j].name):
                j += 1

            # 先 check 所有
            denials: dict[int, tuple[Decision, str]] = {}
            for k in range(i, j):
                d, reason = engine.check(mode, calls[k], True)
                if d == Decision.DENY:
                    denials[k] = (d, reason)

            for k in range(i, j):
                yield Event(
                    tool=ToolEvent(
                        name=calls[k].name,
                        args=_args_preview(calls[k].input),
                        phase=Phase.START,
                    )
                )

            async def _run_one(k: int) -> None:
                if k in denials:
                    _, reason = denials[k]
                    results[k] = ToolResult(tool_call_id=calls[k].id, content=reason, is_error=True)
                    return
                exec_result = await registry.execute(calls[k].name, calls[k].input, timeout=DEFAULT_TIMEOUT)
                results[k] = ToolResult(
                    tool_call_id=calls[k].id, content=exec_result.content, is_error=exec_result.is_error
                )

            await asyncio.gather(*[_run_one(k) for k in range(i, j)])

            for k in range(i, j):
                r = results[k]
                assert r is not None
                yield Event(
                    tool=ToolEvent(
                        name=calls[k].name, phase=Phase.END, result=_summary(r.content), is_error=r.is_error
                    )
                )

            i = j
        else:
            # 有副作用 → 串行，走 check
            call = calls[i]
            d, reason = engine.check(mode, call, False)

            yield Event(tool=ToolEvent(name=call.name, args=_args_preview(call.input), phase=Phase.START))

            if d == Decision.ALLOW:
                exec_result = await registry.execute(call.name, call.input, timeout=DEFAULT_TIMEOUT)
                results[i] = ToolResult(
                    tool_call_id=call.id, content=exec_result.content, is_error=exec_result.is_error
                )
            elif d == Decision.DENY:
                results[i] = ToolResult(tool_call_id=call.id, content=reason, is_error=True)
            else:  # ASK → 人在回路
                respond: asyncio.Future[Outcome] = asyncio.get_running_loop().create_future()
                yield Event(
                    approval=ApprovalRequest(
                        name=call.name,
                        args=_args_preview(call.input),
                        reason=reason,
                        respond=respond,
                    )
                )
                outcome = await respond
                if outcome == Outcome.DENY_ONCE:
                    results[i] = ToolResult(tool_call_id=call.id, content=reason, is_error=True)
                else:
                    if outcome == Outcome.ALLOW_FOREVER:
                        try:
                            from forgecode.permission.persist import persist_local_allow

                            persist_local_allow(engine, call)
                        except Exception:
                            pass
                    exec_result = await registry.execute(call.name, call.input, timeout=DEFAULT_TIMEOUT)
                    results[i] = ToolResult(
                        tool_call_id=call.id, content=exec_result.content, is_error=exec_result.is_error
                    )

            r = results[i]
            assert r is not None
            yield Event(
                tool=ToolEvent(
                    name=call.name, phase=Phase.END, result=_summary(r.content), is_error=r.is_error
                )
            )
            i += 1

    result["results"] = _pack_results(results)
    result["completed"] = True


# ── 辅助 ──────────────────────────────────────────


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
