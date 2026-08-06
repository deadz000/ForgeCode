"""邮箱 Box：文件锁保护的 read/write/mark_read。

每个收件人一个 <agent_id>.json + 同名 .lock，跨进程并发由文件锁串行。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from forgecode.team.filelock import acquire
from forgecode.team.mailbox.message import Message
from forgecode.team.persistence import atomic_write_json, read_json


class Box:
    """邮箱读写（spec F33）。"""

    def __init__(self, dir_: str) -> None:
        self._dir = str(dir_)
        Path(self._dir).mkdir(parents=True, exist_ok=True)

    def _file(self, agent_id: str) -> str:
        return str(Path(self._dir) / f"{agent_id}.json")

    def _lock(self, agent_id: str) -> str:
        return str(Path(self._dir) / f"{agent_id}.lock")

    async def write(self, agent_id: str, msg: Message) -> None:
        """追加一条消息（原子写）。timestamp 为 0 时自动设为当前时间。"""
        path = self._file(agent_id)
        lock_path = self._lock(agent_id)
        async with acquire(lock_path):
            if msg.timestamp == 0:
                msg.timestamp = int(time.time())
            raw = _read_messages_raw(path)
            raw["messages"].append(msg.to_dict())
            atomic_write_json(path, raw)

    async def read(self, agent_id: str) -> list[Message]:
        """返回该收件人全部消息。"""
        return await self._read_inner(agent_id)

    async def read_unread(self, agent_id: str) -> tuple[list[int], list[Message]]:
        """返回未读消息的 indices 与消息本身（不标记 read）。"""
        msgs = await self._read_inner(agent_id)
        idx = [i for i, m in enumerate(msgs) if not m.read]
        return idx, [msgs[i] for i in idx]

    async def mark_read(self, agent_id: str, indices: list[int]) -> None:
        """按 indices 把对应消息 read=True（原子写）。"""
        if not indices:
            return
        path = self._file(agent_id)
        lock_path = self._lock(agent_id)
        async with acquire(lock_path):
            raw = _read_messages_raw(path)
            idx_set = set(indices)
            for i, item in enumerate(raw["messages"]):
                if i in idx_set and isinstance(item, dict):
                    item["read"] = True
            atomic_write_json(path, raw)

    async def _read_inner(self, agent_id: str) -> list[Message]:
        """读消息：绕过锁（只读快照足够），文件不存在返回空列表。"""
        path = self._file(agent_id)
        if not Path(path).exists():
            return []
        try:
            raw = read_json(path)
        except (OSError, ValueError):
            return []
        messages = raw.get("messages", []) if isinstance(raw, dict) else []
        return [Message.from_dict(m) for m in messages if isinstance(m, dict)]


def _read_messages_raw(path: str) -> dict[str, Any]:
    """读 <dir>/<agent_id>.json；不存在或非法时视为空邮箱。"""
    if not Path(path).exists():
        return {"messages": []}
    try:
        raw = read_json(path)
    except (OSError, ValueError):
        return {"messages": []}
    if not isinstance(raw, dict):
        return {"messages": []}
    if not isinstance(raw.get("messages"), list):
        raw["messages"] = []
    return raw
