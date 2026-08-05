"""worktree.create 单测：创建 / 快速恢复 / 创建后设置 A/B/C/D（spec F6-F10）。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from forgecode.worktree import Manager
from forgecode.worktree.git import _run_git


@pytest.mark.asyncio
async def test_create_basic(git_repo) -> None:
    m = Manager(str(git_repo))
    wt = await m.create("alice", "HEAD", manual=True)
    assert wt.name == "alice"
    assert wt.branch == "worktree-alice"
    assert wt.manual is True
    assert Path(wt.path).is_dir()
    assert (Path(wt.path) / "README.md").exists()


@pytest.mark.asyncio
async def test_create_nested_slug(git_repo) -> None:
    m = Manager(str(git_repo))
    wt = await m.create("team/alice", "HEAD", manual=True)
    assert wt.branch == "worktree-team+alice"
    assert (git_repo / ".forgecode" / "worktrees" / "team+alice").is_dir()


@pytest.mark.asyncio
async def test_create_invalid_slug(git_repo) -> None:
    m = Manager(str(git_repo))
    with pytest.raises(ValueError):
        await m.create("../etc", "HEAD", manual=True)


@pytest.mark.asyncio
async def test_create_duplicate_raises(git_repo) -> None:
    m = Manager(str(git_repo))
    await m.create("alice", "HEAD", manual=True)
    with pytest.raises(ValueError, match="已存在"):
        await m.create("alice", "HEAD", manual=True)


@pytest.mark.asyncio
async def test_create_fast_recovery_no_git(git_repo, monkeypatch) -> None:
    """目录已存在且不在 active → 快速恢复，不调 git 子进程。"""
    m = Manager(str(git_repo))
    wt1 = await m.create("alice", "HEAD", manual=True)
    m.active.pop("alice", None)  # 模拟外部重建后的状态（active 不含该目录）

    async def _boom(*args, **kwargs):
        raise AssertionError("快速恢复路径不应调用 git")

    monkeypatch.setattr("forgecode.worktree.create._run_git", _boom)
    wt2 = await m.create("alice", "HEAD", manual=True)
    assert wt2.head_commit == wt1.head_commit
    assert wt2.path == wt1.path


@pytest.mark.asyncio
async def test_setup_a_copy_local_configs(git_repo) -> None:
    (git_repo / ".forgecode").mkdir()
    (git_repo / ".forgecode" / "settings.local.yaml").write_text("mode: acceptEdits\n", encoding="utf-8")
    m = Manager(str(git_repo))
    wt = await m.create("alice", "HEAD", manual=True)
    assert (Path(wt.path) / ".forgecode" / "settings.local.yaml").exists()


@pytest.mark.asyncio
async def test_setup_b_hooks(git_repo) -> None:
    (git_repo / ".husky").mkdir()
    (git_repo / ".husky" / "pre-commit").write_text("#!/bin/sh\n", encoding="utf-8")
    m = Manager(str(git_repo))
    wt = await m.create("alice", "HEAD", manual=True)
    hooks = await _run_git(wt.path, "config", "--get", "core.hooksPath")
    assert hooks == str(git_repo / ".husky")


@pytest.mark.skipif(
    sys.platform == "win32", reason="Windows 上创建目录 symlink 需要开发者模式/管理员权限"
)
@pytest.mark.asyncio
async def test_setup_c_symlink_large_dir(git_repo) -> None:
    (git_repo / "node_modules").mkdir()
    (git_repo / "node_modules" / "pkg").write_text("x", encoding="utf-8")
    m = Manager(str(git_repo))
    wt = await m.create("alice", "HEAD", manual=True)
    assert (Path(wt.path) / "node_modules").is_symlink()


@pytest.mark.asyncio
async def test_setup_d_worktreeinclude(git_repo) -> None:
    (git_repo / ".gitignore").write_text(".env\n", encoding="utf-8")
    (git_repo / ".env").write_text("SECRET=1\n", encoding="utf-8")
    (git_repo / ".worktreeinclude").write_text("*.env\n", encoding="utf-8")
    m = Manager(str(git_repo))
    wt = await m.create("alice", "HEAD", manual=True)
    assert (Path(wt.path) / ".env").exists()
