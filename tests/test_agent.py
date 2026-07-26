"""Agent 单轮闭环单测：AC8 链路 / AC9 单轮上限。"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from forgecode.agent import Agent, Event, Phase
from forgecode.conversation.history import (
    Conversation,
    Message,
    ToolCall,
    ToolDefinition,
)
from forgecode.providers import BaseProvider, StreamEvent
from forgecode.tool import Registry, Result

# ── Fake Provider ─────────────────────────────────


class FakeProvider(BaseProvider):
    """可编排的假 Provider，通过脚本控制每次 stream 调用的行为。"""

    def __init__(self) -> None:
        from forgecode.config.schema import ProviderConfig

        self.config = ProviderConfig(
            name="fake", protocol="fake", model="fake",
            base_url="", api_key="",
        )
        self._scripts: list[list[StreamEvent]] = []
        self._call = 0

    def set_scripts(self, scripts: list[list[StreamEvent]]) -> None:
        """设定每次 stream() 调用的返回序列。"""
        self._scripts = scripts
        self._call = 0

    def stream(
        self, msgs: list[Message], tools: list[ToolDefinition]
    ) -> AsyncIterator[StreamEvent]:
        idx = self._call
        self._call += 1

        async def gen() -> AsyncIterator[StreamEvent]:
            for item in self._scripts[idx]:
                yield item

        return gen()


# ── Fake 工具 ─────────────────────────────────────


class FakeEchoTool:
    def name(self) -> str:
        return "echo"

    def description(self) -> str:
        return "fake echo tool"

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {"msg": {"type": "string"}},
            "required": ["msg"],
        }

    async def execute(self, args: str) -> Result:
        import json

        data = json.loads(args)
        return Result(content=f"echo: {data.get('msg', '')}")


# ── 测试 ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_ac8_tool_roundtrip():
    """AC8: 单轮闭环——模型调用工具 → 执行 → 回灌 → 最终答复。"""
    provider = FakeProvider()
    registry = Registry()
    registry.register(FakeEchoTool())

    provider.set_scripts(
        [
            # 请求#1：前导文本 + 工具调用
            [
                StreamEvent(text="让我用 echo 工具。"),
                StreamEvent(
                    tool_calls=[
                        ToolCall(
                            id="call_1",
                            name="echo",
                            input='{"msg": "hello world"}',
                        )
                    ]
                ),
                StreamEvent(done=True),
            ],
            # 请求#2：最终答复
            [
                StreamEvent(text="工具返回了: echo: hello world"),
                StreamEvent(done=True),
            ],
        ]
    )

    agent = Agent(provider, registry)
    conv = Conversation()
    conv.add_user("请用 echo 工具说 hello world")

    events: list[Event] = []
    async for ev in agent.run(conv):
        events.append(ev)

    # 验证事件序列
    text_events = [e for e in events if e.text]
    tool_events = [e for e in events if e.tool]
    done_events = [e for e in events if e.done]

    assert len(text_events) >= 2  # preamble + final
    assert len(tool_events) == 2  # START + END
    assert tool_events[0].tool.phase == Phase.START
    assert tool_events[1].tool.phase == Phase.END
    assert tool_events[1].tool.result.startswith("echo:")
    assert len(done_events) == 1

    # 验证对话历史
    msgs = conv.messages
    assert len(msgs) == 4  # user + assistant(tool) + tool_result + assistant(final)
    assert msgs[1].tool_calls[0].name == "echo"
    assert msgs[2].role == "tool"
    assert msgs[3].content == "工具返回了: echo: hello world"


@pytest.mark.asyncio
async def test_ac9_single_turn_limit():
    """AC9: 单轮上限——请求#2 若再次请求工具，忽略并不再执行。"""
    provider = FakeProvider()
    registry = Registry()
    registry.register(FakeEchoTool())

    provider.set_scripts(
        [
            # 请求#1：工具调用
            [
                StreamEvent(
                    tool_calls=[
                        ToolCall(
                            id="call_1",
                            name="echo",
                            input='{"msg": "step1"}',
                        )
                    ]
                ),
                StreamEvent(done=True),
            ],
            # 请求#2：再次请求工具（应被忽略）
            [
                StreamEvent(text="还需要..."),
                StreamEvent(
                    tool_calls=[
                        ToolCall(
                            id="call_2",
                            name="echo",
                            input='{"msg": "step2"}',
                        )
                    ]
                ),
                StreamEvent(done=True),
            ],
        ]
    )

    agent = Agent(provider, registry)
    conv = Conversation()
    conv.add_user("test")

    events: list[Event] = []
    async for ev in agent.run(conv):
        events.append(ev)

    # 应该只有 1 次工具执行（1 对 START/END）
    tool_start_events = [
        e for e in events
        if e.tool and e.tool.phase == Phase.START
    ]
    assert len(tool_start_events) == 1

    # 对话历史应该只有 4 条消息
    assert len(conv.messages) == 4
