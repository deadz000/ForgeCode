"""对话管理：Message、Conversation、协议无关工具类型。"""

from __future__ import annotations

import copy
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

# ── 消息角色常量 ───────────────────────────────────

ROLE_USER: Literal["user"] = "user"
ROLE_ASSISTANT: Literal["assistant"] = "assistant"
ROLE_TOOL: Literal["tool"] = "tool"

# ── 工具相关类型 ───────────────────────────────────


@dataclass
class ToolCall:
    """模型发起的一次工具调用（流式拼接完成后，协议无关）。"""

    id: str  # provider 侧调用 id，回灌结果时配对
    name: str  # 工具名（注册中心按名查找）
    input: str  # 拼接完成的 JSON 参数字符串


@dataclass
class ToolResult:
    """工具执行结果（协议无关）。"""

    tool_call_id: str  # 对应 ToolCall.id
    content: str  # 执行产出
    is_error: bool = False


@dataclass
class ToolDefinition:
    """注册中心导出的工具定义（协议无关）。"""

    name: str
    description: str
    input_schema: dict[str, Any]  # JSON Schema: type/properties/required


# ── 消息 ───────────────────────────────────────────


@dataclass
class Message:
    """单条对话消息。"""

    role: Literal["user", "assistant", "tool"]
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)


# ── 对话 ───────────────────────────────────────────


class Conversation:
    """管理当前会话的消息列表（纯内存）。

    构造时可注入 on_append / on_replace 回调用于 JSONL 持久化。
    未注入回调时行为与之前版本完全一致。
    """

    def __init__(
        self,
        on_append: Callable[[Message], None] | None = None,
        on_replace: Callable[[list[Message]], None] | None = None,
    ) -> None:
        self._messages: list[Message] = []
        self._lock = threading.RLock()
        self._on_append = on_append
        self._on_replace = on_replace

    @classmethod
    def from_messages(
        cls,
        msgs: list[Message],
        on_append: Callable[[Message], None] | None = None,
        on_replace: Callable[[list[Message]], None] | None = None,
    ) -> Conversation:
        """从已有消息列表创建会话（恢复场景），可选回调。"""
        conv = cls(on_append=on_append, on_replace=on_replace)
        conv._messages = list(msgs)  # 浅拷贝消息列表
        return conv

    def add_user(self, text: str) -> None:
        """追加用户消息。"""
        msg: Message
        with self._lock:
            msg = Message(role=ROLE_USER, content=text)
            self._messages.append(msg)
        if self._on_append is not None:
            self._on_append(msg)

    def add_assistant(self, text: str) -> None:
        """追加 assistant 纯文本回合。"""
        msg: Message
        with self._lock:
            msg = Message(role=ROLE_ASSISTANT, content=text)
            self._messages.append(msg)
        if self._on_append is not None:
            self._on_append(msg)

    def add_assistant_with_tool_calls(self, text: str, calls: list[ToolCall]) -> None:
        """追加 assistant 工具调用回合。"""
        msg: Message
        with self._lock:
            msg = Message(
                role=ROLE_ASSISTANT,
                content=text,
                tool_calls=list(calls),
            )
            self._messages.append(msg)
        if self._on_append is not None:
            self._on_append(msg)

    def add_tool_results(self, results: list[ToolResult]) -> None:
        """追加工具结果回合。"""
        msg: Message
        with self._lock:
            msg = Message(role=ROLE_TOOL, tool_results=list(results))
            self._messages.append(msg)
        if self._on_append is not None:
            self._on_append(msg)

    def clear(self) -> None:
        """清空所有消息。"""
        with self._lock:
            self._messages.clear()

    def last_role(self) -> str:
        """返回最后一条消息的 role；空历史返回 ""。"""
        with self._lock:
            return self._messages[-1].role if self._messages else ""

    @property
    def messages(self) -> list[Message]:
        """返回当前所有消息的副本。"""
        with self._lock:
            return list(self._messages)

    def length(self) -> int:
        """返回当前消息条数。"""
        with self._lock:
            return len(self._messages)

    def replace_history(self, msgs: list[Message]) -> None:
        """把内存列表整体替换为传入的 msgs（深拷贝，不暴露引用）。"""
        with self._lock:
            self._messages = copy.deepcopy(msgs)
        if self._on_replace is not None:
            self._on_replace(list(self._messages))
