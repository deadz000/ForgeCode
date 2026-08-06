"""项目指令加载器：三层 FORGECODE.md 扫描 + @include 展开。

扫描顺序（高优先级在前）：
1. <project_root>/FORGECODE.md（项目级）
2. <project_root>/.forgecode/FORGECODE.md（项目配置级）
3. ~/.forgecode/FORGECODE.md（用户级）
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# 独占行 @include 语法：行首可选空白，然后 @include 空格 路径，行尾可选空白
_INCLUDE_RE = re.compile(r"^\s*@include\s+(.+?)\s*$")

# 二进制检测：前 512 字节包含 \x00
_BINARY_THRESHOLD = 512


@dataclass
class Loader:
    """三层 FORGECODE.md 加载器。

    project_root: 项目根目录绝对路径。
    user_home:   用户 home 目录，缺省 os.path.expanduser("~")。
    max_depth:   @include 最大嵌套深度（默认 5）。
    """

    project_root: str
    user_home: str = ""
    max_depth: int = 5

    def __post_init__(self) -> None:
        if not self.user_home:
            self.user_home = os.path.expanduser("~")

    # ── 公开接口 ──────────────────────────────────

    def load(self) -> str:
        """按优先级加载三层指令文件，返回拼接后的完整指令文本。

        加载失败的层静默跳过，全部为空返回空字符串。
        """
        parts: list[str] = []

        # ① 项目根 FORGECODE.md（最高优先级）
        project_root = str(Path(self.project_root).resolve())
        path1 = os.path.join(project_root, "FORGECODE.md")
        text1 = self._load_file(path1, boundary=project_root, depth=1, visited=set())
        if text1:
            parts.append(text1)

        # ② 项目配置级 .forgecode/FORGECODE.md
        path2 = os.path.join(project_root, ".forgecode", "FORGECODE.md")
        text2 = self._load_file(path2, boundary=project_root, depth=1, visited=set())
        if text2:
            parts.append(text2)

        # ③ 用户级 ~/.forgecode/FORGECODE.md（最低优先级）
        user_forge = os.path.join(self.user_home, ".forgecode")
        path3 = os.path.join(user_forge, "FORGECODE.md")
        text3 = self._load_file(path3, boundary=user_forge, depth=1, visited=set())
        if text3:
            parts.append(text3)

        return "\n\n".join(parts)

    # ── 内部实现 ──────────────────────────────────

    def _load_file(
        self,
        path: str,
        boundary: str,
        depth: int,
        visited: set[str],
    ) -> str:
        """加载单个文件，递归展开 @include 引用。

        Args:
            path:     文件绝对路径。
            boundary: 路径逃逸检测的根边界。
            depth:    当前嵌套层数（从 1 开始）。
            visited:  环路检测集合（已解析为绝对路径的文件集合）。

        Returns:
            展开后的文件内容；加载失败返回空字符串。
        """
        # 深度检查
        if depth > self.max_depth:
            abs_path = str(Path(path).resolve()) if os.path.exists(path) else path
            return f"<!-- @include 超过最大嵌套深度，已跳过: {abs_path} -->\n"

        # 解析绝对路径
        try:
            abs_path = str(Path(path).resolve())
        except (OSError, ValueError):
            abs_path = os.path.abspath(path)

        # 环路检测
        if abs_path in visited:
            return f"<!-- @include 检测到环路，已跳过: {abs_path} -->\n"

        # 路径逃逸检测
        try:
            boundary_resolved = str(Path(boundary).resolve())
            if not _is_under(abs_path, boundary_resolved):
                return f"<!-- @include 路径超出允许范围，已跳过: {abs_path} -->\n"
        except (OSError, ValueError):
            return f"<!-- @include 路径超出允许范围，已跳过: {abs_path} -->\n"

        # 文件不存在 → 静默跳过
        if not os.path.isfile(abs_path):
            return ""

        # 读取文件
        try:
            with open(abs_path, "rb") as f:
                raw = f.read()
        except OSError:
            logger.warning("无法读取指令文件: %s", abs_path, exc_info=True)
            return ""

        # 二进制检测
        if b"\x00" in raw[:_BINARY_THRESHOLD]:
            return f"<!-- @include 文件为二进制格式，已跳过: {abs_path} -->\n"

        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            logger.warning("指令文件非 UTF-8: %s", abs_path, exc_info=True)
            return ""

        # 空文件 → 空内容
        if not text.strip():
            return ""

        # 标记已访问，展开 @include
        visited.add(abs_path)
        new_boundary = str(Path(abs_path).parent)
        lines = text.split("\n")
        result_lines: list[str] = []

        for line in lines:
            m = _INCLUDE_RE.match(line)
            if m:
                rel = m.group(1).strip()
                # 解析被引用文件的绝对路径
                included_path = str(Path(new_boundary) / rel)
                included_text = self._load_file(
                    included_path,
                    boundary=boundary,
                    depth=depth + 1,
                    visited=visited,
                )
                result_lines.append(included_text.rstrip("\n"))
            else:
                result_lines.append(line)

        return "\n".join(result_lines)


def _is_under(path: str, parent: str) -> bool:
    """检查 path 是否在 parent 目录下（含相等）。"""
    try:
        p = Path(path)
        pp = Path(parent)
        # Path.is_relative_to (Python 3.9+)
        return p == pp or p.is_relative_to(pp)
    except (OSError, ValueError):
        # Windows 上不同盘符
        return False
