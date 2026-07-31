"""会话列表扫描：列出有效会话，按修改时间倒序。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from forgecode.compact.state import parse_session_time


@dataclass
class SessionInfo:
    """会话列表中一项的摘要信息。"""

    id: str  # session ID（目录名）
    title: str  # 第一条 user 消息内容（截断到 50 字符）
    modified_at: datetime  # 最后修改时间
    model: str  # 模型标签
    size: int  # JSONL 文件大小（字节）
    dir: str  # 会话目录绝对路径


def list_sessions(sessions_dir: str) -> list[SessionInfo]:
    """扫描 sessions_dir，返回按修改时间倒序排列的会话列表。

    只返回包含 conversation.jsonl 且 ID 能解析为新格式的目录。
    旧格式 session ID 的目录不展示。
    """
    sessions_path = Path(sessions_dir)
    if not sessions_path.is_dir():
        return []

    infos: list[SessionInfo] = []

    for child in sessions_path.iterdir():
        if not child.is_dir():
            continue

        # 尝试解析 session ID（新格式检查）
        parsed = parse_session_time(child.name)
        if parsed is None:
            continue  # 旧格式跳过

        jsonl_path = child / "conversation.jsonl"
        if not jsonl_path.is_file():
            continue

        # 读取第一条 user 消息的 content 作为标题
        title = ""
        model = ""
        try:
            stat = jsonl_path.stat()
            size = stat.st_size
            modified_at = datetime.fromtimestamp(stat.st_mtime)

            with open(jsonl_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    # 提取 model（从第一条含 model 字段的行）
                    if not model and isinstance(data.get("model"), str):
                        model = data["model"]
                    # 提取标题（从第一条 role=user 的行）
                    if data.get("role") == "user" and isinstance(data.get("content"), str):
                        title = data["content"]
                        break
        except OSError:
            continue

        # 截断标题
        if len(title) > 50:
            title = title[:47] + "..."

        infos.append(
            SessionInfo(
                id=child.name,
                title=title or "(空)",
                modified_at=modified_at,
                model=model or "?",
                size=size,
                dir=str(child),
            )
        )

    # 按修改时间倒序
    infos.sort(key=lambda x: x.modified_at, reverse=True)
    return infos
