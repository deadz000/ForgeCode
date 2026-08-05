"""Worktree 隔离：Manager / Slug 校验 / 会话 / 生命周期 / 过期清理。"""

from forgecode.worktree.manager import (
    DEFAULT_SYMLINK_DIRS,
    AutoCleanupReport,
    ExitAction,
    ExitOptions,
    ExitReport,
    Manager,
    Worktree,
    WorktreeHasChangesError,
)
from forgecode.worktree.session import WorktreeSession, clear_session, load_session, save_session
from forgecode.worktree.slug import flat_slug, validate_slug
from forgecode.worktree.sweep import EPHEMERAL_PATTERN, random_agent_name

__all__ = [
    "DEFAULT_SYMLINK_DIRS",
    "EPHEMERAL_PATTERN",
    "AutoCleanupReport",
    "ExitAction",
    "ExitOptions",
    "ExitReport",
    "Manager",
    "Worktree",
    "WorktreeHasChangesError",
    "WorktreeSession",
    "clear_session",
    "flat_slug",
    "load_session",
    "random_agent_name",
    "save_session",
    "validate_slug",
]
