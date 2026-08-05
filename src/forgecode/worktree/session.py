"""WorktreeSession 数据结构与 JSON 持久化。

会话持久化到 ``<repo_root>/.forgecode/worktree_session.json``，
原子写（先写 tmp 再 os.replace），session=None 时写入 ``null``。
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class WorktreeSession:
    """记录当前活跃的 Worktree 会话（spec F3）。"""

    original_cwd: str
    worktree_path: str
    worktree_name: str
    original_branch: str
    original_head_commit: str
    session_id: str
    hook_based: bool = False

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, raw: str) -> WorktreeSession:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("worktree session JSON 必须是对象")
        return cls(**data)


def load_session(path: Path) -> WorktreeSession | None:
    """从文件加载 session。文件不存在 / 内容为 null / 空 → None；JSON 非法抛异常。"""
    if not Path(path).exists():
        return None
    raw = Path(path).read_text(encoding="utf-8").strip()
    if not raw or raw == "null":
        return None
    return WorktreeSession.from_json(raw)


def save_session(path: Path, session: WorktreeSession | None) -> None:
    """原子写 session。session=None 时写入 null（覆写为空 JSON null 字符串）。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = session.to_json() if session is not None else "null"
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def clear_session(path: Path) -> None:
    """清空 session（等同 save_session(path, None)）。"""
    save_session(path, None)
