"""TUI 的 WorktreeAccessor 适配器：桥接 /worktree 命令与 worktree.Manager。

enter 时通过 set_active_cwd 回调把 ctx cwd 写到 ForgeApp.active_cwd，
主 Agent 下次 Run 用该 cwd 注入 ctx。
"""

from __future__ import annotations

from collections.abc import Callable

from forgecode.command.ui import WorktreeAccessor, WorktreeSummary
from forgecode.worktree import Manager
from forgecode.worktree.manager import ExitAction, ExitOptions


class WorktreeAdapter(WorktreeAccessor):
    """适配 worktree.Manager 实现 WorktreeAccessor 协议。"""

    def __init__(self, manager: Manager, set_active_cwd: Callable[[str], None]) -> None:
        self._manager = manager
        self._set_active_cwd = set_active_cwd

    async def create(self, name: str) -> tuple[str, str]:
        wt = await self._manager.create(name, "HEAD", manual=True)
        return wt.path, wt.branch

    def list(self) -> list[WorktreeSummary]:
        session = self._manager.current_session
        current = session.worktree_path if session else ""
        return [
            WorktreeSummary(
                name=w.name,
                path=w.path,
                branch=w.branch,
                active=(w.path == current),
                manual=w.manual,
            )
            for w in self._manager.list()
        ]

    async def enter(self, name: str) -> None:
        session = await self._manager.enter(name)
        self._set_active_cwd(session.worktree_path)

    async def exit(self, action: str, discard: bool) -> bool:
        session = self._manager.current_session
        if session is None:
            return False
        act = ExitAction.REMOVE if action == "remove" else ExitAction.KEEP
        report = await self._manager.exit(session.worktree_name, act, ExitOptions(discard_changes=discard))
        self._set_active_cwd("")  # 退出会话后回主目录 cwd
        return report.removed

    async def remove(self, name: str, discard: bool) -> None:
        await self._manager.remove(name, ExitOptions(discard_changes=discard))
