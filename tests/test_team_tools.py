"""team.tools 单测：TeamCreate/Delete + 协作工具（AC9-AC13）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from forgecode.team.manager import Manager
from forgecode.team.mailbox import Box
from forgecode.team.tasks import Store
from forgecode.team.tools import (
    SendMessageTool,
    TaskCreateTool,
    TaskGetTool,
    TaskListTool,
    TaskUpdateTool,
    TeamCreateTool,
    TeamDeleteTool,
)
from forgecode.team.types import TeammateInfo


@pytest.fixture
def mgr(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Manager:
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.delenv("TERM_PROGRAM", raising=False)
    home = tmp_path / "home"
    root = tmp_path / "root"
    root.mkdir()
    return Manager(home_dir=home, project_root=root)


async def _team_with_member(mgr: Manager) -> str:
    team = await mgr.create("demo")
    await mgr.add_member(team, TeammateInfo(name="alice", agent_id="agent-1", backend_type="in-process"))
    return team.sanitized_name


async def test_team_create_tool(mgr: Manager) -> None:
    tool = TeamCreateTool(mgr)
    r = await tool.execute(json.dumps({"team_name": "foo bar/baz"}))
    payload = json.loads(r.content)
    assert payload["team_name"] == "foo-bar-baz"
    assert mgr.get("foo-bar-baz") is not None
    assert mgr.active_team_name == "foo-bar-baz"


async def test_team_delete_tool(mgr: Manager) -> None:
    t = TeamCreateTool(mgr)
    await t.execute(json.dumps({"team_name": "demo"}))
    d = TeamDeleteTool(mgr)
    r = await d.execute(json.dumps({"team_name": "demo", "force": True}))
    assert json.loads(r.content)["deleted"] is True
    assert mgr.get("demo") is None


async def test_task_create_list_update(mgr: Manager) -> None:
    team_name = await _team_with_member(mgr)
    team = mgr.get(team_name)
    mgr.active_team_name = team_name

    tc = TaskCreateTool(mgr)
    r = await tc.execute(json.dumps({"title": "do x", "assignee": "alice"}))
    tid = json.loads(r.content)["task_id"]

    r2 = await tc.execute(json.dumps({"title": "blocker"}))
    bid = json.loads(r2.content)["task_id"]

    tu = TaskUpdateTool(mgr)
    await tu.execute(json.dumps({"task_id": tid, "add_blocked_by": [bid]}))

    tl = TaskListTool(mgr)
    r3 = await tl.execute("{}")
    tasks = json.loads(r3.content)
    by_id = {t["id"]: t for t in tasks}
    assert bid in by_id[tid]["blocked_by"]
    assert tid in by_id[bid]["blocks"]

    tg = TaskGetTool(mgr)
    r4 = await tg.execute(json.dumps({"task_id": tid}))
    assert json.loads(r4.content)["title"] == "do x"


async def test_task_list_status_filter(mgr: Manager) -> None:
    team_name = await _team_with_member(mgr)
    mgr.active_team_name = team_name
    tc = TaskCreateTool(mgr)
    await tc.execute(json.dumps({"title": "pending task"}))
    tl = TaskListTool(mgr)
    r = await tl.execute(json.dumps({"status": "pending"}))
    tasks = json.loads(r.content)
    assert len(tasks) == 1
    assert tasks[0]["is_ready"] is True


async def test_send_message_text(mgr: Manager) -> None:
    team_name = await _team_with_member(mgr)
    mgr.active_team_name = team_name
    sm = SendMessageTool(mgr)
    r = await sm.execute(json.dumps({"to": "alice", "summary": "hello", "message": "hi alice"}))
    payload = json.loads(r.content)
    assert payload["delivered_to"] == ["agent-1"]
    box = Box(mgr.get(team_name).mailbox_dir)
    msgs = await box.read("agent-1")
    assert len(msgs) == 1
    assert msgs[0].from_ == "lead"
    assert msgs[0].content == "hi alice"


async def test_send_message_broadcast(mgr: Manager) -> None:
    team_name = await _team_with_member(mgr)
    team = mgr.get(team_name)
    await mgr.add_member(team, TeammateInfo(name="bob", agent_id="agent-2", backend_type="in-process"))
    mgr.active_team_name = team_name
    sm = SendMessageTool(mgr)
    r = await sm.execute(json.dumps({"to": "*", "summary": "all", "message": "to everyone"}))
    payload = json.loads(r.content)
    assert set(payload["delivered_to"]) == {"agent-1", "agent-2"}
    box = Box(team.mailbox_dir)
    assert len(await box.read("agent-1")) == 1
    assert len(await box.read("agent-2")) == 1


async def test_send_message_bad_type_permission(mgr: Manager) -> None:
    team_name = await _team_with_member(mgr)
    mgr.active_team_name = team_name
    sm = SendMessageTool(mgr)
    r = await sm.execute(json.dumps({"to": "alice", "type": "shutdown_response", "summary": "x"}))
    assert r.is_error is True


async def test_send_message_plan_approval_lead_only(mgr: Manager) -> None:
    team_name = await _team_with_member(mgr)
    mgr.active_team_name = team_name
    sm = SendMessageTool(mgr)
    # Lead 发送允许
    r = await sm.execute(
        json.dumps({"to": "alice", "type": "plan_approval_response", "payload": {"approve": True}, "summary": "ok"})
    )
    assert r.is_error is False
