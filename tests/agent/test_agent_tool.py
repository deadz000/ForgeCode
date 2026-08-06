"""AgentTool 单测：参数校验 / 定义式 / 后台 / 嵌套阻断 / bg 开关。"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator

import pytest

from forgecode.agent import Agent
from forgecode.agent.agent_tool import AgentTool
from forgecode.agent.run_to_completion import IN_SUBAGENT
from forgecode.conversation.history import Conversation
from forgecode.permission import Outcome
from forgecode.permission.engine import new_engine
from forgecode.providers import BaseProvider, Request, StreamEvent
from forgecode.subagent import Definition, Source
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


class FakeTool:
    read_only = False

    def name(self) -> str:
        return "fake_tool"

    def description(self) -> str:
        return "fake"

    def parameters(self) -> dict:
        return {"type": "object", "properties": {}}

    async def execute(self, args: str) -> Result:
        return Result(content="fake-ok")


class MockCatalog:
    def __init__(self, defs: list[Definition]) -> None:
        self._defs = {d.name: d for d in defs}

    def resolve(self, name: str) -> Definition | None:
        return self._defs.get(name)

    def list(self):
        return list(self._defs.values())

    def fork_definition(self) -> Definition:
        return Definition(name="__fork__", description="fork", model="inherit")


class FakeTaskMgr:
    def __init__(self) -> None:
        self.launched: list[tuple[str, str]] = []

    async def launch(self, ag, conv, name, task):
        self.launched.append((name, task))
        return "task_0001"

    async def adopt_running(self, ag, conv, name, events, partial=None):
        return "task_0002"

    async def upgrade_approval(self, req):
        return Outcome.DENY_ONCE, True


def _explore_def() -> Definition:
    return Definition(
        name="Explore",
        description="explore",
        disallowed_tools=["write_file"],
        system_prompt="you are explore",
        source=Source.BUILTIN,
    )


def _make_parent(provider) -> Agent:
    reg = Registry()
    reg.register(FakeTool())
    return Agent(provider, reg, _test_engine(), "test")


def _make_tool(catalog, mgr, parent, bg_enabled: bool = True) -> AgentTool:
    tool = AgentTool(catalog, mgr, parent=parent, bg_enabled=bg_enabled)
    tool.bind_conv_source(lambda: Conversation())
    return tool


def _args(**kw) -> str:
    base = {"prompt": "p", "description": "d"}
    base.update(kw)
    return json.dumps(base)


@pytest.mark.asyncio
async def test_missing_prompt() -> None:
    tool = _make_tool(MockCatalog([_explore_def()]), FakeTaskMgr(), _make_parent(FakeProvider()))
    result = await tool.execute(json.dumps({"description": "d"}))
    assert result.is_error
    assert "缺少必填参数 prompt" in result.content


@pytest.mark.asyncio
async def test_unknown_subagent_type() -> None:
    tool = _make_tool(MockCatalog([]), FakeTaskMgr(), _make_parent(FakeProvider()))
    result = await tool.execute(_args(subagent_type="nope"))
    assert result.is_error
    assert "unknown subagent_type" in result.content


@pytest.mark.asyncio
async def test_defined_foreground_returns_text() -> None:
    provider = FakeProvider()
    provider.set_scripts([[StreamEvent(text="sub result"), StreamEvent(done=True)]])
    parent = _make_parent(provider)
    tool = _make_tool(MockCatalog([_explore_def()]), FakeTaskMgr(), parent)
    result = await tool.execute(_args(subagent_type="Explore"))
    assert not result.is_error
    assert result.content == "sub result"


@pytest.mark.asyncio
async def test_run_in_background() -> None:
    mgr = FakeTaskMgr()
    parent = _make_parent(FakeProvider())
    tool = _make_tool(MockCatalog([_explore_def()]), mgr, parent)
    result = await tool.execute(_args(subagent_type="Explore", run_in_background=True))
    assert not result.is_error
    data = json.loads(result.content)
    assert data["status"] == "async_launched"
    assert data["task_id"] == "task_0001"
    assert mgr.launched[0][0] == ""


@pytest.mark.asyncio
async def test_nesting_blocked_by_contextvar() -> None:
    tool = _make_tool(MockCatalog([_explore_def()]), FakeTaskMgr(), _make_parent(FakeProvider()))
    token = IN_SUBAGENT.set(True)
    try:
        result = await tool.execute(_args(subagent_type="Explore"))
    finally:
        IN_SUBAGENT.reset(token)
    assert result.is_error
    assert "subagent cannot spawn Agent" in result.content


@pytest.mark.asyncio
async def test_fork_boilerplate_blocked() -> None:
    from forgecode.agent.fork import FORK_BOILERPLATE

    conv = Conversation()
    conv.add_user(FORK_BOILERPLATE + "task")
    tool = AgentTool(MockCatalog([_explore_def()]), FakeTaskMgr(), parent=_make_parent(FakeProvider()))
    tool.bind_conv_source(lambda: conv)
    result = await tool.execute(_args())
    assert result.is_error
    assert "Fork subagent cannot spawn Agent" in result.content


@pytest.mark.asyncio
async def test_bg_disabled_rejects_background() -> None:
    tool = _make_tool(
        MockCatalog([_explore_def()]), FakeTaskMgr(), _make_parent(FakeProvider()), bg_enabled=False
    )
    result = await tool.execute(_args(subagent_type="Explore", run_in_background=True))
    assert result.is_error
    assert "background mode is disabled" in result.content


@pytest.mark.asyncio
async def test_fork_disabled_rejects_fork() -> None:
    tool = _make_tool(
        MockCatalog([_explore_def()]), FakeTaskMgr(), _make_parent(FakeProvider()), bg_enabled=False
    )
    result = await tool.execute(_args())  # 空 subagent_type → fork 路径（强制后台）
    assert result.is_error
    assert "background mode is disabled" in result.content


# ── Team spawn 分支（F24/F25）──────────────────────


class MockTeamHook:
    def __init__(self, spawn_result: str = '{"member_name":"alice"}') -> None:
        self.calls: list[dict] = []
        self._result = spawn_result
        self._ctx: tuple[str, str, bool] | None = None

    def set_context(self, member: str, agent_id: str, inproc: bool) -> None:
        self._ctx = (member, agent_id, inproc)

    async def spawn_teammate(self, req) -> str:
        self.calls.append(
            {
                "team_name": req.team_name,
                "member_name": req.member_name,
                "agent_type": req.agent_type,
                "prompt": req.prompt,
            }
        )
        return self._result


@pytest.mark.asyncio
async def test_team_name_routes_to_hook() -> None:
    hook = MockTeamHook()
    tool = AgentTool(
        MockCatalog([_explore_def()]),
        FakeTaskMgr(),
        parent=_make_parent(FakeProvider()),
        team_hook=hook,
    )
    tool.bind_conv_source(lambda: Conversation())
    result = await tool.execute(_args(subagent_type="Explore", name="alice", team_name="demo"))
    assert not result.is_error
    assert hook.calls[0]["team_name"] == "demo"
    assert hook.calls[0]["member_name"] == "alice"


@pytest.mark.asyncio
async def test_team_name_without_hook_errors() -> None:
    tool = _make_tool(MockCatalog([_explore_def()]), FakeTaskMgr(), _make_parent(FakeProvider()))
    result = await tool.execute(_args(team_name="demo"))
    assert result.is_error
    assert "team_hook 缺失" in result.content


@pytest.mark.asyncio
async def test_inprocess_teammate_cannot_spawn() -> None:
    from forgecode.agent.team_hook import TeammateContext, with_teammate_context

    hook = MockTeamHook()
    tool = AgentTool(
        MockCatalog([_explore_def()]),
        FakeTaskMgr(),
        parent=_make_parent(FakeProvider()),
        team_hook=hook,
    )
    tool.bind_conv_source(lambda: Conversation())

    async def _noop_read():
        return [], []

    async def _noop_mark(indices):
        pass

    tc = TeammateContext(
        team_name="demo",
        member_name="alice",
        agent_id="agent-1",
        backend_type="in-process",
        read_unread=_noop_read,
        mark_read=_noop_mark,
    )
    with with_teammate_context(tc):
        result = await tool.execute(_args(team_name="demo"))
    assert result.is_error
    assert "in-process 队员" in result.content
