"""worktree.lifecycle 单测：enter / exit / remove / auto_cleanup（spec F11-F14）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from forgecode.worktree import ExitAction, ExitOptions, Manager, WorktreeHasChangesError


@pytest.mark.asyncio
async def test_enter_does_not_change_cwd(git_repo) -> None:
    m = Manager(str(git_repo))
    await m.create("alice", "HEAD", manual=True)
    before = str(Path.cwd())
    session = await m.enter("alice")
    assert str(Path.cwd()) == before  # 不调 os.chdir
    assert session.worktree_path == str(git_repo / ".forgecode" / "worktrees" / "alice")
    assert session.session_id
    assert session.original_branch == "main"


@pytest.mark.asyncio
async def test_enter_persists_session(git_repo) -> None:
    m = Manager(str(git_repo))
    await m.create("alice", "HEAD", manual=True)
    await m.enter("alice")
    raw = (git_repo / ".forgecode" / "worktree_session.json").read_text(encoding="utf-8")
    assert '"worktree_name": "alice"' in raw


@pytest.mark.asyncio
async def test_enter_unknown_raises(git_repo) -> None:
    m = Manager(str(git_repo))
    with pytest.raises(ValueError, match="不存在"):
        await m.enter("nobody")


@pytest.mark.asyncio
async def test_exit_remove_blocks_on_changes(git_repo) -> None:
    m = Manager(str(git_repo))
    await m.create("alice", "HEAD", manual=True)
    await m.enter("alice")
    (git_repo / ".forgecode" / "worktrees" / "alice" / "mod.txt").write_text("x", encoding="utf-8")
    with pytest.raises(WorktreeHasChangesError):
        await m.exit("alice", ExitAction.REMOVE, ExitOptions())
    assert (git_repo / ".forgecode" / "worktrees" / "alice").exists()


@pytest.mark.asyncio
async def test_exit_remove_discard_deletes(git_repo) -> None:
    m = Manager(str(git_repo))
    await m.create("alice", "HEAD", manual=True)
    await m.enter("alice")
    (git_repo / ".forgecode" / "worktrees" / "alice" / "mod.txt").write_text("x", encoding="utf-8")
    report = await m.exit("alice", ExitAction.REMOVE, ExitOptions(discard_changes=True))
    assert report.removed is True
    assert not (git_repo / ".forgecode" / "worktrees" / "alice").exists()
    assert m.current_session is None


@pytest.mark.asyncio
async def test_exit_restores_cwd(git_repo, monkeypatch) -> None:
    m = Manager(str(git_repo))
    await m.create("alice", "HEAD", manual=True)
    session = await m.enter("alice")
    # 模拟 session 期间进程 cwd 被改到别处
    fake = git_repo / "somewhere"
    fake.mkdir()
    monkeypatch.chdir(fake)
    await m.exit("alice", ExitAction.KEEP, ExitOptions())
    assert str(Path.cwd()) == session.original_cwd


@pytest.mark.asyncio
async def test_exit_wrong_session_raises(git_repo) -> None:
    m = Manager(str(git_repo))
    await m.create("alice", "HEAD", manual=True)
    await m.create("bob", "HEAD", manual=True)
    await m.enter("alice")
    with pytest.raises(ValueError, match="只能退出"):
        await m.exit("bob", ExitAction.KEEP, ExitOptions())


@pytest.mark.asyncio
async def test_remove_allows_non_current_session(git_repo) -> None:
    m = Manager(str(git_repo))
    await m.create("alice", "HEAD", manual=True)
    await m.enter("alice")
    await m.create("bob", "HEAD", manual=True)  # 非当前 session 的 worktree
    await m.remove("bob", ExitOptions())
    assert m.get("bob") is None
    assert not (git_repo / ".forgecode" / "worktrees" / "bob").exists()


@pytest.mark.asyncio
async def test_auto_cleanup_manual_kept(git_repo) -> None:
    m = Manager(str(git_repo))
    await m.create("alice", "HEAD", manual=True)
    report = await m.auto_cleanup("alice")
    assert report.kept is True


@pytest.mark.asyncio
async def test_auto_cleanup_no_changes_removed(git_repo) -> None:
    m = Manager(str(git_repo))
    await m.create("agent-a1234567", "HEAD", manual=False)
    report = await m.auto_cleanup("agent-a1234567")
    assert report.kept is False
    assert not (git_repo / ".forgecode" / "worktrees" / "agent-a1234567").exists()


@pytest.mark.asyncio
async def test_auto_cleanup_with_changes_kept(git_repo) -> None:
    m = Manager(str(git_repo))
    await m.create("agent-a1234567", "HEAD", manual=False)
    (git_repo / ".forgecode" / "worktrees" / "agent-a1234567" / "mod.txt").write_text("x", encoding="utf-8")
    report = await m.auto_cleanup("agent-a1234567")
    assert report.kept is True
    assert report.path
    assert report.branch == "worktree-agent-a1234567"
