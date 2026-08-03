"""run_to_completion 单测：跑到底循环 / dont_ask / max_turns / upgrader / events。"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator

import pytest

from forgecode.agent import Agent
from forgecode.agent.run_to_completion import MaxTurnsReached
from forgecode.conversation.history import Conversation, ToolCall
from forgecode.permission import Outcome
from forgecode.permission.engine import new_engine
from forgecode.providers import BaseProvider, Request, StreamEvent
from forgecode.tool import Registry, Result


def _test_engine():
    e, _ = new_engine(os.getcwd())
    return e


class FakeProvider(BaseProvider):
    def __init__(self, model: str = "fake") -> None:
        from forgecode.config.schema import ProviderConfig

        self.config = ProviderConfig(name="fake", protocol="fake", model=model, base_url="", api_key="")
        self._scripts: list[list[StreamEvent]] = []
        self._call = 0

    def set_scripts(self, scripts: list[list[StreamEvent]]) -> None:
        self._scripts = scripts
        self._call = 0

    def stream(self, req: Request) -> AsyncIterator[StreamEvent]:
        idx = self._call
        self._call += 1

        async def _gen() -> AsyncIterator[StreamEvent]:
            if idx >= len(self._scripts):
                yield StreamEvent(done=True)
                return
            for item in self._scripts[idx]:
                yield item

        return _gen()


class FakeExecTool:
    """EXEC 类别工具：DEFAULT 模式下触发 ASK。"""

    read_only = False

    def name(self) -> str:
        return "fake_exec"

    def description(self) -> str:
        return "fake exec"

    def parameters(self) -> dict:
        return {"type": "object", "properties": {}}

    async def execute(self, args: str) -> Result:
        return Result(content="executed-ok")


def _registry() -> Registry:
    reg = Registry()
    reg.register(FakeExecTool())
    return reg


def _tool_call_script() -> list[StreamEvent]:
    return [
        StreamEvent(tool_calls=[ToolCall(id="c1", name="fake_exec", input="{}")]),
        StreamEvent(done=True),
    ]


@pytest.mark.asyncio
async def test_single_turn_text() -> None:
    provider = FakeProvider()
    provider.set_scripts([[StreamEvent(text="ok"), StreamEvent(done=True)]])
    agent = Agent(provider, _registry(), _test_engine(), "test")
    conv = Conversation()
    text = await agent.run_to_completion(conv, "任务")
    assert text == "ok"
    assert conv.messages[0].role == "user"


@pytest.mark.asyncio
async def test_tool_then_text() -> None:
    provider = FakeProvider()
    provider.set_scripts([_tool_call_script(), [StreamEvent(text="done"), StreamEvent(done=True)]])
    # dont_ask=True：让 ASK 级 fake_exec 直接执行（本测试聚焦工具→文本流程）
    agent = Agent(provider, _registry(), _test_engine(), "test", dont_ask=True)
    conv = Conversation()
    text = await agent.run_to_completion(conv, "任务")
    assert text == "done"
    # 工具被执行，结果写入对话
    tool_msgs = [m for m in conv.messages if m.role == "tool"]
    assert any(r.content == "executed-ok" for m in tool_msgs for r in m.tool_results)


@pytest.mark.asyncio
async def test_max_turns_reached() -> None:
    provider = FakeProvider()
    provider.set_scripts([_tool_call_script()] * 3)
    agent = Agent(provider, _registry(), _test_engine(), "test", max_turns=3)
    conv = Conversation()
    with pytest.raises(MaxTurnsReached):
        await agent.run_to_completion(conv, "任务")


@pytest.mark.asyncio
async def test_dont_ask_allows() -> None:
    provider = FakeProvider()
    provider.set_scripts([_tool_call_script(), [StreamEvent(text="ok"), StreamEvent(done=True)]])
    agent = Agent(provider, _registry(), _test_engine(), "test", dont_ask=True)
    conv = Conversation()
    text = await agent.run_to_completion(conv, "任务")
    assert text == "ok"
    tool_msgs = [m for m in conv.messages if m.role == "tool"]
    assert any(r.content == "executed-ok" for m in tool_msgs for r in m.tool_results)


@pytest.mark.asyncio
async def test_approval_upgrader_hit() -> None:
    provider = FakeProvider()
    provider.set_scripts([_tool_call_script(), [StreamEvent(text="ok"), StreamEvent(done=True)]])

    calls: list[str] = []

    async def upgrader(req):
        calls.append(req.name)
        return Outcome.ALLOW_ONCE, True

    agent = Agent(provider, _registry(), _test_engine(), "test", approval_upgrader=upgrader)
    conv = Conversation()
    text = await agent.run_to_completion(conv, "任务")
    assert text == "ok"
    assert calls == ["fake_exec"]
    tool_msgs = [m for m in conv.messages if m.role == "tool"]
    assert any(r.content == "executed-ok" for m in tool_msgs for r in m.tool_results)


@pytest.mark.asyncio
async def test_events_forwarded() -> None:
    provider = FakeProvider()
    provider.set_scripts([_tool_call_script(), [StreamEvent(text="done"), StreamEvent(done=True)]])
    agent = Agent(provider, _registry(), _test_engine(), "test")
    conv = Conversation()
    events: asyncio.Queue = asyncio.Queue(maxsize=64)
    await agent.run_to_completion(conv, "任务", events)
    seen: list = []
    while not events.empty():
        seen.append(events.get_nowait())
    assert any(ev.tool is not None for ev in seen)
    assert any(ev.text for ev in seen)
