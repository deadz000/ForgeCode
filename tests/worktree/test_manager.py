"""worktree.Manager 单测：构造校验 / session 持久化 / 扫描还原（spec F4/F5）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from forgecode.worktree import Manager
from forgecode.worktree.session import WorktreeSession, save_session


def test_construct_rejects_non_git(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="git"):
        Manager(str(tmp_path))


def test_construct_creates_worktree_dir(git_repo) -> None:
    m = Manager(str(git_repo))
    assert (git_repo / ".forgecode" / "worktrees").is_dir()
    assert m.current_session is None
    assert m.list() == []


def test_construct_session_json_field_names(git_repo) -> None:
    """WorktreeSession JSON 序列化字段名为小写下划线。"""
    s = WorktreeSession(
        original_cwd="/a",
        worktree_path="/b",
        worktree_name="x",
        original_branch="main",
        original_head_commit="abc",
        session_id="s1",
    )
    raw = s.to_json()
    assert '"original_cwd"' in raw
    assert '"worktree_path"' in raw
    assert '"worktree_name"' in raw
    assert '"hook_based"' in raw
    assert "'original_cwd'" not in raw


def test_save_session_null(git_repo) -> None:
    from forgecode.worktree.session import load_session

    path = git_repo / ".forgecode" / "worktree_session.json"
    path.parent.mkdir(parents=True)
    save_session(path, None)
    assert load_session(path) is None
    assert path.read_text(encoding="utf-8").strip() == "null"


def test_load_existing_session(git_repo) -> None:
    wt_dir = git_repo / ".forgecode" / "worktrees" / "alice"
    wt_dir.mkdir(parents=True)
    s = WorktreeSession(
        original_cwd=str(git_repo),
        worktree_path=str(wt_dir),
        worktree_name="alice",
        original_branch="main",
        original_head_commit="abc",
        session_id="s1",
    )
    save_session(git_repo / ".forgecode" / "worktree_session.json", s)
    m = Manager(str(git_repo))
    assert m.current_session is not None
    assert m.current_session.worktree_name == "alice"
    assert m.current_session.worktree_path == str(wt_dir)


def test_session_gone_cleared_on_start(git_repo, capsys) -> None:
    s = WorktreeSession(
        original_cwd="",
        worktree_path=str(git_repo / "gone"),
        worktree_name="x",
        original_branch="",
        original_head_commit="",
        session_id="s",
    )
    save_session(git_repo / ".forgecode" / "worktree_session.json", s)
    m = Manager(str(git_repo))
    assert m.current_session is None
    assert "gone" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_scan_rebuilds_active(git_repo) -> None:
    """构造 Manager 后扫描 worktree_dir 还原 active（快速恢复）。"""
    m1 = Manager(str(git_repo))
    await m1.create("alice", "HEAD", manual=True)
    # 重新构造：扫描磁盘还原
    m2 = Manager(str(git_repo))
    assert m2.get("alice") is not None
    assert m2.get("alice").path == str(git_repo / ".forgecode" / "worktrees" / "alice")
