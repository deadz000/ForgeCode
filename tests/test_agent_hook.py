"""Agent hook 集成测试：PreToolUse 拦截、PreUserMessage reminder 注入、Stop emit。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest

from forgecode.agent import Agent, Phase
from forgecode.conversation.history import Conversation, ToolCall
from forgecode.hook.engine import Engine as HookEngine
from forgecode.hook.event import Event as HookEvent
from forgecode.hook.rule import Action, ActionType, PromptAction, Rule, ShellAction
from forgecode.permission import Mode
from forgecode.permission.engine import Engine, new_engine
from forgecode.providers import BaseProvider, Request, StreamEvent
from forgecode.tool import Registry, Result


def _test_engine() -> Engine:
    import os

    e, _ = new_engine(os.getcwd())
    return e


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
        self.requests: list[Request] = []

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


def _pre_tool_use_block_rule(command: str, name: str = "block-write") -> Rule:
    return Rule(
        name=name,
        event=HookEvent.PRE_TOOL_USE,
        action=Action(type=ActionType.SHELL, shell=ShellAction(command=command)),
    )


def _win_path(p) -> str:
    return str(p).replace("\\", "/")


@pytest.mark.asyncio
async def test_hook_pre_tool_use_blocks():
    """PreToolUse 拦截 → 工具结果为 [hook <name>] reason，PhaseStart/End 仍 emit。"""
    provider = FakeProvider()
    registry = Registry()
    registry.register(FakeWriteTool())

    hk = HookEngine(
        [
            _pre_tool_use_block_rule(
                "python -c \"import sys; print('blocked by hook', file=sys.stderr); sys.exit(2)\""
            )
        ],
        ["x.yaml"],
    )
    provider.set_scripts(
        [
            [
                StreamEvent(
                    tool_calls=[
                        ToolCall(id="c1", name="fake_write", input='{"path":"/tmp/x"}'),
                    ]
                ),
                StreamEvent(done=True),
            ],
            [StreamEvent(text="明白了"), StreamEvent(done=True)],
        ]
    )

    agent = Agent(provider, registry, _test_engine(), "test", hook_engine=hk)
    conv = Conversation()
    conv.add_user("写一个文件")

    events = []
    async for ev in agent.run(conv, Mode.BYPASS):
        events.append(ev)

    tool_ends = [e for e in events if e.tool and e.tool.phase == Phase.END]
    assert len(tool_ends) >= 1
    blocked = [e for e in tool_ends if "[hook block-write]" in e.tool.result]
    assert blocked, "应存在被 hook 拦截的工具结果"
    assert "blocked by hook" in blocked[0].tool.result
    assert blocked[0].tool.is_error

    # 消息回灌后进入对话，内容含 [hook ...]
    from forgecode.conversation.history import ROLE_TOOL

    tool_msgs = [m for m in conv.messages if m.role == ROLE_TOOL]
    assert tool_msgs
    assert any("[hook block-write]" in r.content for m in tool_msgs for r in m.tool_results)


@pytest.mark.asyncio
async def test_hook_pre_user_message_injects_reminder():
    """PreUserMessage prompt → 下一次 _stream_once 的 reminder 含该文本。"""
    provider = FakeProvider()
    registry = Registry()
    hk = HookEngine(
        [
            Rule(
                name="zh",
                event=HookEvent.PRE_USER_MESSAGE,
                action=Action(type=ActionType.PROMPT, prompt=PromptAction(text="用 zh-CN 回复")),
            )
        ],
        ["x.yaml"],
    )
    provider.set_scripts([[StreamEvent(text="hi"), StreamEvent(done=True)]])
    agent = Agent(provider, registry, _test_engine(), "test", hook_engine=hk)
    conv = Conversation()
    conv.add_user("hello")

    async for _ in agent.run(conv, Mode.BYPASS):
        pass

    assert provider.requests
    assert "用 zh-CN 回复" in provider.requests[0].reminder


@pytest.mark.asyncio
async def test_hook_pending_reminder_in_first_request():
    """SessionStart 注入的 prompt 出现在首轮请求的 reminder。"""
    provider = FakeProvider()
    registry = Registry()
    provider.set_scripts([[StreamEvent(text="hi"), StreamEvent(done=True)]])
    agent = Agent(provider, registry, _test_engine(), "test")
    agent.runtime.append_reminders(["默认用 zh-CN 回复"])
    conv = Conversation()
    conv.add_user("hello")

    async for _ in agent.run(conv, Mode.BYPASS):
        pass

    assert provider.requests
    assert "默认用 zh-CN 回复" in provider.requests[0].reminder
    # 取出后清空
    assert agent.runtime.take_reminders() == []


@pytest.mark.asyncio
async def test_hook_stop_emitted(tmp_path):
    """Stop 事件在 Agent.run 自然停止时被 emit。"""
    provider = FakeProvider()
    registry = Registry()
    marker = tmp_path / "stop.txt"
    cmd = f'python -c "import pathlib; pathlib.Path(r\'{_win_path(marker)}\').write_text(\'stopped\')"'
    hk = HookEngine(
        [
            Rule(
                name="stop-marker",
                event=HookEvent.STOP,
                action=Action(type=ActionType.SHELL, shell=ShellAction(command=cmd)),
            )
        ],
        ["x.yaml"],
    )
    provider.set_scripts([[StreamEvent(text="done"), StreamEvent(done=True)]])
    agent = Agent(provider, registry, _test_engine(), "test", hook_engine=hk)
    conv = Conversation()
    conv.add_user("hi")

    async for _ in agent.run(conv, Mode.BYPASS):
        pass

    assert marker.exists(), "Stop hook 应已执行写 marker"


@pytest.mark.asyncio
async def test_hook_pre_tool_use_allow_passes():
    """PreToolUse 未拦截 → 工具正常执行。"""
    provider = FakeProvider()
    registry = Registry()
    registry.register(FakeWriteTool())
    # exit 0 → 放行
    hk = HookEngine(
        [_pre_tool_use_block_rule('python -c "pass"', name="pass-hook")],
        ["x.yaml"],
    )
    provider.set_scripts(
        [
            [
                StreamEvent(
                    tool_calls=[
                        ToolCall(id="c1", name="fake_write", input='{"path":"/tmp/x"}'),
                    ]
                ),
                StreamEvent(done=True),
            ],
            [StreamEvent(text="done"), StreamEvent(done=True)],
        ]
    )
    agent = Agent(provider, registry, _test_engine(), "test", hook_engine=hk)
    conv = Conversation()
    conv.add_user("test")

    async for ev in agent.run(conv, Mode.BYPASS):
        pass

    from forgecode.conversation.history import ROLE_TOOL

    tool_msgs = [m for m in conv.messages if m.role == ROLE_TOOL]
    assert tool_msgs
    results = [r for m in tool_msgs for r in m.tool_results]
    assert results and results[0].content == "wrote: /tmp/x"
    assert not results[0].is_error


@pytest.mark.asyncio
async def test_hook_reminder_cleared_after_take():
    """reminder 取出后被清空（N4 不残留）。"""
    provider = FakeProvider()
    registry = Registry()
    hk = HookEngine(
        [
            Rule(
                name="zh",
                event=HookEvent.PRE_USER_MESSAGE,
                action=Action(type=ActionType.PROMPT, prompt=PromptAction(text="inject-me")),
            )
        ],
        ["x.yaml"],
    )
    provider.set_scripts([[StreamEvent(text="hi"), StreamEvent(done=True)]])
    agent = Agent(provider, registry, _test_engine(), "test", hook_engine=hk)
    conv = Conversation()
    conv.add_user("hello")

    async for _ in agent.run(conv, Mode.BYPASS):
        pass

    assert agent.runtime.take_reminders() == []


# ── SessionRuntime.pending_reminders ─────────────────


def test_runtime_pending_reminders_append_take():
    """append_reminders 追加、take_reminders 取出并清空。"""
    from forgecode.agent.runtime import new_runtime

    rt = new_runtime(".")
    rt.append_reminders(["a", "b"])
    assert rt.take_reminders() == ["a", "b"]
    assert rt.take_reminders() == []


def test_runtime_reset_clears_reminders():
    """reset_for_new_session 清空 pending_reminders。"""
    from forgecode.agent.runtime import new_runtime
    from forgecode.compact.state import new_session_context

    rt = new_runtime(".")
    rt.append_reminders(["x"])
    rt.reset_for_new_session(new_session_context("."))
    assert rt.take_reminders() == []


def test_runtime_reset_calls_hook_engine_reset():
    """reset_for_new_session 会清空 hook 引擎的 only_once 集合。"""
    from forgecode.agent.runtime import new_runtime
    from forgecode.compact.state import new_session_context
    from forgecode.hook.rule import PromptAction

    rt = new_runtime(".")
    hk = HookEngine(
        [
            Rule(
                name="once",
                event=HookEvent.STOP,
                only_once=True,
                action=Action(type=ActionType.PROMPT, prompt=PromptAction(text="ONCE")),
            )
        ],
        ["x.yaml"],
    )
    rt.hook_engine = hk

    async def _dispatch_twice():
        await hk.dispatch(HookEvent.STOP, {"event": "Stop"})
        await hk.dispatch(HookEvent.STOP, {"event": "Stop"})

    asyncio.run(_dispatch_twice())
    assert hk._once_fired == {"once"}
    rt.reset_for_new_session(new_session_context("."))
    assert hk._once_fired == set()
