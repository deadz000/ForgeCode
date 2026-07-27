"""Agent Loop 单测：多轮链路、停止条件、保序分批、Plan Mode。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest

from forgecode.agent import (
    MAX_ITERATIONS,
    MAX_UNKNOWN_RUN,
    NOTICE_CANCELLED,
    NOTICE_MAX_ITER,
    NOTICE_UNKNOWN_TOOLS,
    Agent,
    Event,
    Mode,
    Phase,
)
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
    def __init__(self) -> None:
        from forgecode.config.schema import ProviderConfig

        self.config = ProviderConfig(
            name="fake", protocol="fake", model="fake",
            base_url="", api_key="",
        )
        self._scripts: list[list[StreamEvent]] = []
        self._call = 0
        self.calls_record: list[list] = []  # 记录每次 stream 收到的 tools

    def set_scripts(self, scripts: list[list[StreamEvent]]) -> None:
        self._scripts = scripts
        self._call = 0
        self.calls_record.clear()

    def stream(
        self, msgs: list[Message], tools: list[ToolDefinition],
        system_suffix: str = "",
    ) -> AsyncIterator[StreamEvent]:
        self.calls_record.append([t.name for t in tools])
        if self._call >= len(self._scripts):
            # 脚本耗尽则返回空（测试迭代上限用）
            async def _empty() -> AsyncIterator[StreamEvent]:
                yield StreamEvent(done=True)
                return
            return _empty()
        idx = self._call
        self._call += 1
        async def _gen() -> AsyncIterator[StreamEvent]:
            for item in self._scripts[idx]:
                yield item
        return _gen()


# ── Fake 工具 ─────────────────────────────────────


class FakeEchoTool:
    read_only = True

    def name(self) -> str:
        return "echo"

    def description(self) -> str:
        return "fake echo"

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


class FakeWriteTool:
    read_only = False

    def name(self) -> str:
        return "fake_write"

    def description(self) -> str:
        return "fake write"

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        }

    async def execute(self, args: str) -> Result:
        import json

        data = json.loads(args)
        return Result(content=f"wrote: {data.get('path', '')}")


# ── 场景 A：多轮链路 (AC1) ──────────────────────


@pytest.mark.asyncio
async def test_multi_turn_loop():
    provider = FakeProvider()
    registry = Registry()
    registry.register(FakeEchoTool())
    registry.register(FakeWriteTool())

    provider.set_scripts([
        [  # 轮1：调 echo
            StreamEvent(tool_calls=[
                ToolCall(id="c1", name="echo", input='{"msg":"hello"}'),
            ]),
            StreamEvent(done=True),
        ],
        [  # 轮2：调 fake_write
            StreamEvent(tool_calls=[
                ToolCall(id="c2", name="fake_write", input='{"path":"/tmp/x"}'),
            ]),
            StreamEvent(done=True),
        ],
        [  # 轮3：纯文本完成
            StreamEvent(text="任务完成"),
            StreamEvent(done=True),
        ],
    ])

    agent = Agent(provider, registry)
    conv = Conversation()
    conv.add_user("test multi-turn")

    events: list[Event] = []
    async for ev in agent.run(conv, Mode.NORMAL):
        events.append(ev)

    iters = [e for e in events if e.iter > 0]
    tool_starts = [e for e in events if e.tool and e.tool.phase == Phase.START]
    texts = [e for e in events if e.text]
    done_events = [e for e in events if e.done]

    assert len(iters) == 3  # 3 轮迭代
    assert len(tool_starts) == 2  # echo + fake_write
    assert len(texts) >= 1  # 最终答复
    assert len(done_events) == 1


# ── 场景 B：迭代上限 (AC3) ──────────────────────


@pytest.mark.asyncio
async def test_max_iterations():
    provider = FakeProvider()
    registry = Registry()
    registry.register(FakeEchoTool())

    # 每轮都返回工具调用（永不停止）
    scripts: list[list[StreamEvent]] = []
    for _ in range(MAX_ITERATIONS + 5):
        scripts.append([
            StreamEvent(tool_calls=[
                ToolCall(id="c", name="echo", input='{"msg":"x"}'),
            ]),
            StreamEvent(done=True),
        ])
    provider.set_scripts(scripts)

    agent = Agent(provider, registry)
    conv = Conversation()
    conv.add_user("loop forever")

    events: list[Event] = []
    async for ev in agent.run(conv, Mode.NORMAL):
        events.append(ev)

    notices = [e for e in events if e.notice]
    assert len(notices) >= 1
    assert any(NOTICE_MAX_ITER in n.notice for n in notices)
    assert conv.last_role() == "assistant"


# ── 场景 C：连续未知工具 (AC4) ──────────────────


@pytest.mark.asyncio
async def test_unknown_tools_stop():
    provider = FakeProvider()
    registry = Registry()
    registry.register(FakeEchoTool())  # 只有 echo 已注册

    scripts: list[list[StreamEvent]] = []
    for _ in range(MAX_UNKNOWN_RUN + 2):
        scripts.append([
            StreamEvent(tool_calls=[
                ToolCall(id="c", name="nonexistent_tool", input="{}"),
            ]),
            StreamEvent(done=True),
        ])
    provider.set_scripts(scripts)

    agent = Agent(provider, registry)
    conv = Conversation()
    conv.add_user("bad tools")

    events: list[Event] = []
    async for ev in agent.run(conv, Mode.NORMAL):
        events.append(ev)

    notices = [e for e in events if e.notice]
    assert any(NOTICE_UNKNOWN_TOOLS in n.notice for n in notices)


@pytest.mark.asyncio
async def test_unknown_tools_reset():
    """混入已知工具后计数重置。"""
    provider = FakeProvider()
    registry = Registry()
    registry.register(FakeEchoTool())

    provider.set_scripts([
        [  # 轮1：未知
            StreamEvent(tool_calls=[
                ToolCall(id="c1", name="bad_tool", input="{}"),
            ]),
            StreamEvent(done=True),
        ],
        [  # 轮2：未知
            StreamEvent(tool_calls=[
                ToolCall(id="c2", name="bad_tool", input="{}"),
            ]),
            StreamEvent(done=True),
        ],
        [  # 轮3：已知工具——重置计数
            StreamEvent(tool_calls=[
                ToolCall(id="c3", name="echo", input='{"msg":"ok"}'),
            ]),
            StreamEvent(done=True),
        ],
        [  # 轮4-6：又连续未知
            StreamEvent(tool_calls=[
                ToolCall(id="c4", name="bad_tool", input="{}"),
            ]),
            StreamEvent(done=True),
        ],
        [  # 轮5
            StreamEvent(tool_calls=[
                ToolCall(id="c5", name="bad_tool", input="{}"),
            ]),
            StreamEvent(done=True),
        ],
        [  # 轮6
            StreamEvent(tool_calls=[
                ToolCall(id="c6", name="bad_tool", input="{}"),
            ]),
            StreamEvent(done=True),
        ],
        [  # 轮7：应停止
            StreamEvent(tool_calls=[
                ToolCall(id="c7", name="bad_tool", input="{}"),
            ]),
            StreamEvent(done=True),
        ],
    ])

    agent = Agent(provider, registry)
    conv = Conversation()
    conv.add_user("reset test")

    events: list[Event] = []
    async for ev in agent.run(conv, Mode.NORMAL):
        events.append(ev)

    # 应停在轮7（重置后：4,5,6 连续3轮未知 → 第7轮触发停止）
    notices = [e for e in events if e.notice]
    assert any(NOTICE_UNKNOWN_TOOLS in n.notice for n in notices)
    # 确认已知工具的执行重置了计数（否则会更早停止）
    tool_names = [e.tool.name for e in events if e.tool and e.tool.phase == Phase.START]
    assert "echo" in tool_names


# ── 场景 D：保序分批并发 (AC8) ──────────────────


@pytest.mark.asyncio
async def test_concurrent_batch():
    """连续只读并发执行，有副作用串行。"""
    registry = Registry()

    concurrent_count = 0
    max_concurrent = 0

    class ReadOnlyTool:
        read_only = True

        def name(self) -> str:
            return "ro"

        def description(self) -> str:
            return "ro"

        def parameters(self) -> dict:
            return {"type": "object", "properties": {}}

        async def execute(self, args: str) -> Result:
            nonlocal concurrent_count, max_concurrent
            concurrent_count += 1
            max_concurrent = max(max_concurrent, concurrent_count)
            await asyncio.sleep(0.05)  # 制造重叠
            concurrent_count -= 1
            return Result(content="ro done")

    class WriteTool:
        read_only = False

        def name(self) -> str:
            return "rw"

        def description(self) -> str:
            return "rw"

        def parameters(self) -> dict:
            return {"type": "object", "properties": {}}

        async def execute(self, args: str) -> Result:
            nonlocal concurrent_count
            assert concurrent_count == 0  # 写工具应在读完成后执行
            return Result(content="rw done")

    registry.register(ReadOnlyTool())
    registry.register(WriteTool())

    provider = FakeProvider()
    provider.set_scripts([[
        StreamEvent(tool_calls=[
            ToolCall(id="c1", name="ro", input="{}"),
            ToolCall(id="c2", name="ro", input="{}"),
            ToolCall(id="c3", name="rw", input="{}"),
        ]),
        StreamEvent(done=True),
    ]])

    agent = Agent(provider, registry)
    conv = Conversation()
    conv.add_user("batch test")

    events: list[Event] = []
    async for ev in agent.run(conv, Mode.NORMAL):
        events.append(ev)

    assert max_concurrent >= 2  # 两只读并发


# ── 场景 E：取消历史一致 (AC9) ──────────────────


@pytest.mark.asyncio
async def test_cancel_history_consistency():
    registry = Registry()

    class SlowTool:
        read_only = True

        def name(self) -> str:
            return "slow"

        def description(self) -> str:
            return "slow"

        def parameters(self) -> dict:
            return {"type": "object", "properties": {}}

        async def execute(self, args: str) -> Result:
            await asyncio.sleep(0.5)
            return Result(content="done")

    registry.register(SlowTool())

    provider = FakeProvider()
    provider.set_scripts([[
        StreamEvent(tool_calls=[
            ToolCall(id="c1", name="slow", input="{}"),
        ]),
        StreamEvent(done=True),
    ]])

    agent = Agent(provider, registry)
    conv = Conversation()
    conv.add_user("cancel test")
    cancel = asyncio.Event()

    # 启动后立刻取消
    events: list[Event] = []
    gen = agent.run(conv, Mode.NORMAL, cancel)

    # 拿到 iter 事件后取消
    async for ev in gen:
        events.append(ev)
        if ev.iter > 0:
            cancel.set()

    # 历史应配对合法
    assert conv.last_role() == "assistant"
    # 应有 tool_results
    has_tool = any(m.role == "tool" for m in conv.messages)
    assert has_tool or any(
        NOTICE_CANCELLED in m.content for m in conv.messages
        if m.role == "assistant"
    )


# ── 场景 F：Plan Mode 工具集 (AC13) ──────────────


@pytest.mark.asyncio
async def test_plan_mode_tools():
    provider = FakeProvider()
    registry = Registry()
    registry.register(FakeEchoTool())  # read_only=True
    registry.register(FakeWriteTool())  # read_only=False

    provider.set_scripts([[
        StreamEvent(text="plan text"),
        StreamEvent(done=True),
    ]])

    agent = Agent(provider, registry)
    conv = Conversation()
    conv.add_user("plan test")

    async for _ in agent.run(conv, Mode.PLAN):
        pass

    # Plan mode 下只收到只读工具
    for tools_list in provider.calls_record:
        assert "echo" in tools_list
        assert "fake_write" not in tools_list
