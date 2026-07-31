"""记忆存储：单级（项目级或用户级）笔记文件 CRUD + 索引维护。"""

from __future__ import annotations

import logging
import os
import threading
from datetime import UTC, datetime

from forgecode.memory.types import UpdateAction

logger = logging.getLogger(__name__)

# MEMORY.md 最大行数
MAX_INDEX_LINES = 200
# MEMORY.md 最大字节数
MAX_INDEX_BYTES = 25 * 1024

# ── YAML frontmatter 手写解析/生成 ──────────────────


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """解析 Markdown 文件的首段 YAML frontmatter。

    Returns:
        (frontmatter_dict, body) —— frontmatter 中各字段和去除 frontmatter 后的正文。
    """
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}, text

    end_idx: int | None = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break

    if end_idx is None:
        return {}, text

    fm: dict[str, str] = {}
    for line in lines[1:end_idx]:
        line = line.strip()
        if ":" in line:
            key, _, val = line.partition(":")
            fm[key.strip()] = val.strip()

    body = "\n".join(lines[end_idx + 1 :])
    return fm, body


def _write_frontmatter(fm: dict[str, str], body: str) -> str:
    """生成带 YAML frontmatter 的 Markdown 文本。"""
    lines = ["---"]
    for key, val in fm.items():
        lines.append(f"{key}: {val}")
    lines.append("---")
    lines.append("")
    lines.append(body.lstrip("\n"))
    return "\n".join(lines) + "\n"


# ── Store ──────────────────────────────────────────


class Store:
    """管理单级（项目级或用户级）的笔记文件和索引。"""

    def __init__(self, dir: str) -> None:
        self._dir = dir
        self._lock = threading.Lock()

    def ensure_dir(self) -> None:
        """创建目录（如不存在）。"""
        os.makedirs(self._dir, exist_ok=True)

    def load_index(self) -> str:
        """读取 MEMORY.md 内容；不存在返回空字符串。"""
        index_path = os.path.join(self._dir, "MEMORY.md")
        try:
            with open(index_path, encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            return ""
        except OSError:
            logger.warning("读取 MEMORY.md 失败: %s", index_path, exc_info=True)
            return ""

    def apply(self, actions: list[UpdateAction]) -> None:
        """执行 create / update / delete 操作。

        所有操作在锁内完成，保证并发安全。
        """
        with self._lock:
            self.ensure_dir()
            for action in actions:
                if action.action == "create":
                    self._create(action)
                elif action.action == "update":
                    self._update(action)
                elif action.action == "delete":
                    self._delete(action)

    # ── 内部操作 ──────────────────────────────────

    def _create(self, action: UpdateAction) -> None:
        """创建新笔记文件并在索引中追加一行。"""
        filename = action.filename or f"{action.type}_{action.slug}.md"
        filepath = os.path.join(self._dir, filename)

        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        body = _write_frontmatter(
            {
                "type": action.type,
                "title": action.title,
                "created": now,
                "updated": now,
            },
            action.content,
        )

        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(body)
        except OSError:
            logger.warning("创建笔记文件失败: %s", filepath, exc_info=True)
            return

        # 追加索引行（含文件名用于后续删除匹配）
        self._append_index_line(
            f"- [{action.type}] {action.title} — {_summary_line(action.content)} <!-- {filename} -->\n"
        )

    def _update(self, action: UpdateAction) -> None:
        """重写文件内容和 frontmatter（保留 created，更新 updated）。"""
        filepath = os.path.join(self._dir, action.filename)

        # 读取现有文件获取 created 时间
        try:
            with open(filepath, encoding="utf-8") as f:
                old_text = f.read()
        except FileNotFoundError:
            logger.warning("要更新的笔记不存在: %s", filepath)
            return
        except OSError:
            logger.warning("读取笔记文件失败: %s", filepath, exc_info=True)
            return

        old_fm, _ = _parse_frontmatter(old_text)
        created = old_fm.get("created", datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S+00:00"))
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S+00:00")

        body = _write_frontmatter(
            {
                "type": old_fm.get("type", action.type),
                "title": action.title or old_fm.get("title", ""),
                "created": created,
                "updated": now,
            },
            action.content,
        )

        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(body)
        except OSError:
            logger.warning("更新笔记文件失败: %s", filepath, exc_info=True)
            return

        # 更新索引中对应行
        self._update_index_line(action.filename, action.title, action.content)

    def _delete(self, action: UpdateAction) -> None:
        """删除笔记文件并移除索引中对应行。"""
        filepath = os.path.join(self._dir, action.filename)
        try:
            os.remove(filepath)
        except FileNotFoundError:
            pass
        except OSError:
            logger.warning("删除笔记文件失败: %s", filepath, exc_info=True)

        self._remove_index_line(action.filename)

    # ── 索引操作 ──────────────────────────────────

    def _index_path(self) -> str:
        return os.path.join(self._dir, "MEMORY.md")

    def _read_index_lines(self) -> list[str]:
        """读取 MEMORY.md 所有行；不存在返回空列表。"""
        try:
            with open(self._index_path(), encoding="utf-8") as f:
                return f.readlines()
        except FileNotFoundError:
            return []
        except OSError:
            logger.warning("读取 MEMORY.md 失败", exc_info=True)
            return []

    def _write_index_lines(self, lines: list[str]) -> None:
        """写回 MEMORY.md。"""
        try:
            with open(self._index_path(), "w", encoding="utf-8") as f:
                f.writelines(lines)
        except OSError:
            logger.warning("写入 MEMORY.md 失败", exc_info=True)

    def _append_index_line(self, line: str) -> None:
        """在 MEMORY.md 末尾追加一行。超出限制时淘汰旧条目。"""
        lines = self._read_index_lines()
        lines.append(line)
        # 行数限制
        while len(lines) > MAX_INDEX_LINES:
            lines.pop(0)
        # 字节数限制
        total = sum(len(ln) for ln in lines)
        while total > MAX_INDEX_BYTES and len(lines) > 1:
            total -= len(lines[0])
            lines.pop(0)
        self._write_index_lines(lines)

    def _update_index_line(self, filename: str, new_title: str, new_content: str) -> None:
        """更新 MEMORY.md 中指定文件名对应的摘要行。"""
        lines = self._read_index_lines()
        new_line = f"- [{new_title}] {_summary_line(new_content)} <!-- {filename} -->\n"
        updated = False
        for i, line in enumerate(lines):
            if filename in line:
                lines[i] = new_line
                updated = True
                break
        if not updated:
            lines.append(new_line)
        self._write_index_lines(lines)

    def _remove_index_line(self, filename: str) -> None:
        """从 MEMORY.md 中移除指定文件名对应的行。"""
        lines = self._read_index_lines()
        lines = [ln for ln in lines if filename not in ln]
        self._write_index_lines(lines)


def _summary_line(content: str) -> str:
    """从笔记内容生成一行摘要（取第一句，最长 80 字符）。"""
    # 取第一个句号、换行或 80 字符
    first = content.split(".")[0].split("\n")[0].strip()
    if len(first) > 80:
        first = first[:77] + "..."
    return first
