"""会话写入器：JSONL 追加写入 + fsync 刷盘。"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass


@dataclass
class Entry:
    """JSONL 中一行的 dataclass 表示。"""

    role: str = ""  # "user" / "assistant" / "tool"
    content: str = ""
    tool_calls: list[dict] | None = None  # 仅 assistant
    tool_results: list[dict] | None = None  # 仅 tool
    ts: int = 0  # Unix 秒
    model: str | None = None  # 仅首条消息
    type: str | None = None  # "compact" 或省略


class Writer:
    """负责向 conversation.jsonl 追加写入。

    保证多协程/线程追加的原子性（用 threading.Lock）。
    每次 append 后 flush + fsync 刷盘。
    """

    def __init__(self, session_dir: str) -> None:
        os.makedirs(session_dir, exist_ok=True)
        self._path = os.path.join(session_dir, "conversation.jsonl")
        self._file = open(self._path, "ab")  # noqa: SIM115
        self._lock = threading.Lock()
        self._closed = False

    @property
    def path(self) -> str:
        """返回 writer 对应的 JSONL 文件绝对路径。"""
        return self._path

    @classmethod
    def open_existing(cls, session_dir: str) -> Writer:
        """以追加模式打开已有会话的 JSONL（不创建目录）。"""
        path = os.path.join(session_dir, "conversation.jsonl")
        writer = cls.__new__(cls)
        writer._path = path
        writer._file = open(path, "ab")  # noqa: SIM115
        writer._lock = threading.Lock()
        writer._closed = False
        return writer

    def _append_raw(self, data: dict) -> None:
        """底层追加：序列化 → 加锁 → 写入 → fsync → 解锁。"""
        line = json.dumps(data, ensure_ascii=False) + "\n"
        encoded = line.encode("utf-8")
        with self._lock:
            if self._closed:
                return
            self._file.write(encoded)
            self._file.flush()
            os.fsync(self._file.fileno())

    def append(self, msg, model: str = "", is_first: bool = False) -> None:
        """追加一条消息到 JSONL。

        Args:
            msg: Message 对象（来自 conversation.history）。
            model: 当前 provider 的模型名。
            is_first: 是否为首条消息（首条消息携带 model 字段）。
        """
        entry = Entry(
            role=msg.role,
            content=msg.content,
            tool_calls=_serialize_tool_calls(msg.tool_calls),
            tool_results=_serialize_tool_results(msg.tool_results),
            ts=int(time.time()),
            model=model if is_first else None,
        )
        self._append_raw(_entry_to_dict(entry))

    def write_compact_marker(self) -> None:
        """写入压缩标记行。"""
        self._append_raw({"type": "compact", "ts": int(time.time())})

    def append_all(self, msgs: list) -> None:
        """批量追加消息（压缩后回写），不带 model。"""
        for msg in msgs:
            self.append(msg, model="", is_first=False)

    def close(self) -> None:
        """关闭文件句柄。"""
        with self._lock:
            if not self._closed:
                self._file.close()
                self._closed = True

    def __enter__(self) -> Writer:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: F841
        self.close()


def _serialize_tool_calls(calls: list) -> list[dict] | None:
    """序列化 ToolCall 列表为 dict 列表。"""
    if not calls:
        return None
    result = []
    for c in calls:
        result.append(
            {
                "id": getattr(c, "id", ""),
                "name": getattr(c, "name", ""),
                "input": getattr(c, "input", ""),
            }
        )
    return result


def _serialize_tool_results(results: list) -> list[dict] | None:
    """序列化 ToolResult 列表为 dict 列表。"""
    if not results:
        return None
    out = []
    for r in results:
        out.append(
            {
                "tool_call_id": getattr(r, "tool_call_id", ""),
                "content": getattr(r, "content", ""),
                "is_error": getattr(r, "is_error", False),
            }
        )
    return out


def _entry_to_dict(entry: Entry) -> dict:
    """将 Entry 转为 dict，移除值为 None 的字段（紧凑输出）。"""
    d: dict = {"role": entry.role, "content": entry.content, "ts": entry.ts}
    if entry.tool_calls:
        d["tool_calls"] = entry.tool_calls
    if entry.tool_results:
        d["tool_results"] = entry.tool_results
    if entry.model is not None:
        d["model"] = entry.model
    if entry.type is not None:
        d["type"] = entry.type
    return d
