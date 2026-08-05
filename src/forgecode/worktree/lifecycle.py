"""Worktree 生命周期：enter / exit / remove / auto_cleanup。

enter 不调 os.chdir；exit 的 os.chdir 仅作进程级 cwd 兜底（spec N4）。
git 慢操作一律放在锁外执行（spec N3：Manager 状态变更持锁，git 不持锁避免长锁）。
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import secrets
from pathlib import Path
from typing import TYPE_CHECKING

from forgecode.worktree.git import _has_worktree_changes, _run_git
from forgecode.worktree.manager import AutoCleanupReport, ExitOptions, ExitReport, WorktreeHasChangesError
from forgecode.worktree.session import WorktreeSession, save_session

if TYPE_CHECKING:
    from forgecode.worktree.manager import ExitAction, Manager


async def enter(manager: Manager, name: str) -> WorktreeSession:
    """进入 Worktree 会话（spec F11）。不调 os.chdir，进程 cwd 不变。"""
    async with manager.lock:
        wt = manager.active.get(name)
        if wt is None:
            raise ValueError(f"worktree 不存在: {name}")

    original_cwd = str(Path.cwd())
    try:
        original_branch = await _run_git(manager.repo_root, "rev-parse", "--abbrev-ref", "HEAD")
    except RuntimeError:
        original_branch = ""
    try:
        original_head = await _run_git(manager.repo_root, "rev-parse", "HEAD")
    except RuntimeError:
        original_head = ""

    session = WorktreeSession(
        original_cwd=original_cwd,
        worktree_path=wt.path,
        worktree_name=wt.name,
        original_branch=original_branch,
        original_head_commit=original_head,
        session_id=secrets.token_hex(8),
    )
    async with manager.lock:
        manager.current_session = session
        save_session(manager.session_file, session)
    return session


async def exit_(
    manager: Manager,
    name: str,
    action: ExitAction,
    opts: ExitOptions,
) -> ExitReport:
    """退出当前 Worktree 会话（spec F12）。仅允许退出当前 session。"""
    async with manager.lock:
        wt = manager.active.get(name)
        if wt is None:
            raise ValueError(f"worktree 不存在: {name}")
        session = manager.current_session
        if session is None or session.worktree_name != wt.name:
            raise ValueError(f"当前会话不属于 {name!r}，只能退出当前 Worktree")
        head_commit = wt.head_commit

    if action.value == "remove" and not opts.discard_changes:
        if await _has_worktree_changes(wt.path, head_commit):
            raise WorktreeHasChangesError(f"worktree {name} 有未提交修改或新 commit，拒绝删除")

    # os.chdir 兜底：防 session 期间 Bash 残留进程级 cwd（spec N4）
    with contextlib.suppress(OSError):
        os.chdir(session.original_cwd)

    if action.value == "remove":
        await _remove_wt(manager, wt.path, wt.branch, wt.name)

    async with manager.lock:
        manager.current_session = None
        save_session(manager.session_file, None)
        if action.value == "remove":
            manager.active.pop(name, None)

    return ExitReport(removed=action.value == "remove", path=wt.path, branch=wt.branch)


async def remove(manager: Manager, name: str, opts: ExitOptions) -> None:
    """独立删除入口（spec F13）：允许删除非当前 session 的 Worktree；变更保护同 exit。"""
    async with manager.lock:
        wt = manager.active.get(name)
        if wt is None:
            raise ValueError(f"worktree 不存在: {name}")
        head_commit = wt.head_commit

    if not opts.discard_changes:
        if await _has_worktree_changes(wt.path, head_commit):
            raise WorktreeHasChangesError(f"worktree {name} 有未提交修改或新 commit，拒绝删除")

    await _remove_wt(manager, wt.path, wt.branch, wt.name)

    async with manager.lock:
        manager.active.pop(name, None)


async def _remove_wt(manager: Manager, wt_path: str, branch: str, name: str) -> None:
    """执行 git worktree remove --force + 等 100ms 处理 lockfile 竞态 + 删分支（锁外）。"""
    await _run_git(manager.repo_root, "worktree", "remove", "--force", wt_path)
    await asyncio.sleep(0.1)
    await _run_git(manager.repo_root, "branch", "-D", branch)


async def auto_cleanup(manager: Manager, name: str) -> AutoCleanupReport:
    """SubAgent 退出时的自动清理（spec F14 / G9）。"""
    async with manager.lock:
        wt = manager.active.get(name)
        if wt is None:
            return AutoCleanupReport(kept=False)
        # 手动创建的 Worktree 永不自动清理
        if wt.manual:
            return AutoCleanupReport(kept=True, path=wt.path, branch=wt.branch)
        head_commit = wt.head_commit

    if await _has_worktree_changes(wt.path, head_commit):
        return AutoCleanupReport(kept=True, path=wt.path, branch=wt.branch)

    await remove(manager, name, ExitOptions(discard_changes=True))
    return AutoCleanupReport(kept=False)
