"""后台过期 Worktree 清理（sweep_stale）+ 临时 Worktree 随机命名。

三层过滤（spec F33）：
1. 名字匹配临时模式 ``agent-a[0-9a-f]{7}``
2. 目录 mtime 不晚于 cutoff；跳过当前 session 的目录
3. fail-closed 变更检查：有未提交修改或未推送 commit 都保留
"""

from __future__ import annotations

import re
import secrets
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from forgecode.worktree.git import _has_worktree_changes, _run_git

if TYPE_CHECKING:
    from forgecode.worktree.manager import Manager

EPHEMERAL_PATTERN = re.compile(r"^agent-a[0-9a-f]{7}$")


def random_agent_name() -> str:
    """生成 SubAgent 临时 Worktree 名字：agent-a + 7 位 hex。"""
    return "agent-a" + secrets.token_hex(4)[:7]


async def sweep_stale(manager: Manager, cutoff: datetime) -> list[str]:
    """清理超过 cutoff 的临时 Worktree（spec F33 / G10）。返回被删除的名字列表。"""
    from forgecode.worktree.manager import ExitOptions

    removed: list[str] = []
    worktree_dir = Path(manager.worktree_dir)
    if not worktree_dir.is_dir():
        return removed

    current_path = manager.current_session.worktree_path if manager.current_session else ""

    for p in worktree_dir.iterdir():
        if not p.is_dir():
            continue
        # 第一层：命名模式
        if not EPHEMERAL_PATTERN.fullmatch(p.name):
            continue
        # 第二层：时间过滤 + 跳过当前 session
        try:
            mtime = datetime.fromtimestamp(p.stat().st_mtime)
        except OSError:
            continue
        if mtime > cutoff:
            continue
        if str(p) == current_path:
            continue
        # 第三层：fail-closed 变更检查（有修改 / 未推送 commit 都保留）
        try:
            if await _has_worktree_changes(str(p), "HEAD"):
                continue
            unpushed = await _run_git(str(p), "rev-list", "--max-count=1", "HEAD", "--not", "--remotes")
            if unpushed:
                continue
        except Exception:
            continue
        await manager.remove(p.name, ExitOptions(discard_changes=True))
        removed.append(p.name)
    return removed
