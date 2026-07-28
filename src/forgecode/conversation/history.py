"""对话管理：Message、Conversation、协议无关工具类型。"""

from __future__ import annotations

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
    """管理当前会话的消息列表（纯内存）。"""

    def __init__(self) -> None:
        self._messages: list[Message] = []

    def add_user(self, text: str) -> None:
        """追加用户消息。"""
        self._messages.append(Message(role=ROLE_USER, content=text))

    def add_assistant(self, text: str) -> None:
        """追加 assistant 纯文本回合。"""
        self._messages.append(Message(role=ROLE_ASSISTANT, content=text))

    def add_assistant_with_tool_calls(self, text: str, calls: list[ToolCall]) -> None:
        """追加 assistant 工具调用回合。"""
        self._messages.append(
            Message(
                role=ROLE_ASSISTANT,
                content=text,
                tool_calls=list(calls),
            )
        )

    def add_tool_results(self, results: list[ToolResult]) -> None:
        """追加工具结果回合。"""
        self._messages.append(Message(role=ROLE_TOOL, tool_results=list(results)))

    def clear(self) -> None:
        """清空所有消息。"""
        self._messages.clear()

    def last_role(self) -> str:
        """返回最后一条消息的 role；空历史返回 ""。"""
        return self._messages[-1].role if self._messages else ""

    @property
    def messages(self) -> list[Message]:
        """返回当前所有消息的副本。"""
        return list(self._messages)
