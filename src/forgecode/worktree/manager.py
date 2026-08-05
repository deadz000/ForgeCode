"""Worktree Manager：核心数据结构 + 构造 + 状态查询。

create / enter / exit / remove / auto_cleanup / sweep_stale 的具体实现
分别落在 create.py / lifecycle.py / sweep.py，Manager 方法体内延迟导入，
避免包内循环导入。
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from forgecode.worktree.git import _resolve_head_sha_from_fs
from forgecode.worktree.session import WorktreeSession, clear_session, load_session

DEFAULT_SYMLINK_DIRS: list[str] = ["node_modules", ".venv", "vendor"]

SweepResult = list[str]


@dataclass
class Worktree:
    """单个 Worktree 的元信息（spec F2）。"""

    name: str  # 原始 slug（可能含 /）
    path: str  # 绝对路径
    branch: str  # worktree-<flat_slug>
    based_on: str  # 创建时的 base 引用（HEAD / SHA）
    head_commit: str  # 创建时的 commit SHA
    created: datetime
    manual: bool  # True=用户手动创建（/worktree create 路径）


class ExitAction(StrEnum):
    KEEP = "keep"
    REMOVE = "remove"


@dataclass
class ExitOptions:
    discard_changes: bool = False


@dataclass
class ExitReport:
    removed: bool
    path: str
    branch: str


@dataclass
class AutoCleanupReport:
    kept: bool
    path: str = ""
    branch: str = ""


class WorktreeHasChangesError(Exception):
    """Worktree 有未提交修改或本地多于 base 的 commit。"""


class Manager:
    """封装 Worktree 完整生命周期管理（spec F4）。"""

    def __init__(self, repo_root: str, *, symlink_dirs: list[str] | None = None) -> None:
        self.repo_root = str(Path(repo_root).resolve())
        self.worktree_dir: Path = Path(self.repo_root) / ".forgecode" / "worktrees"
        self.session_file: Path = Path(self.repo_root) / ".forgecode" / "worktree_session.json"
        self.symlink_dirs: list[str] = symlink_dirs or DEFAULT_SYMLINK_DIRS
        self.lock = asyncio.Lock()
        self.active: dict[str, Worktree] = {}
        self._current_session: WorktreeSession | None = None

        # 校验 repo_root 是 git 仓库根目录；失败抛异常（启动方降级）
        self._verify_repo_root()

        self.worktree_dir.mkdir(parents=True, exist_ok=True)

        # 从 session_file 反序列化 current_session（允许文件不存在）
        try:
            session = load_session(self.session_file)
        except Exception as exc:
            print(f"Worktree: session 文件非法已清空: {exc}", file=sys.stderr)
            clear_session(self.session_file)
            session = None
        if session is not None and not Path(session.worktree_path).exists():
            print("Worktree: session worktree gone, cleared", file=sys.stderr)
            clear_session(self.session_file)
            session = None
        self._current_session = session

        # 扫描 worktree_dir 子目录还原 active（快速恢复，不调 git）
        if self.worktree_dir.is_dir():
            for p in self.worktree_dir.iterdir():
                if not p.is_dir():
                    continue
                head = _resolve_head_sha_from_fs(str(p))
                if head is None:
                    continue
                flat = p.name
                self.active[flat] = Worktree(
                    name=flat,
                    path=str(p),
                    branch=f"worktree-{flat}",
                    based_on="HEAD",
                    head_commit=head,
                    created=datetime.fromtimestamp(p.stat().st_mtime),
                    manual=True,
                )

    def _verify_repo_root(self) -> None:
        try:
            proc = subprocess.run(
                ["git", "-C", self.repo_root, "rev-parse", "--show-toplevel"],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as e:
            raise ValueError(f"git 不可用或无法访问仓库: {e}") from e
        if proc.returncode != 0:
            raise ValueError(f"{self.repo_root} 不是 git 仓库根目录")
        top = Path(proc.stdout.strip()).resolve()
        if top != Path(self.repo_root):
            raise ValueError(f"{self.repo_root} 不是 git 仓库根目录（根为 {top}）")

    # ── 状态查询 ──

    @property
    def current_session(self) -> WorktreeSession | None:
        """当前活跃的 Worktree 会话。"""
        return self._current_session

    @current_session.setter
    def current_session(self, session: WorktreeSession | None) -> None:
        self._current_session = session

    def list(self) -> list[Worktree]:
        """返回按 name 排序的 Worktree 列表。"""
        return sorted(self.active.values(), key=lambda w: w.name)

    def get(self, name: str) -> Worktree | None:
        return self.active.get(name)

    # ── 生命周期（实现见子模块，延迟导入避免循环依赖）──

    async def create(self, name: str, base_ref: str, manual: bool) -> Worktree:
        from forgecode.worktree.create import create

        return await create(self, name, base_ref, manual)

    async def enter(self, name: str) -> WorktreeSession:
        from forgecode.worktree.lifecycle import enter

        return await enter(self, name)

    async def exit(self, name: str, action: ExitAction, opts: ExitOptions) -> ExitReport:
        from forgecode.worktree.lifecycle import exit_

        return await exit_(self, name, action, opts)

    async def remove(self, name: str, opts: ExitOptions) -> None:
        from forgecode.worktree.lifecycle import remove

        return await remove(self, name, opts)

    async def auto_cleanup(self, name: str) -> AutoCleanupReport:
        from forgecode.worktree.lifecycle import auto_cleanup

        return await auto_cleanup(self, name)

    async def sweep_stale(self, cutoff: datetime) -> SweepResult:
        from forgecode.worktree.sweep import sweep_stale

        return await sweep_stale(self, cutoff)
