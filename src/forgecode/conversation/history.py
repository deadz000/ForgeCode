from dataclasses import dataclass


@dataclass
class Message:
    """单条对话消息。"""

    role: str  # "user" | "assistant"
    content: str


class Conversation:
    """管理当前会话的消息列表（纯内存）。"""

    def __init__(self) -> None:
        self._messages: list[Message] = []

    def add(self, role: str, content: str) -> None:
        """追加一条消息。"""
        self._messages.append(Message(role=role, content=content))

    def clear(self) -> None:
        """清空所有消息。"""
        self._messages.clear()

    @property
    def messages(self) -> list[Message]:
        """返回当前所有消息的副本。"""
        return list(self._messages)
