"""write_file 工具：写入（覆盖）文件。"""

from __future__ import annotations

from pathlib import Path

from forgecode.tool import Result, _parse_args


class WriteFileTool:
    """写入内容到文件，父目录不存在时自动创建。"""

    read_only = False
    is_system = False

    def name(self) -> str:
        return "write_file"

    def description(self) -> str:
        return "将内容写入指定文件（覆盖已有内容）。如果父目录不存在，会自动创建。"

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "要写入的文件路径",
                },
                "content": {
                    "type": "string",
                    "description": "要写入的文件内容",
                },
            },
            "required": ["path", "content"],
        }

    async def execute(self, args: str) -> Result:
        try:
            data = _parse_args(args)
        except ValueError as e:
            return Result(content=str(e), is_error=True)

        path_str = data.get("path")
        content = data.get("content")
        if not path_str:
            return Result(content="缺少必填参数: path", is_error=True)
        if content is None:
            return Result(content="缺少必填参数: content", is_error=True)

        path = Path(path_str)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        except OSError as e:
            return Result(content=f"写入文件失败: {e}", is_error=True)

        size = len(content.encode("utf-8"))
        return Result(content=f"已写入 {path}（{size} 字节）")
