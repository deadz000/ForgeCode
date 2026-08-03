"""Hook 生命周期挂钩系统：事件总线 + 规则加载 + 动作执行。"""

from __future__ import annotations

from forgecode.hook.engine import DispatchResult, Engine
from forgecode.hook.event import BLOCKING_EVENTS, Event, is_blocking, parse_event
from forgecode.hook.loader import load
from forgecode.hook.rule import (
    Action,
    ActionType,
    CombineMode,
    Condition,
    HttpAction,
    Payload,
    PromptAction,
    Rule,
    ShellAction,
    SubagentAction,
)

__all__ = [
    "Action",
    "ActionType",
    "BLOCKING_EVENTS",
    "CombineMode",
    "Condition",
    "DispatchResult",
    "Engine",
    "Event",
    "HttpAction",
    "Payload",
    "PromptAction",
    "Rule",
    "ShellAction",
    "SubagentAction",
    "is_blocking",
    "load",
    "parse_event",
]
