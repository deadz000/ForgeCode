"""权限系统：五层防御流水线（黑名单→沙箱→规则→模式兜底→人在回路）。"""

from __future__ import annotations

from enum import IntEnum


class Mode(IntEnum):
    DEFAULT = 0
    ACCEPT_EDITS = 1
    PLAN = 2
    BYPASS = 3

    def __str__(self) -> str:
        return _MODE_STRS[self]

    def label(self) -> str:
        return _MODE_LABELS[self]


_MODE_STRS = {
    Mode.DEFAULT: "default",
    Mode.ACCEPT_EDITS: "acceptEdits",
    Mode.PLAN: "plan",
    Mode.BYPASS: "bypassPermissions",
}

_MODE_LABELS = {
    Mode.DEFAULT: "DEFAULT",
    Mode.ACCEPT_EDITS: "ACCEPT EDITS",
    Mode.PLAN: "PLAN",
    Mode.BYPASS: "BYPASS",
}


def parse_mode(s: str) -> tuple[Mode, bool]:
    """大小写不敏感识别四档名；未知返回 (Mode.DEFAULT, False)。"""
    s = s.lower()
    for m, name in _MODE_STRS.items():
        if name.lower() == s:
            return m, True
    return Mode.DEFAULT, False


class Decision(IntEnum):
    ALLOW = 0
    DENY = 1
    ASK = 2


class Category(IntEnum):
    READ = 0
    WRITE = 1
    EXEC = 2


class Outcome(IntEnum):
    DENY_ONCE = 0
    ALLOW_ONCE = 1
    ALLOW_FOREVER = 2


class ApprovalError(Exception):
    """权限判定异常（非致命，用于降级）。"""
    pass
