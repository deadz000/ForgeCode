"""worktree.sweep 单测：sweep_stale 三层过滤 + random_agent_name（spec F33/G10）。"""

from __future__ import annotations

import os
import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from forgecode.worktree import Manager
from forgecode.worktree.sweep import EPHEMERAL_PATTERN, random_agent_name


def _age_dir(p: Path, days: int = 3) -> None:
    """把目录 mtime 改成 N 天前，使其满足「旧目录才清理」的时间条件。"""
    ts = (datetime.now() - timedelta(days=days)).timestamp()
    os.utime(p, (ts, ts))


def test_ephemeral_pattern() -> None:
    assert EPHEMERAL_PATTERN.fullmatch("agent-a1234567")
    assert not EPHEMERAL_PATTERN.fullmatch("agent-a123456")
    assert not EPHEMERAL_PATTERN.fullmatch("agent-a12345678")
    assert not EPHEMERAL_PATTERN.fullmatch("manual-one")
    assert not EPHEMERAL_PATTERN.fullmatch("agent-b1234567")


def test_random_agent_name() -> None:
    assert re.fullmatch(r"agent-a[0-9a-f]{7}", random_agent_name())


@pytest.mark.asyncio
async def test_sweep_only_deletes_clean_ephemeral(git_repo_with_remote) -> None:
    repo = git_repo_with_remote
    m = Manager(str(repo))
    await m.create("agent-a1234567", "HEAD", manual=False)  # 干净临时 → 删
    _age_dir(repo / ".forgecode" / "worktrees" / "agent-a1234567")
    await m.create("agent-b1234567", "HEAD", manual=False)  # 有未提交修改 → 保留
    _age_dir(repo / ".forgecode" / "worktrees" / "agent-b1234567")
    (repo / ".forgecode" / "worktrees" / "agent-b1234567" / "mod.txt").write_text("x", encoding="utf-8")
    await m.create("manual-one", "HEAD", manual=True)  # 手动命名 → 不删
    _age_dir(repo / ".forgecode" / "worktrees" / "manual-one")

    removed = await m.sweep_stale(datetime.now() - timedelta(days=1))
    assert "agent-a1234567" in removed
    assert "agent-b1234567" not in removed
    assert "manual-one" not in removed
    assert not (repo / ".forgecode" / "worktrees" / "agent-a1234567").exists()
    assert (repo / ".forgecode" / "worktrees" / "agent-b1234567").exists()


@pytest.mark.asyncio
async def test_sweep_skips_fresh_mtime(git_repo_with_remote) -> None:
    """第二层：mtime > cutoff（新创建的目录）被跳过。"""
    repo = git_repo_with_remote
    m = Manager(str(repo))
    await m.create("agent-a1234567", "HEAD", manual=False)
    removed = await m.sweep_stale(datetime.now() - timedelta(days=1))  # 目录 mtime=now > cutoff
    assert removed == []


@pytest.mark.asyncio
async def test_sweep_skips_current_session(git_repo_with_remote) -> None:
    repo = git_repo_with_remote
    m = Manager(str(repo))
    await m.create("agent-a1234567", "HEAD", manual=False)
    _age_dir(repo / ".forgecode" / "worktrees" / "agent-a1234567")
    await m.enter("agent-a1234567")
    removed = await m.sweep_stale(datetime.now() - timedelta(days=1))
    assert "agent-a1234567" not in removed
