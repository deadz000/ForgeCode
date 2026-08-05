"""agent.agent_worktree 单测：_execute_with_worktree + build_worktree_notice（spec F21/F22）。"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator

import pytest

from forgecode.agent import Agent
from forgecode.agent.agent_tool import AgentTool
from forgecode.agent.agent_worktree import _execute_with_worktree, build_worktree_notice
from forgecode.conversation.history import Conversation
from forgecode.permission import Outcome
from forgecode.permission.engine import new_engine
from forgecode.providers import BaseProvider, Request, StreamEvent
from forgecode.subagent import Definition, Source
from forgecode.tool import Registry
from forgecode.worktree import Manager


def _engine():
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


class RecordingSubAgent:
    """记录 ctx cwd 与收到的 task，run_to_completion 直接返回文本。"""

    def __init__(self) -> None:
        self.recorded_cwd: str | None = None
        self.recorded_task: str = ""

    async def run_to_completion(self, conv, task, events=None) -> str:
        from forgecode.tool.ctx import cwd_from_ctx

        self.recorded_cwd = cwd_from_ctx()
        self.recorded_task = task
        return "sub agent result"


def _wt_definition() -> Definition:
    return Definition(
        name="wt-writer",
        description="worktree writer",
        isolation="worktree",
        system_prompt="write files",
        source=Source.PROJECT,
    )


def test_build_worktree_notice() -> None:
    notice = build_worktree_notice("/parent", "/parent/.forgecode/worktrees/agent-a1234567")
    assert "<worktree-context>" in notice
    assert "/parent" in notice
    assert "/parent/.forgecode/worktrees/agent-a1234567" in notice
    assert "</worktree-context>" in notice


@pytest.mark.asyncio
async def test_execute_with_worktree_injects_cwd_and_cleanups(git_repo) -> None:
    manager = Manager(str(git_repo))
    sub = RecordingSubAgent()
    conv = Conversation()
    final = await _execute_with_worktree(
        manager, _wt_definition(), sub, conv, "把 README 覆盖", asyncio.Queue()
    )
    assert final == "sub agent result"
    # ctx cwd 注入为 wt.path
    assert sub.recorded_cwd is not None
    assert ".forgecode" in sub.recorded_cwd and "worktrees" in sub.recorded_cwd
    assert "agent-a" in sub.recorded_cwd
    # worktree notice 拼到 task 前
    assert "<worktree-context>" in sub.recorded_task
    assert "把 README 覆盖" in sub.recorded_task
    # 无变更 → auto_cleanup 删除临时 worktree
    wt_dir = git_repo / ".forgecode" / "worktrees"
    remaining = [p for p in wt_dir.iterdir() if p.name.startswith("agent-a")] if wt_dir.is_dir() else []
    assert remaining == []


@pytest.mark.asyncio
async def test_execute_with_worktree_keeps_on_changes(git_repo) -> None:
    manager = Manager(str(git_repo))
    sub = RecordingSubAgent()
    conv = Conversation()

    async def _write_in_wt(conv, task, events=None) -> str:
        from forgecode.tool.ctx import cwd_from_ctx

        (__import__("pathlib").Path(cwd_from_ctx()) / "changed.txt").write_text("x", encoding="utf-8")
        return "did it"

    sub.run_to_completion = _write_in_wt  # type: ignore[method-assign]
    final = await _execute_with_worktree(manager, _wt_definition(), sub, conv, "改文件", None)
    assert "[Worktree 保留" in final
    # 有变更 → 目录保留
    wt_dir = git_repo / ".forgecode" / "worktrees"
    kept = [p for p in wt_dir.iterdir() if p.name.startswith("agent-a")] if wt_dir.is_dir() else []
    assert len(kept) == 1


@pytest.mark.asyncio
async def test_agent_tool_worktree_mgr_none_returns_error() -> None:
    provider = FakeProvider()
    provider.set_scripts([[StreamEvent(done=True)]])
    reg = Registry()
    from forgecode.tool.read_file import ReadFileTool

    reg.register(ReadFileTool())
    parent = Agent(provider, reg, _engine(), "test")
    tool = AgentTool(_MockCatalog([_wt_definition()]), _FakeTaskMgr(), parent=parent, worktree_mgr=None)
    tool.bind_conv_source(lambda: Conversation())
    result = await tool.execute(
        json.dumps({"prompt": "p", "description": "d", "subagent_type": "wt-writer"})
    )
    assert result.is_error
    assert "worktree manager not configured" in result.content


@pytest.mark.asyncio
async def test_agent_tool_isolation_forces_foreground(git_repo) -> None:
    """isolation:worktree + background=True → 强制前台（不 launch 后台任务）。"""
    provider = FakeProvider()
    provider.set_scripts([[StreamEvent(done=True)]])
    reg = Registry()
    from forgecode.tool.read_file import ReadFileTool

    reg.register(ReadFileTool())
    parent = Agent(provider, reg, _engine(), "test")
    mgr = _FakeTaskMgr()
    tool = AgentTool(
        _MockCatalog([_wt_definition()]),
        mgr,
        parent=parent,
        worktree_mgr=Manager(str(git_repo)),
    )
    tool.bind_conv_source(lambda: Conversation())
    result = await tool.execute(
        json.dumps(
            {"prompt": "p", "description": "d", "subagent_type": "wt-writer", "run_in_background": True}
        )
    )
    assert not result.is_error
    assert mgr.launched == []  # 强制前台，未走后台上路


class _MockCatalog:
    def __init__(self, defs):
        self._defs = {d.name: d for d in defs}

    def resolve(self, name):
        return self._defs.get(name)

    def list(self):
        return list(self._defs.values())

    def fork_definition(self):
        return Definition(name="__fork__", description="fork", model="inherit")


class _FakeTaskMgr:
    def __init__(self) -> None:
        self.launched: list[tuple[str, str]] = []

    async def launch(self, ag, conv, name, task):
        self.launched.append((name, task))
        return "task_0001"

    async def adopt_running(self, ag, conv, name, events, partial=None):
        return "task_0002"

    async def upgrade_approval(self, req):
        return Outcome.DENY_ONCE, True
