"""Team 共享任务列表：Task / Status / Filter / Patch / Store。

单文件 tasks.json（read-modify-write）+ 文件锁，跨进程与 in-process 共用。
"""

from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from forgecode.team.filelock import acquire
from forgecode.team.persistence import atomic_write_json, read_json


class Status(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"


@dataclass
class Task:
    id: str
    title: str
    description: str = ""
    status: Status = Status.PENDING
    assignee: str = ""
    blocked_by: list[str] = field(default_factory=list)
    blocks: list[str] = field(default_factory=list)
    created_at: int = 0
    updated_at: int = 0
    is_ready: bool = True  # 动态计算标记，不持久化

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "status": str(self.status),
            "assignee": self.assignee,
            "blocked_by": list(self.blocked_by),
            "blocks": list(self.blocks),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Task:
        st = data.get("status", "pending")
        try:
            s = Status(st)
        except ValueError:
            s = Status.PENDING
        return cls(
            id=str(data.get("id", "")),
            title=str(data.get("title", "")),
            description=str(data.get("description", "")),
            status=s,
            assignee=str(data.get("assignee", "")),
            blocked_by=list(data.get("blocked_by", []) or []),
            blocks=list(data.get("blocks", []) or []),
            created_at=int(data.get("created_at", 0)),
            updated_at=int(data.get("updated_at", 0)),
        )


@dataclass
class Filter:
    """任务列表过滤。"""

    status: str | None = None  # pending/in_progress/completed/blocked


@dataclass
class Patch:
    """任务更新字段。"""

    title: str | None = None
    description: str | None = None
    status: str | None = None
    assignee: str | None = None
    add_blocks: list[str] = field(default_factory=list)
    add_blocked_by: list[str] = field(default_factory=list)
    remove_blocks: list[str] = field(default_factory=list)
    remove_blocked_by: list[str] = field(default_factory=list)


class TaskNotFound(Exception):  # noqa: N818 — 文档 API 命名
    pass


class Store:
    """共享任务存储（spec F30）。"""

    def __init__(self, path: str) -> None:
        self._path = str(path)
        self._lock = asyncio.Lock()
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)

    def _lock_file(self) -> str:
        return self._path + ".lock"

    async def create(self, t: Task) -> str:
        """创建任务并返回 task_<6位hex> 的 id。"""
        t.id = f"task_{secrets.token_hex(3)}"
        async with self._lock:
            async with acquire(self._lock_file()):
                raw = _read_raw(self._path)
                tasks = [Task.from_dict(m) for m in raw["tasks"]]
                tasks.append(t)
                self._save(tasks)
        return t.id

    async def get(self, id_: str) -> Task:
        async with self._lock:
            async with acquire(self._lock_file()):
                raw = _read_raw(self._path)
                tasks = [Task.from_dict(m) for m in raw["tasks"]]
        for t in tasks:
            if t.id == id_:
                return t
        raise TaskNotFound(id_)

    async def list_(self, f: Filter) -> list[Task]:
        async with self._lock:
            async with acquire(self._lock_file()):
                raw = _read_raw(self._path)
                tasks = [Task.from_dict(m) for m in raw["tasks"]]
        if f.status:
            tasks = [t for t in tasks if t.status == f.status]
        for t in tasks:
            t.is_ready = self._is_ready(t, tasks)
        return tasks

    async def update(self, id_: str, p: Patch) -> None:
        async with self._lock:
            async with acquire(self._lock_file()):
                raw = _read_raw(self._path)
                tasks = [Task.from_dict(m) for m in raw["tasks"]]
                by_id = {t.id: t for t in tasks}
                if id_ not in by_id:
                    raise TaskNotFound(id_)
                t = by_id[id_]
                if p.title is not None:
                    t.title = p.title
                if p.description is not None:
                    t.description = p.description
                if p.status is not None:
                    try:
                        t.status = Status(p.status)
                    except ValueError:
                        t.status = Status.PENDING
                if p.assignee is not None:
                    t.assignee = p.assignee
                if p.add_blocks:
                    for bid in p.add_blocks:
                        if bid in by_id and bid != t.id and bid not in t.blocks:
                            t.blocks.append(bid)
                            if t.id not in by_id[bid].blocked_by:
                                by_id[bid].blocked_by.append(t.id)
                if p.add_blocked_by:
                    for bid in p.add_blocked_by:
                        if bid in by_id and bid != t.id and bid not in t.blocked_by:
                            t.blocked_by.append(bid)
                            if t.id not in by_id[bid].blocks:
                                by_id[bid].blocks.append(t.id)
                if p.remove_blocks:
                    for bid in p.remove_blocks:
                        if bid in t.blocks:
                            t.blocks.remove(bid)
                            if bid in by_id and t.id in by_id[bid].blocked_by:
                                by_id[bid].blocked_by.remove(t.id)
                if p.remove_blocked_by:
                    for bid in p.remove_blocked_by:
                        if bid in t.blocked_by:
                            t.blocked_by.remove(bid)
                            if bid in by_id and t.id in by_id[bid].blocks:
                                by_id[bid].blocks.remove(t.id)
                self._save(tasks)

    # ── 内部 ─────────────────────────────────────

    @staticmethod
    def _is_ready(t: Task, all_tasks: list[Task]) -> bool:
        """is_ready：无未完成的 blocker。"""
        by_id = {x.id: x for x in all_tasks}
        for bid in t.blocked_by:
            b = by_id.get(bid)
            if b is not None and b.status != Status.COMPLETED:
                return False
        return True

    def _save(self, tasks: list[Task]) -> None:
        atomic_write_json(self._path, {"tasks": [t.to_dict() for t in tasks]})


def _read_raw(path: str) -> dict[str, Any]:
    if not Path(path).exists():
        return {"tasks": []}
    try:
        raw = read_json(path)
    except (OSError, ValueError):
        return {"tasks": []}
    if not isinstance(raw, dict):
        return {"tasks": []}
    if not isinstance(raw.get("tasks"), list):
        raw["tasks"] = []
    return raw
