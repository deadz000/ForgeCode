"""Team 持久化工具：sanitize、原子写 JSON、读 JSON、跨进程 reload。"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

# sanitize：只保留 [a-zA-Z0-9._-]，其他替换为 -，首尾去 -，空返回 ""
_SANITIZE_RE = re.compile(r"[^a-zA-Z0-9._-]+")


def sanitize(name: str) -> str:
    """把团队名转换为可安全用于路径的 slug。空字符串返回 ""。"""
    cleaned = _SANITIZE_RE.sub("-", name).strip("-")
    return cleaned


def atomic_write_json(path: str | Path, value: Any) -> None:
    """原子写 JSON：先写 <path>.tmp 再 os.replace。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)


def read_json(path: str | Path) -> Any:
    """读 JSON；文件不存在抛 FileNotFoundError。"""
    return json.loads(Path(path).read_text(encoding="utf-8"))


async def reload_from_disk_locked(team: Any) -> None:
    """跨进程并发兜底：从磁盘重读 members 覆盖到内存 Team。

    调用方须已持有 team._lock。磁盘读失败或结构非法时静默回退内存现状。
    """
    try:
        data = read_json(team.config_path)
    except (OSError, ValueError, json.JSONDecodeError):
        return
    members_raw = data.get("members", [])
    if not isinstance(members_raw, list):
        return
    from forgecode.team.types import TeammateInfo

    team.members = [TeammateInfo.from_dict(m) for m in members_raw]
