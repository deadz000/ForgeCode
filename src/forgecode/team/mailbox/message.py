"""邮箱消息类型：Message / MessageType。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class MessageType(StrEnum):
    TEXT = "text"
    SHUTDOWN_REQUEST = "shutdown_request"
    SHUTDOWN_RESPONSE = "shutdown_response"
    PLAN_APPROVAL_RESPONSE = "plan_approval_response"


@dataclass
class Message:
    """一条邮箱消息（json key "from" 对应 from_ 字段）。"""

    from_: str
    to: str
    type: MessageType
    summary: str
    content: str = ""
    payload: dict[str, Any] | None = None
    timestamp: int = 0
    read: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "from": self.from_,
            "to": self.to,
            "type": str(self.type),
            "summary": self.summary,
            "content": self.content,
            "payload": self.payload,
            "timestamp": self.timestamp,
            "read": self.read,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Message:
        mtype = data.get("type", "text")
        try:
            mt = MessageType(mtype)
        except ValueError:
            mt = MessageType.TEXT
        return cls(
            from_=str(data.get("from", "")),
            to=str(data.get("to", "")),
            type=mt,
            summary=str(data.get("summary", "")),
            content=str(data.get("content", "")),
            payload=data.get("payload"),
            timestamp=int(data.get("timestamp", 0)),
            read=bool(data.get("read", False)),
        )
