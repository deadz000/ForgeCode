"""grep 工具：在文件内容中搜索。"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

from forgecode.tool import Result, _parse_args


class GrepTool:
    """在文件中搜索匹配正则表达式的内容。"""

    read_only = True

    def name(self) -> str:
        return "grep"

    def description(self) -> str:
        return (
            "在文件中搜索匹配正则表达式的内容。"
            "返回 file:line:content 格式的命中列表。"
        )

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Python 正则表达式搜索模式",
                },
                "path": {
                    "type": "string",
                    "description": "搜索根目录，默认为当前工作目录",
                },
                "glob": {
                    "type": "string",
                    "description": "文件名过滤 glob，如 *.py",
                },
            },
            "required": ["pattern"],
        }

    async def execute(self, args: str) -> Result:
        try:
            data = _parse_args(args)
        except ValueError as e:
            return Result(content=str(e), is_error=True)

        pattern = data.get("pattern")
        if not pattern:
            return Result(content="缺少必填参数: pattern", is_error=True)

        try:
            rx = re.compile(pattern)
        except re.error as e:
            return Result(content=f"正则非法: {e}", is_error=True)

        root = Path(data.get("path") or ".")
        file_glob = data.get("glob")

        hits: list[str] = []
        file_count = 0

        iterator = root.rglob(file_glob) if file_glob else root.rglob("*")
        for filepath in iterator:
            if not filepath.is_file():
                continue
            file_count += 1

            try:
                with open(filepath, encoding="utf-8", errors="replace") as f:
                    for lineno, line in enumerate(f, 1):
                        if len(hits) >= 100:
                            break
                        if len(line) > 1024 * 1024:
                            hits.append(
                                f"{filepath}:{lineno}:[该行过长，未完整搜索]"
                            )
                            continue
                        if rx.search(line):
                            hits.append(
                                f"{filepath}:{lineno}:{line.rstrip()}"
                            )
            except (OSError, UnicodeDecodeError):
                continue

            if file_count % 20 == 0:
                await asyncio.sleep(0)

            if len(hits) >= 100:
                break

        if len(hits) >= 100:
            hits.append("[truncated: 仅显示前 100 条命中]")

        if not hits:
            return Result(content="无命中")

        return Result(content="\n".join(hits))
