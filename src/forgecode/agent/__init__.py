"""Agent ReAct 循环编排：多轮→权限判定→工具调用→结果回灌 + 上下文管理集成。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import Enum, IntEnum
from pathlib import Path
from typing import Any

from forgecode.compact import (
    ManageInput,
    ManageOutput,
    TriggerKind,
    manage_context,
)
from forgecode.compact.token import estimate_tokens
from forgecode.compact.token import usage_anchor as _usage_anchor_fn
from forgecode.conversation.history import (
    ROLE_USER,
    Conversation,
    ToolCall,
    ToolDefinition,
    ToolResult,
)
from forgecode.permission import Decision, Mode, Outcome
from forgecode.permission.engine import Engine
from forgecode.prompt import (
    build_system_prompt,
    gather_environment,
    plan_reminder,
    render_active_skills_block,
    render_skills_catalog,
)
from forgecode.providers import (
    BaseProvider,
    PromptTooLongError,
    Request,
    System,
    Usage,
)
from forgecode.tool import DEFAULT_TIMEOUT, Registry

# ── 常量 ──────────────────────────────────────────

MAX_ITERATIONS: int = 25
MAX_UNKNOWN_RUN: int = 3
PLAN_REMINDER_INTERVAL: int = 4
MEMORY_UPDATE_INTERVAL: int = 5  # 每 N 轮自然完成触发记忆更新

NOTICE_MAX_ITER = "（已达最大迭代轮数 25，自动停止；可继续发消息推进。）"
NOTICE_UNKNOWN_TOOLS = "（连续多轮只请求到未注册的工具，自动停止。）"
NOTICE_STREAM_ERR = "（请求出错，本轮已中断。）"
NOTICE_CANCELLED = "（已取消。）"

MANUAL_SAFETY_MARGIN: int = 3000
AUTO_SAFETY_MARGIN: int = 13000
SUMMARY_RESERVE: int = 20000

# 记忆请求关键词
_MEMORY_SIGNALS = ("记住", "记忆", "别忘", "remember", "memo")

# ── Agent 事件 ────────────────────────────────────


class Phase(IntEnum):
    START = 0
    END = 1


class CompactPhase(Enum):
    BEFORE_AUTO = "before_auto"
    AFTER_AUTO = "after_auto"
    BEFORE_EMERGENCY = "before_emergency"
    AFTER_EMERGENCY = "after_emergency"


@dataclass
class CompactEvent:
    phase: CompactPhase
    before: int = 0
    after: int = 0
    err: Exception | None = None


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
    compact: CompactEvent | None = None
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
        *,
        runtime: Any = None,  # SessionRuntime | None
        memory_manager: Any = None,  # memory.Manager | None
        instruction_text: str = "",
        memory_text: str = "",
        catalog=None,
        allowed_tools: list[str] | None = None,
    ) -> None:
        self._provider = provider
        self._registry = registry
        self._engine = engine
        self._version = version
        self._memory_manager = memory_manager
        self._instruction_text = instruction_text
        self._memory_text = memory_text
        self._catalog = catalog
        self._allowed_tools = allowed_tools

        if runtime is None:
            from forgecode.agent.runtime import new_runtime

            runtime = new_runtime(".")
        self.runtime = runtime
        self._run_lock = asyncio.Lock()

    def activate_skill(self, name: str, body: str) -> None:
        if self.runtime is not None and self.runtime.active_skills is not None:
            self.runtime.active_skills.activate(name, body)

    def clear_active_skills(self) -> None:
        if self.runtime is not None and self.runtime.active_skills is not None:
            self.runtime.active_skills.clear()

    async def run(
        self,
        conv: Conversation,
        mode: Mode = Mode.DEFAULT,
        cancel: asyncio.Event | None = None,
    ) -> AsyncIterator[Event]:
        """Agent 主循环：ReAct 多轮 + 上下文管理。"""
        if cancel is None:
            cancel = asyncio.Event()

        async with self._run_lock:
            async for ev in self._run_impl(conv, mode, cancel):
                yield ev

    async def _run_impl(
        self,
        conv: Conversation,
        mode: Mode,
        cancel: asyncio.Event,
    ) -> AsyncIterator[Event]:
        env = gather_environment(self._version, self._provider.config.model)
        env_text = env.render()
        if self.runtime is not None and self.runtime.active_skills is not None:
            active_block = render_active_skills_block(self.runtime.active_skills.to_prompt_entries())
            if active_block:
                env_text += "\\n\\n" + active_block
        catalog_text = ""
        if self._catalog is not None:
            catalog_text = render_skills_catalog(self._catalog.to_prompt_items())
        sys = build_system_prompt(self._instruction_text, self._memory_text, catalog_text)
        unknown_run = 0

        for it in range(1, MAX_ITERATIONS + 1):
            yield Event(iter=it)

            if cancel.is_set():
                await _finish_cancelled(conv)
                return

            # 本轮按 mode 选工具定义（同一份引用给 manage_context 和 stream）
            if self._allowed_tools is not None:
                defs = self._registry.definitions_filtered(self._allowed_tools)
            elif mode == Mode.PLAN:
                defs = self._registry.read_only_definitions()
            else:
                defs = self._registry.definitions()

            # ── 上下文管理（每轮 stream 之前）──
            anchor = self.runtime.usage_anchor
            anchor_len = self.runtime.anchor_msg_len
            cw = self.runtime.context_window
            est = estimate_tokens(anchor, conv.messages, anchor_len)

            in_ = ManageInput(
                conv=conv,
                provider=self._provider,
                model=self._provider.config.model,
                context_window=cw,
                tool_defs=defs,
                replacement=self.runtime.replacement,
                recovery=self.runtime.recovery,
                auto_tracking=self.runtime.auto_tracking,
                session=self.runtime.session,
                usage_anchor=anchor,
                anchor_msg_len=anchor_len,
                estimated_token=est,
                trigger=TriggerKind.AUTO,
            )

            # 判断是否会触发自动摘要（用于 emit before 事件）
            threshold = cw - SUMMARY_RESERVE - AUTO_SAFETY_MARGIN
            will_summarize = (
                est >= threshold
                and cw > SUMMARY_RESERVE + AUTO_SAFETY_MARGIN
                and not self.runtime.auto_tracking.tripped()
            )

            if will_summarize:
                yield Event(compact=CompactEvent(phase=CompactPhase.BEFORE_AUTO))

            mc_err: Exception | None = None
            try:
                out = await manage_context(in_)
            except Exception as e:
                mc_err = e
                out = ManageOutput(before_tokens=est, after_tokens=0)

            if will_summarize:
                yield Event(
                    compact=CompactEvent(
                        phase=CompactPhase.AFTER_AUTO,
                        before=out.before_tokens,
                        after=out.after_tokens,
                        err=mc_err,
                    )
                )

            if mc_err is not None:
                yield Event(err=mc_err)
                return

            # layer1 落盘提示
            if out.offloaded > 0:
                spill = self.runtime.session.spill_dir
                yield Event(notice=f"已落盘 {out.offloaded} 个大工具结果到 {spill}")

            # ── Plan Mode reminder ──
            reminder = ""
            if mode == Mode.PLAN:
                full = it == 1 or (it - 1) % PLAN_REMINDER_INTERVAL == 0
                reminder = plan_reminder(full)

            # ── stream_once ──
            stream_result: dict[str, Any] = {}
            async for ev in _stream_once(
                self._provider, conv, sys, env_text, defs, reminder, cancel, stream_result
            ):
                yield ev

            text: str = stream_result.get("text", "")
            calls: list[ToolCall] = stream_result.get("calls", [])
            usage: Usage | None = stream_result.get("usage")
            err: Exception | None = stream_result.get("err")

            if err is not None:
                # ── 紧急压缩处理 ──
                if isinstance(err, PromptTooLongError):
                    async for ev in self._emergency_compact(conv, est, err):
                        yield ev
                    # 重新估算
                    est2 = estimate_tokens(0, conv.messages, 0)
                    if est2 >= cw - MANUAL_SAFETY_MARGIN:
                        yield Event(err=Exception("紧急压缩后 token 仍超限，无法恢复"))
                        return
                    # 重试一次
                    retry_result: dict[str, Any] = {}
                    async for ev in _stream_once(
                        self._provider, conv, sys, env_text, defs, reminder, cancel, retry_result
                    ):
                        yield ev
                    text = retry_result.get("text", "")
                    calls = retry_result.get("calls", [])
                    usage = retry_result.get("usage")
                    err = retry_result.get("err")

            if err is not None:
                if cancel.is_set():
                    await _finish_cancelled(conv)
                    return
                yield Event(err=err)
                await _ensure_assistant_tail(conv, NOTICE_STREAM_ERR)
                return

            # 更新 usage 锚点（仅主对话路径）
            if usage is not None:
                self.runtime.usage_anchor = _usage_anchor_fn(usage)
                self.runtime.anchor_msg_len = conv.length()
                yield Event(usage=usage)

            if not calls:
                conv.add_assistant(text or "（任务完成）")
                # ── 记忆更新触发 ──
                await self._maybe_update_memory(conv)
                yield Event(done=True)
                return

            conv.add_assistant_with_tool_calls(text, calls)

            # 未知工具计数
            if _all_unknown(self._registry, calls):
                unknown_run += 1
            else:
                unknown_run = 0

            # 工具执行
            batched_result: dict[str, Any] = {}
            async for ev in _execute_batched(
                self._registry, self._engine, calls, mode, cancel, self.runtime, batched_result
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

    async def _maybe_update_memory(self, conv: Conversation) -> None:
        """检查是否需要触发异步记忆更新。"""
        if self._memory_manager is None:
            return

        # 递增轮数计数
        self.runtime.turn_count += 1

        # 提取最近一轮消息（从最后一条 user 到当前 assistant）
        recent_msgs = _extract_recent_turn(conv)

        # 条件：每 N 轮 或 检测到显式记忆请求关键词
        should_update = self.runtime.turn_count % MEMORY_UPDATE_INTERVAL == 0 or _has_memory_signal(
            recent_msgs
        )

        if should_update:
            # 异步执行，不阻塞用户下一次输入
            asyncio.create_task(self._memory_manager.update_async(recent_msgs))

    async def _emergency_compact(self, conv: Conversation, est: int, err: Exception) -> AsyncIterator[Event]:
        """紧急压缩：先 layer1 再 force_compact。"""
        yield Event(compact=CompactEvent(phase=CompactPhase.BEFORE_EMERGENCY))

        in_ = ManageInput(
            conv=conv,
            provider=self._provider,
            model=self._provider.config.model,
            context_window=self.runtime.context_window,
            tool_defs=self._registry.definitions(),
            replacement=self.runtime.replacement,
            recovery=self.runtime.recovery,
            auto_tracking=self.runtime.auto_tracking,
            session=self.runtime.session,
            usage_anchor=self.runtime.usage_anchor,
            anchor_msg_len=self.runtime.anchor_msg_len,
            estimated_token=est,
            trigger=TriggerKind.EMERGENCY,
        )

        mc_err: Exception | None = None
        try:
            out = await manage_context(in_)
        except Exception as e:
            mc_err = e
            out = ManageOutput(before_tokens=est, after_tokens=0)

        yield Event(
            compact=CompactEvent(
                phase=CompactPhase.AFTER_EMERGENCY,
                before=out.before_tokens,
                after=out.after_tokens,
                err=mc_err,
            )
        )

        if mc_err is not None:
            raise mc_err

        self.runtime.usage_anchor = 0
        self.runtime.anchor_msg_len = 0

    async def run_force_compact(self, conv: Conversation, tool_defs: list[ToolDefinition]) -> tuple[int, int]:
        """手动 /compact 入口，由 TUI 调用。"""
        async with self._run_lock:
            anchor = self.runtime.usage_anchor
            anchor_len = self.runtime.anchor_msg_len
            est = estimate_tokens(anchor, conv.messages, anchor_len)

            in_ = ManageInput(
                conv=conv,
                provider=self._provider,
                model=self._provider.config.model,
                context_window=self.runtime.context_window,
                tool_defs=tool_defs,
                replacement=self.runtime.replacement,
                recovery=self.runtime.recovery,
                auto_tracking=self.runtime.auto_tracking,
                session=self.runtime.session,
                usage_anchor=anchor,
                anchor_msg_len=anchor_len,
                estimated_token=est,
                trigger=TriggerKind.MANUAL,
            )
            out = await manage_context(in_)
            return (out.before_tokens, out.after_tokens)


# ── stream_once ───────────────────────────────────


async def _stream_once(
    provider: BaseProvider,
    conv: Conversation,
    sys: str,
    env_text: str,
    defs: list[ToolDefinition],
    reminder: str,
    cancel: asyncio.Event,
    result: dict[str, Any],
) -> AsyncIterator[Event]:
    """单轮流式请求。通过 result dict 返回 text/calls/usage/err。"""
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
                result["text"] = text
                result["ok"] = False
                return
            if se.err is not None:
                result["text"] = text
                result["calls"] = calls
                result["usage"] = usage
                result["err"] = se.err
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
        result["text"] = text
        result["calls"] = calls
        result["usage"] = usage
        result["err"] = e
        result["ok"] = False
        return

    result["text"] = text
    result["calls"] = calls
    result["usage"] = usage
    result["err"] = None
    result["ok"] = True


# ── execute_batched（含权限判定 + ReadFile 追踪）────


async def _execute_batched(
    registry: Registry,
    engine: Engine,
    calls: list[ToolCall],
    mode: Mode,
    cancel: asyncio.Event,
    runtime: Any,
    result: dict[str, Any],
) -> AsyncIterator[Event]:
    """保序分批并发执行，每工具前走权限判定，ReadFile 成功后写 recovery。"""
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
            # 只读批
            j = i
            while j < len(calls) and registry.is_read_only(calls[j].name):
                j += 1

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

            async def _run_read_only(k: int) -> None:
                if k in denials:
                    _, reason = denials[k]
                    results[k] = ToolResult(tool_call_id=calls[k].id, content=reason, is_error=True)
                    return
                exec_result = await registry.execute(calls[k].name, calls[k].input, timeout=DEFAULT_TIMEOUT)
                results[k] = ToolResult(
                    tool_call_id=calls[k].id, content=exec_result.content, is_error=exec_result.is_error
                )
                # ReadFile 成功后写 recovery
                await _track_read_file(runtime, calls[k], exec_result)

            await asyncio.gather(*[_run_read_only(k) for k in range(i, j)])

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
            # 有副作用 → 串行
            call = calls[i]
            d, reason = engine.check(mode, call, False)

            yield Event(tool=ToolEvent(name=call.name, args=_args_preview(call.input), phase=Phase.START))

            if d == Decision.ALLOW:
                exec_result = await registry.execute(call.name, call.input, timeout=DEFAULT_TIMEOUT)
                results[i] = ToolResult(
                    tool_call_id=call.id, content=exec_result.content, is_error=exec_result.is_error
                )
                await _track_read_file(runtime, call, exec_result)
            elif d == Decision.DENY:
                results[i] = ToolResult(tool_call_id=call.id, content=reason, is_error=True)
            else:  # ASK
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
                    await _track_read_file(runtime, call, exec_result)

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


# ── ReadFile 追踪 ──────────────────────────────────


async def _track_read_file(runtime: Any, call: ToolCall, exec_result: Any) -> None:
    """ReadFile 成功后用纯净字节写入 RecoveryState。"""
    if call.name != "read_file" or exec_result.is_error:
        return
    try:
        args: dict = json.loads(call.input) if isinstance(call.input, str) else call.input
    except (json.JSONDecodeError, TypeError):
        return
    if not isinstance(args, dict):
        return
    path = args.get("path")
    if not isinstance(path, str) or not path:
        return
    try:
        abs_path = str(Path(path).resolve())
    except OSError:
        return
    try:
        data = await asyncio.to_thread(Path(abs_path).read_bytes)
        runtime.recovery.record_file(abs_path, data.decode("utf-8", errors="replace"))
    except OSError:
        pass


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


def _extract_recent_turn(conv: Conversation) -> list[Any]:
    """提取最近一轮对话消息（从最后一条 user 到末尾）。"""
    msgs = conv.messages
    if not msgs:
        return []

    # 从末尾向前找最后一条 user 消息
    start = len(msgs) - 1
    while start >= 0 and msgs[start].role != ROLE_USER:
        start -= 1

    if start < 0:
        return list(msgs)

    return list(msgs[start:])


def _has_memory_signal(msgs: list[Any]) -> bool:
    """检测消息中是否包含显式记忆请求关键词。"""
    for m in msgs:
        text = getattr(m, "content", "") or ""
        text_lower = text.lower()
        for kw in _MEMORY_SIGNALS:
            if kw in text_lower:
                return True
    return False
