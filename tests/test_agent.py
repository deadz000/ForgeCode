"""Agent Loop 单测：多轮链路、停止条件、保序分批、Plan Mode、系统提示工程化。"""

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
    ToolCall,
)
from forgecode.providers import BaseProvider, Request, StreamEvent, Usage
from forgecode.tool import Registry, Result

# ── Fake Provider ─────────────────────────────────


class FakeProvider(BaseProvider):
    def __init__(self, model: str = "fake") -> None:
        from forgecode.config.schema import ProviderConfig

        self.config = ProviderConfig(
            name="fake",
            protocol="fake",
            model=model,
            base_url="",
            api_key="",
        )
        self._scripts: list[list[StreamEvent]] = []
        self._call = 0
        self.requests: list[Request] = []  # 记录每次 stream 收到的 Request

    def set_scripts(self, scripts: list[list[StreamEvent]]) -> None:
        self._scripts = scripts
        self._call = 0
        self.requests.clear()

    def stream(self, req: Request) -> AsyncIterator[StreamEvent]:
        self.requests.append(req)
        if self._call >= len(self._scripts):

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

    provider.set_scripts(
        [
            [  # 轮1：调 echo
                StreamEvent(
                    tool_calls=[
                        ToolCall(id="c1", name="echo", input='{"msg":"hello"}'),
                    ]
                ),
                StreamEvent(done=True),
            ],
            [  # 轮2：调 fake_write
                StreamEvent(
                    tool_calls=[
                        ToolCall(id="c2", name="fake_write", input='{"path":"/tmp/x"}'),
                    ]
                ),
                StreamEvent(done=True),
            ],
            [  # 轮3：纯文本完成
                StreamEvent(text="任务完成"),
                StreamEvent(done=True),
            ],
        ]
    )

    agent = Agent(provider, registry, "test")
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
        scripts.append(
            [
                StreamEvent(
                    tool_calls=[
                        ToolCall(id="c", name="echo", input='{"msg":"x"}'),
                    ]
                ),
                StreamEvent(done=True),
            ]
        )
    provider.set_scripts(scripts)

    agent = Agent(provider, registry, "test")
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
        scripts.append(
            [
                StreamEvent(
                    tool_calls=[
                        ToolCall(id="c", name="nonexistent_tool", input="{}"),
                    ]
                ),
                StreamEvent(done=True),
            ]
        )
    provider.set_scripts(scripts)

    agent = Agent(provider, registry, "test")
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

    provider.set_scripts(
        [
            [  # 轮1：未知
                StreamEvent(
                    tool_calls=[
                        ToolCall(id="c1", name="bad_tool", input="{}"),
                    ]
                ),
                StreamEvent(done=True),
            ],
            [  # 轮2：未知
                StreamEvent(
                    tool_calls=[
                        ToolCall(id="c2", name="bad_tool", input="{}"),
                    ]
                ),
                StreamEvent(done=True),
            ],
            [  # 轮3：已知工具——重置计数
                StreamEvent(
                    tool_calls=[
                        ToolCall(id="c3", name="echo", input='{"msg":"ok"}'),
                    ]
                ),
                StreamEvent(done=True),
            ],
            [  # 轮4-6：又连续未知
                StreamEvent(
                    tool_calls=[
                        ToolCall(id="c4", name="bad_tool", input="{}"),
                    ]
                ),
                StreamEvent(done=True),
            ],
            [
                StreamEvent(
                    tool_calls=[
                        ToolCall(id="c5", name="bad_tool", input="{}"),
                    ]
                ),
                StreamEvent(done=True),
            ],
            [
                StreamEvent(
                    tool_calls=[
                        ToolCall(id="c6", name="bad_tool", input="{}"),
                    ]
                ),
                StreamEvent(done=True),
            ],
            [  # 轮7：应停止
                StreamEvent(
                    tool_calls=[
                        ToolCall(id="c7", name="bad_tool", input="{}"),
                    ]
                ),
                StreamEvent(done=True),
            ],
        ]
    )

    agent = Agent(provider, registry, "test")
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
    provider.set_scripts(
        [
            [
                StreamEvent(
                    tool_calls=[
                        ToolCall(id="c1", name="ro", input="{}"),
                        ToolCall(id="c2", name="ro", input="{}"),
                        ToolCall(id="c3", name="rw", input="{}"),
                    ]
                ),
                StreamEvent(done=True),
            ]
        ]
    )

    agent = Agent(provider, registry, "test")
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
    provider.set_scripts(
        [
            [
                StreamEvent(
                    tool_calls=[
                        ToolCall(id="c1", name="slow", input="{}"),
                    ]
                ),
                StreamEvent(done=True),
            ]
        ]
    )

    agent = Agent(provider, registry, "test")
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
        NOTICE_CANCELLED in m.content for m in conv.messages if m.role == "assistant"
    )


# ── 场景 F：Plan Mode 工具集 (AC13) ──────────────


@pytest.mark.asyncio
async def test_plan_mode_tools():
    provider = FakeProvider()
    registry = Registry()
    registry.register(FakeEchoTool())  # read_only=True
    registry.register(FakeWriteTool())  # read_only=False

    provider.set_scripts(
        [
            [
                StreamEvent(text="plan text"),
                StreamEvent(done=True),
            ]
        ]
    )

    agent = Agent(provider, registry, "test")
    conv = Conversation()
    conv.add_user("plan test")

    async for _ in agent.run(conv, Mode.PLAN):
        pass

    # Plan mode 下只收到只读工具
    for req in provider.requests:
        tool_names = [t.name for t in req.tools]
        assert "echo" in tool_names
        assert "fake_write" not in tool_names


# ═══════════════════════════════════════════════════
# T11 新增：系统提示工程化测试
# ═══════════════════════════════════════════════════


# ── G1：Request 系统提示装配 ─────────────────────


@pytest.mark.asyncio
async def test_request_system_assembly():
    """Request 中 system.stable 和 system.environment 均非空。"""
    provider = FakeProvider()
    registry = Registry()
    registry.register(FakeEchoTool())

    provider.set_scripts(
        [
            [
                StreamEvent(text="hello"),
                StreamEvent(done=True),
            ]
        ]
    )

    agent = Agent(provider, registry, "1.0")
    conv = Conversation()
    conv.add_user("test")

    async for _ in agent.run(conv, Mode.NORMAL):
        pass

    assert len(provider.requests) >= 1
    req = provider.requests[0]
    assert req.system.stable != "", "稳定系统提示不应为空"
    assert req.system.environment != "", "环境信息不应为空"
    assert "ForgeCode" in req.system.stable
    assert "1.0" in req.system.environment  # version


# ── G2：稳定系统提示跨模式一致 ───────────────────


@pytest.mark.asyncio
async def test_stable_system_cross_mode():
    """普通模式与规划模式 stable 相同（规划提醒已移出系统通道）。"""
    provider1 = FakeProvider()
    provider2 = FakeProvider()
    registry = Registry()
    registry.register(FakeEchoTool())
    registry.register(FakeWriteTool())

    provider1.set_scripts(
        [
            [
                StreamEvent(text="normal"),
                StreamEvent(done=True),
            ]
        ]
    )
    provider2.set_scripts(
        [
            [
                StreamEvent(text="plan"),
                StreamEvent(done=True),
            ]
        ]
    )

    agent1 = Agent(provider1, registry, "test")
    conv1 = Conversation()
    conv1.add_user("normal")
    async for _ in agent1.run(conv1, Mode.NORMAL):
        pass

    agent2 = Agent(provider2, registry, "test")
    conv2 = Conversation()
    conv2.add_user("plan")
    async for _ in agent2.run(conv2, Mode.PLAN):
        pass

    stable1 = provider1.requests[0].system.stable
    stable2 = provider2.requests[0].system.stable
    assert stable1 == stable2, "普通/规划模式 stable 应相同"


# ── G3：规划模式按轮次 reminder ──────────────────


@pytest.mark.asyncio
async def test_plan_reminder_per_iteration():
    """iter1 完整，iter2-4 精简，iter5 完整（间隔=4）。"""

    provider = FakeProvider()
    registry = Registry()
    registry.register(FakeEchoTool())

    # 需要足够多轮来观察模式
    scripts: list[list[StreamEvent]] = []
    for _ in range(10):
        scripts.append(
            [
                StreamEvent(
                    tool_calls=[
                        ToolCall(id="c", name="echo", input='{"msg":"x"}'),
                    ]
                ),
                StreamEvent(done=True),
            ]
        )
    provider.set_scripts(scripts)

    agent = Agent(provider, registry, "test")
    conv = Conversation()
    conv.add_user("plan multi-turn")

    # 跑几轮就取消
    cancel = asyncio.Event()
    count = 0
    async for ev in agent.run(conv, Mode.PLAN, cancel):
        if ev.iter > 0:
            count += 1
            if count >= 6:
                cancel.set()

    reminders = [req.reminder for req in provider.requests]
    # iter1: 完整
    assert "<system-reminder>" in reminders[0]
    assert len(reminders[0]) > 100  # 完整版较长

    # iter2: 精简（iter1 之后，iter2-1=1, 1%4!=0）
    if len(reminders) > 1:
        assert len(reminders[1]) < len(reminders[0])

    # iter5: 完整（(5-1)%4==0）
    if len(reminders) >= 5:
        assert len(reminders[4]) > len(reminders[1])  # 比精简版长

    # 普通模式无 reminder
    for req in provider.requests:
        if req.reminder:
            # 所有有 reminder 的都应该含 system-reminder 标签
            assert "<system-reminder>" in req.reminder


# ── G4：reminder 不写入持久历史 ──────────────────


@pytest.mark.asyncio
async def test_reminder_not_in_history():
    """reminder 注入后不污染 conv 持久历史。"""
    provider = FakeProvider()
    registry = Registry()
    registry.register(FakeEchoTool())

    provider.set_scripts(
        [
            [
                StreamEvent(text="plan output"),
                StreamEvent(done=True),
            ]
        ]
    )

    agent = Agent(provider, registry, "test")
    conv = Conversation()
    conv.add_user("plan test")

    async for _ in agent.run(conv, Mode.PLAN):
        pass

    # conv 历史中不应出现 reminder 文本
    for msg in conv.messages:
        assert "<system-reminder>" not in msg.content, (
            f"持久历史不应含 reminder 标签: {msg.content[:100]}"
        )


# ── G5：缓存用量透传 ─────────────────────────────


@pytest.mark.asyncio
async def test_cache_usage_passthrough():
    """fake 发送 Usage(cache_write/cache_read) → Event.usage 携带对应值。"""
    provider = FakeProvider()
    registry = Registry()
    registry.register(FakeEchoTool())

    cache_w, cache_r = 150, 200
    provider.set_scripts(
        [
            [
                StreamEvent(
                    usage=Usage(
                        input_tokens=100,
                        output_tokens=50,
                        cache_write=cache_w,
                        cache_read=cache_r,
                    ),
                ),
                StreamEvent(text="done"),
                StreamEvent(done=True),
            ]
        ]
    )

    agent = Agent(provider, registry, "test")
    conv = Conversation()
    conv.add_user("cache test")

    usage_events: list[Usage] = []
    async for ev in agent.run(conv, Mode.NORMAL):
        if ev.usage is not None:
            usage_events.append(ev.usage)

    assert len(usage_events) >= 1
    u = usage_events[0]
    assert u.cache_write == cache_w
    assert u.cache_read == cache_r
    assert u.input_tokens == 100
    assert u.output_tokens == 50


# ── G6：环境信息在 Request 中独立于 stable ────────


@pytest.mark.asyncio
async def test_environment_separate_from_stable():
    """环境信息在 Request.system.environment 中，不在 stable 中。"""
    provider = FakeProvider()
    registry = Registry()
    registry.register(FakeEchoTool())

    provider.set_scripts(
        [
            [
                StreamEvent(text="ok"),
                StreamEvent(done=True),
            ]
        ]
    )

    agent = Agent(provider, registry, "2.0")
    conv = Conversation()
    conv.add_user("env test")

    async for _ in agent.run(conv, Mode.NORMAL):
        pass

    req = provider.requests[0]
    # environment 应独立
    assert req.system.environment != ""
    # stable 不应包含时变信息
    assert "2.0" not in req.system.stable  # version
    import os

    cwd = os.getcwd()
    if cwd:
        assert cwd not in req.system.stable, "stable 不应含工作目录"
