"""Agent 单轮闭环编排：请求→工具调用→执行→回灌→续答。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import Enum

from forgecode.conversation.history import (
    Conversation,
    ToolCall,
    ToolResult,
)
from forgecode.providers import BaseProvider, TokenUsage
from forgecode.tool import DEFAULT_TIMEOUT, Registry

# ── Agent 事件 ────────────────────────────────────


class Phase(Enum):
    START = "start"
    END = "end"


@dataclass
class ToolEvent:
    """一次工具调用的开始/结束。"""

    name: str
    args: str = ""
    phase: Phase = Phase.START
    result: str = ""
    is_error: bool = False


@dataclass
class Event:
    """单轮闭环对外事件流。TUI 据非空字段分派渲染。"""

    text: str = ""
    thinking: str = ""
    tool: ToolEvent | None = None
    usage: TokenUsage | None = None
    done: bool = False
    err: Exception | None = None


# ── Agent ─────────────────────────────────────────


class Agent:
    """持有 provider 与注册中心，执行单轮闭环。"""

    def __init__(self, provider: BaseProvider, registry: Registry) -> None:
        self._provider = provider
        self._registry = registry

    async def run(self, conv: Conversation) -> AsyncIterator[Event]:
        """执行单轮闭环（F5/F6），AC9 单轮上限。"""
        defs = self._registry.definitions()

        # ── 请求#1：首发（带工具） ──
        preamble = ""
        tool_calls: list[ToolCall] = []

        try:
            async for se in self._provider.stream(conv.messages, defs):
                if se.err:
                    yield Event(err=se.err)
                    return
                if se.text:
                    preamble += se.text
                    yield Event(text=se.text)
                if se.thinking:
                    yield Event(thinking=se.thinking)
                if se.tool_calls:
                    tool_calls = se.tool_calls
                if se.usage:
                    yield Event(usage=se.usage)
                if se.done:
                    break
        except Exception as e:
            yield Event(err=e)
            return

        # 无工具调用 → 纯文本回合
        if not tool_calls:
            conv.add_assistant(preamble)
            yield Event(done=True)
            return

        # ── 有工具调用 → 执行 ──
        conv.add_assistant_with_tool_calls(preamble, tool_calls)

        results: list[ToolResult] = []
        for call in tool_calls:
            # 预览参数（截断）
            args_preview = call.input
            if len(args_preview) > 80:
                args_preview = args_preview[:77] + "..."

            yield Event(
                tool=ToolEvent(name=call.name, args=args_preview, phase=Phase.START)
            )

            result = await self._registry.execute(
                call.name, call.input, timeout=DEFAULT_TIMEOUT
            )

            # 结果摘要（UI 截断 ~8 行）
            summary_lines = result.content.split("\n")[:8]
            summary = "\n".join(summary_lines)
            if len(result.content.split("\n")) > 8:
                summary += "\n..."

            yield Event(
                tool=ToolEvent(
                    name=call.name,
                    phase=Phase.END,
                    result=summary,
                    is_error=result.is_error,
                )
            )

            results.append(
                ToolResult(
                    tool_call_id=call.id,
                    content=result.content,
                    is_error=result.is_error,
                )
            )

        conv.add_tool_results(results)

        # ── 请求#2：续答 ──
        final = ""
        try:
            async for se in self._provider.stream(conv.messages, defs):
                if se.err:
                    yield Event(err=se.err)
                    return
                if se.text:
                    final += se.text
                    yield Event(text=se.text)
                if se.thinking:
                    yield Event(thinking=se.thinking)
                if se.usage:
                    yield Event(usage=se.usage)
                # 忽略第二次的任何 tool_calls（单轮上限 AC9）
                if se.done:
                    break
        except Exception as e:
            yield Event(err=e)
            return

        # 空最终答复兜底
        if not final.strip():
            final = "（工具已执行完毕）"
            yield Event(text=final)

        conv.add_assistant(final)
        yield Event(done=True)
