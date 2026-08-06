"""team.spawn 单测：in-process 后端 spawn 全流程（AC7/AC25）。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from forgecode.agent.team_hook import TeamSpawnRequest
from forgecode.permission.engine import new_engine
from forgecode.subagent import Definition
from forgecode.task.manager import Manager as TaskManager
from forgecode.team import Manager as TeamManager
from forgecode.team.registry import AgentNameRegistry
from forgecode.team.types import BackendType
from forgecode.tool import new_default_registry
from forgecode.worktree import Manager as WorktreeManager


class _FakeCatalog:
    def __init__(self) -> None:
        self._def = Definition(
            name="general-purpose",
            description="general",
            max_turns=2,
        )

    def resolve(self, name: str) -> Definition | None:
        return self._def if name == "general-purpose" else None

    def fork_definition(self) -> Definition:
        return Definition(name="__fork__", description="fork")


class _FakeProvider:
    config = SimpleNamespace(model="test-model", context_window=100000)

    async def stream(self, req):
        return
        yield  # pragma: no cover


def _wire(git_repo: Path) -> tuple[TeamManager, TaskManager, WorktreeManager, AgentNameRegistry]:
    home = git_repo.parent / "home"
    tm = TaskManager()
    name_reg = AgentNameRegistry()
    tm.set_name_registry(name_reg)
    wt = WorktreeManager(str(git_repo))
    team_mgr = TeamManager(home, git_repo, wt, tm, name_reg)
    registry = new_default_registry()
    engine, _ = new_engine(str(git_repo))
    team_mgr.bind_spawn_deps(
        provider=_FakeProvider(),
        engine=engine,
        registry=registry,
        catalog=_FakeCatalog(),
        version="test",
        hook_engine=None,
        fork_enabled=False,
    )
    return team_mgr, tm, wt, name_reg


async def test_inprocess_spawn_full(git_repo: Path) -> None:
    team_mgr, tm, wt, name_reg = _wire(git_repo)
    team = await team_mgr.create("demo")
    assert team.backend is BackendType.IN_PROCESS

    text = await team_mgr.spawn_teammate(
        TeamSpawnRequest(
            team_name="demo",
            member_name="alice",
            agent_type="general-purpose",
            model="",
            prompt="写一个文件",
            plan_mode_required=False,
        )
    )
    import json

    payload = json.loads(text)
    assert payload["member_name"] == "alice"
    assert payload["backend"] == "in-process"
    assert payload["worktree"]  # worktree 已创建

    # members 落盘
    mem = team.member_by_name("alice")
    assert mem is not None
    assert mem.agent_id == payload["agent_id"]
    # worktree 目录存在（嵌套 slug → team-demo+alice）
    assert (Path(payload["worktree"]).is_dir())
    # 名称注册
    assert name_reg.resolve("alice") == payload["agent_id"]
    # 后台 task 用 agent_id 作为 id
    assert tm.get(payload["agent_id"]) is not None


async def test_spawn_member_name_conflict(git_repo: Path) -> None:
    team_mgr, _, _, _ = _wire(git_repo)
    await team_mgr.create("demo")
    await team_mgr.spawn_teammate(
        TeamSpawnRequest(team_name="demo", member_name="alice", agent_type="general-purpose", model="", prompt="x")
    )
    with pytest.raises(Exception):
        await team_mgr.spawn_teammate(
            TeamSpawnRequest(team_name="demo", member_name="alice", agent_type="general-purpose", model="", prompt="y")
        )


async def test_spawn_unknown_team(git_repo: Path) -> None:
    team_mgr, _, _, _ = _wire(git_repo)
    with pytest.raises(LookupError):
        await team_mgr.spawn_teammate(
            TeamSpawnRequest(team_name="ghost", member_name="a", agent_type="", model="", prompt="x")
        )


async def test_lifecycle_idle_and_resume(git_repo: Path) -> None:
    """AC17/AC18：spawn → 自然结束 → is_active=False + Lead idle 消息 → SendMessage 续派。"""
    team_mgr, tm, _, name_reg = _wire(git_repo)
    from forgecode.team.types import TeammateInfo

    # 注册 on_task_done（main.py wire 等价物）
    async def _on_done(task_id: str) -> None:
        await team_mgr.handle_task_done(task_id)

    tm.on_task_done(_on_done)

    team = await team_mgr.create("demo")
    text = await team_mgr.spawn_teammate(
        TeamSpawnRequest(
            team_name="demo",
            member_name="alice",
            agent_type="general-purpose",
            model="",
            prompt="做点事",
        )
    )
    import json

    agent_id = json.loads(text)["agent_id"]

    # 等后台 task 自然完成 + on_task_done 回调执行
    for _ in range(200):
        mem = team.member_by_name("alice")
        if mem is not None and mem.is_active is False:
            break
        await asyncio.sleep(0.02)

    # is_active=False + Lead mailbox idle 消息
    mem = team.member_by_name("alice")
    assert mem is not None
    assert mem.is_active is False
    from forgecode.team.mailbox import Box

    box = Box(team.mailbox_dir)
    lead_msgs = await box.read("lead")
    assert any("idle" in m.summary for m in lead_msgs)

    # SendMessage 续派：alice 已 stop → 重新 Running
    from forgecode.team.tools import SendMessageTool

    team_mgr.active_team_name = "demo"
    sm = SendMessageTool(team_mgr)
    r = await sm.execute(json.dumps({"to": "alice", "summary": "再来", "message": "再做一件事"}))
    assert r.is_error is False
    assert tm.get(agent_id).status.name == "RUNNING"
    # 续派后 is_active 重新为 True
    assert team.member_by_name("alice").is_active is True
