"""glob 工具：按模式查找文件。"""

from __future__ import annotations

import asyncio
from pathlib import Path

from forgecode.tool import Result, _parse_args


class GlobTool:
    """按 glob 模式匹配文件路径。"""

    read_only = True

    def name(self) -> str:
        return "glob"

    def description(self) -> str:
        return "按 glob 模式查找匹配的文件。支持 ** 递归匹配，如 **/*.py 查找所有 Python 文件。"

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "glob 模式，如 **/*.py、src/**/*.ts",
                },
                "path": {
                    "type": "string",
                    "description": "搜索根目录，默认为当前工作目录",
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

        root = Path(data.get("path") or ".")
        if not root.exists():
            return Result(content=f"目录不存在: {root}", is_error=True)

        matches: list[str] = []
        count = 0
        for p in root.glob(pattern):
            count += 1
            if p.is_file():
                matches.append(str(p))
            if count % 100 == 0:
                await asyncio.sleep(0)  # 让出 event loop

        matches.sort()
        if len(matches) > 100:
            matches = matches[:100]
            matches.append("[truncated: 仅显示前 100 条]")

        if not matches:
            return Result(content="无匹配文件")

        return Result(content="\n".join(matches))
