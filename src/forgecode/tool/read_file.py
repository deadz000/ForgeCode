"""read_file 工具：读取文件内容（带行号）。"""

from __future__ import annotations

from pathlib import Path

from forgecode.tool import Result, _parse_args, _truncate


class ReadFileTool:
    """读取文件内容，返回带行号的文本。"""

    read_only = True

    def name(self) -> str:
        return "read_file"

    def description(self) -> str:
        return (
            "读取指定文件的内容。返回带行号的文本，"
            "方便在后续操作中引用具体行号。"
            "文件不存在或不可读时返回错误信息。"
        )

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "要读取的文件路径（绝对路径或相对于工作目录的路径）",
                }
            },
            "required": ["path"],
        }

    async def execute(self, args: str) -> Result:
        try:
            data = _parse_args(args)
        except ValueError as e:
            return Result(content=str(e), is_error=True)

        path_str = data.get("path")
        if not path_str:
            return Result(content="缺少必填参数: path", is_error=True)

        path = Path(path_str)
        if not path.exists():
            return Result(content=f"文件不存在: {path}", is_error=True)
        if path.is_dir():
            return Result(content=f"路径是目录而非文件: {path}", is_error=True)

        try:
            text = path.read_text(encoding="utf-8")
        except PermissionError:
            return Result(content=f"无权限读取文件: {path}", is_error=True)
        except Exception as e:
            return Result(content=f"读取文件失败: {e}", is_error=True)

        # 加行号并截断
        lines = text.split("\n")
        numbered = [f"{i + 1:6d}\t{line}" for i, line in enumerate(lines)]
        result = "\n".join(numbered)
        result = _truncate(result, max_lines=2000, max_chars=256 * 1024)

        return Result(content=result)
