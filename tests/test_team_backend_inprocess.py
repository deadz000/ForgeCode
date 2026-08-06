"""team.backend.inprocess 单测：launch 复用 + task_id 统一。"""

from __future__ import annotations

import asyncio

from forgecode.team.backend import SpawnRequest
from forgecode.team.backend.inprocess import InProcessBackend
from forgecode.conversation.history import Conversation
from forgecode.task.manager import Manager as TaskManager


class _FakeSubAgent:
    async def run_to_completion(self, conv, task, events=None):
        return "done"


async def test_spawn_uses_agent_id_as_task_id() -> None:
    tm = TaskManager()
    be = InProcessBackend(task_mgr=tm)
    req = SpawnRequest(
        team_name="demo",
        member_name="bob",
        agent_id="agent-bob",
        worktree_path="/wt",
        session_dir="/sess",
        agent_type="",
        model="",
        initial_prompt="go",
        plan_mode_required=False,
        sub_agent=_FakeSubAgent(),
        conv=Conversation(),
        task_mgr=tm,
    )
    pane, agent_id = await be.spawn(req)
    assert pane == ""
    assert agent_id == "agent-bob"
    bt = tm.get("agent-bob")
    assert bt is not None
    assert bt.name == "bob"
    # 等任务跑完
    for _ in range(50):
        if bt.status.name != "RUNNING":
            break
        await asyncio.sleep(0.01)
    assert bt.status.name == "COMPLETED"
    assert bt.result == "done"


async def test_wake_is_noop() -> None:
    be = InProcessBackend(task_mgr=TaskManager())
    await be.wake("", "agent-1")


async def test_kill_stops_task() -> None:
    tm = TaskManager()

    class _Never:
        async def run_to_completion(self, conv, task, events=None):
            await asyncio.Event().wait()

    req = SpawnRequest(
        team_name="d",
        member_name="bob",
        agent_id="agent-kill",
        worktree_path="/wt",
        session_dir="/sess",
        agent_type="",
        model="",
        initial_prompt="go",
        plan_mode_required=False,
        sub_agent=_Never(),
        conv=Conversation(),
        task_mgr=tm,
    )
    be = InProcessBackend(task_mgr=tm)
    await be.spawn(req)
    bt = tm.get("agent-kill")
    assert bt.status.name == "RUNNING"
    await be.kill("", "agent-kill")
    for _ in range(50):
        if bt.status.name != "RUNNING":
            break
        await asyncio.sleep(0.01)
    assert bt.status.name == "CANCELLED"
