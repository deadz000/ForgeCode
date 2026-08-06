"""Hook 生命周期事件：11 个枚举成员 + 拦截类判定。"""

from __future__ import annotations

import enum


class Event(str, enum.Enum):  # noqa: UP042 — 文档指定 str+Enum 形态，反查 Event(s) 方便
    """11 个生命周期事件，枚举值对应 YAML 字面量。"""

    SESSION_START = "SessionStart"
    SESSION_END = "SessionEnd"
    SESSION_RESUME = "SessionResume"
    USER_PROMPT_SUBMIT = "UserPromptSubmit"
    STOP = "Stop"
    PRE_USER_MESSAGE = "PreUserMessage"
    PRE_TOOL_USE = "PreToolUse"
    POST_TOOL_USE = "PostToolUse"
    PRE_COMPACT = "PreCompact"
    POST_COMPACT = "PostCompact"
    NOTIFICATION = "Notification"


# 拦截类事件：hook 可表达拦截信号，不允许 async
BLOCKING_EVENTS: frozenset[Event] = frozenset({Event.PRE_TOOL_USE, Event.USER_PROMPT_SUBMIT})


def is_blocking(e: Event) -> bool:
    """该事件是否允许 hook 表达拦截信号。"""
    return e in BLOCKING_EVENTS


def parse_event(s: str) -> Event | None:
    """按 YAML 字面量解析事件名；未知返回 None。"""
    try:
        return Event(s)
    except ValueError:
        return None
