"""team.Manager 单测：create/get/delete + 成员操作 + 跨进程 reload。"""

from __future__ import annotations

from pathlib import Path

import pytest

from forgecode.team.manager import Manager
from forgecode.team.persistence import read_json
from forgecode.team.types import (
    MemberExistsError,
    TeamHasActiveMembersError,
    TeammateInfo,
)


@pytest.fixture
def mgr(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Manager:
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.delenv("TERM_PROGRAM", raising=False)
    home = tmp_path / "home"
    root = tmp_path / "root"
    root.mkdir()
    return Manager(home_dir=home, project_root=root)


def test_constructor_creates_dir(tmp_path: Path) -> None:
    home = tmp_path / "home"
    Manager(home_dir=home, project_root=tmp_path)
    assert (home / ".forgecode" / "teams").is_dir()


async def test_create_sanitizes(mgr: Manager) -> None:
    team = await mgr.create("refactor auth")
    assert team.sanitized_name == "refactor-auth"
    assert (mgr.teams_dir / "refactor-auth" / "config.json").is_file()
    data = read_json(team.config_path)
    assert data["sanitized_name"] == "refactor-auth"
    assert data["backend"] in ("tmux", "in-process", "iterm2")
    # Lead 已注册为第一个成员
    assert data["members"][0]["name"] == "lead"


async def test_create_suffix_on_conflict(mgr: Manager) -> None:
    await mgr.create("demo")
    team2 = await mgr.create("demo")
    assert team2.sanitized_name == "demo-2"


async def test_get_and_list(mgr: Manager) -> None:
    await mgr.create("alpha")
    await mgr.create("beta")
    assert mgr.get("alpha") is not None
    assert mgr.get("missing") is None
    names = [t.sanitized_name for t in mgr.list_()]
    assert names == ["alpha", "beta"]


async def test_delete_rejects_active(mgr: Manager) -> None:
    team = await mgr.create("demo")
    mem = TeammateInfo(name="alice", agent_id="agent-x", is_active=True)
    await mgr.add_member(team, mem)
    with pytest.raises(TeamHasActiveMembersError):
        await mgr.delete("demo", force=False)
    assert (mgr.teams_dir / "demo").is_dir()


async def test_delete_force_cleans(mgr: Manager) -> None:
    team = await mgr.create("demo")
    mem = TeammateInfo(
        name="alice",
        agent_id="agent-x",
        session_dir=str(mgr.teams_dir / "demo" / "sess"),
        worktree_path="",
        is_active=True,
    )
    (mgr.teams_dir / "demo" / "sess").mkdir(parents=True, exist_ok=True)
    await mgr.add_member(team, mem)
    await mgr.delete("demo", force=True)
    assert mgr.get("demo") is None
    assert not (mgr.teams_dir / "demo").exists()


async def test_member_crud_and_reload(mgr: Manager) -> None:
    team = await mgr.create("demo")
    await mgr.add_member(team, TeammateInfo(name="alice", agent_id="agent-1"))
    await mgr.set_member_active(team, "alice", False)
    data = read_json(team.config_path)
    assert data["members"][1]["is_active"] is False

    # 跨进程兜底：内存里没有 bob，disk 有 → set_member_active 走 reload 应成功
    await mgr.add_member(team, TeammateInfo(name="bob", agent_id="agent-2"))
    await mgr.set_member_active(team, "bob", False)
    assert team.member_by_name("bob") is not None
    assert team.member_by_name("bob").is_active is False


async def test_member_exists_error(mgr: Manager) -> None:
    team = await mgr.create("demo")
    await mgr.add_member(team, TeammateInfo(name="alice", agent_id="agent-1"))
    with pytest.raises(MemberExistsError):
        await mgr.add_member(team, TeammateInfo(name="alice", agent_id="agent-2"))


def test_scan_restores(tmp_path: Path) -> None:
    home = tmp_path / "home"
    root = tmp_path / "root"
    root.mkdir()
    m1 = Manager(home_dir=home, project_root=root)
    asyncio_run(m1.create("restore"))
    m2 = Manager(home_dir=home, project_root=root)
    assert m2.get("restore") is not None
    assert m2.get("restore").members[0].name == "lead"


def test_scan_skips_corrupt(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    home = tmp_path / "home"
    root = tmp_path / "root"
    root.mkdir()
    teams = home / ".forgecode" / "teams"
    teams.mkdir(parents=True)
    (teams / "bad").mkdir()
    (teams / "bad" / "config.json").write_text("{ not json", encoding="utf-8")
    m = Manager(home_dir=home, project_root=root)
    assert m.get("bad") is None
    assert "解析失败" in capsys.readouterr().err


async def test_kill_member(mgr: Manager) -> None:
    team = await mgr.create("demo")
    await mgr.add_member(team, TeammateInfo(name="alice", agent_id="agent-1"))
    ok = await mgr.kill_member("demo", "alice")
    assert ok is True
    assert team.member_by_name("alice") is None
    assert await mgr.kill_member("demo", "ghost") is False


def asyncio_run(coro):
    import asyncio

    return asyncio.run(coro)
