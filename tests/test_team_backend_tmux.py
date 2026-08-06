"""team.backend.tmux 单测：命令构造 + spawn/wake/kill 参数。"""

from __future__ import annotations

import sys

import pytest

from forgecode.team.backend import SpawnRequest
from forgecode.team.backend.tmux import TmuxBackend, build_member_cmd
from forgecode.team.types import BackendType


def _req(**over) -> SpawnRequest:
    base = dict(
        team_name="demo",
        member_name="alice",
        agent_id="agent-abc",
        worktree_path="/x/.forgecode/worktrees/team-demo+alice",
        session_dir="/x/.forgecode/sessions/s1",
        agent_type="general-purpose",
        model="",
        initial_prompt="do work",
        plan_mode_required=False,
    )
    base.update(over)
    return SpawnRequest(**base)


def test_build_member_cmd_contains_agent_id() -> None:
    cmd = build_member_cmd(_req())
    assert "--team-member" in cmd
    assert "--agent-id agent-abc" in cmd
    assert "--team demo" in cmd
    assert "--member alice" in cmd
    assert "--worktree" in cmd
    assert "--session-dir" in cmd
    assert sys.executable in cmd


def test_build_member_cmd_optional() -> None:
    cmd = build_member_cmd(_req(model="haiku", agent_type="worker", plan_mode_required=True))
    assert "--model haiku" in cmd
    assert "--agent-type worker" in cmd
    assert "--plan-mode" in cmd


def test_type() -> None:
    assert TmuxBackend().type() is BackendType.TMUX


async def test_spawn_inside_tmux(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TMUX", "sock")
    captured: list[list[str]] = []

    class _FakeProc:
        returncode = 0

        def __init__(self, args):
            captured.append(args)

        async def communicate(self):
            return b"%5\n", b""

    async def _fake_exec(*args, **kwargs):
        return _FakeProc(list(args))

    monkeypatch.setattr("forgecode.team.backend.tmux.asyncio.create_subprocess_exec", _fake_exec)
    pane_id, agent_id = await TmuxBackend().spawn(_req())
    assert pane_id == "%5"
    assert agent_id == "agent-abc"
    assert captured[0][0] == "tmux"
    assert captured[0][1] == "split-window"


async def test_spawn_outside_tmux(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TMUX", raising=False)
    captured: list[list[str]] = []

    class _FakeProc:
        returncode = 0

        def __init__(self, args):
            captured.append(list(args))

        async def communicate(self):
            return b"", b""

    async def _fake_exec(*args, **kwargs):
        return _FakeProc(args)

    monkeypatch.setattr("forgecode.team.backend.tmux.asyncio.create_subprocess_exec", _fake_exec)
    await TmuxBackend().spawn(_req())
    # 第一次 new-session，第二次 display-message
    assert captured[0][1] == "new-session"
    assert captured[1][1] == "display-message"
