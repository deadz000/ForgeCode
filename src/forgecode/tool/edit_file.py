"""edit_file 工具：精确替换文件内容。"""

from __future__ import annotations

from pathlib import Path

from forgecode.tool import Result, _parse_args


class EditFileTool:
    """在文件中做唯一匹配替换。"""

    read_only = False
    is_system = False

    def name(self) -> str:
        return "edit_file"

    def description(self) -> str:
        return (
            "在文件中进行精确的字符串替换。"
            "old_string 必须在文件中恰好出现一次，"
            "否则返回含匹配次数的错误（模型可据此调整 old_string）。"
            "编辑前请先用 read_file 读取目标文件，确认 old_string 唯一。"
        )

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "要编辑的文件路径",
                },
                "old_string": {
                    "type": "string",
                    "description": "要被替换的原文片段（必须唯一匹配）",
                },
                "new_string": {
                    "type": "string",
                    "description": "替换后的新文片段",
                },
            },
            "required": ["path", "old_string", "new_string"],
        }

    async def execute(self, args: str) -> Result:
        try:
            data = _parse_args(args)
        except ValueError as e:
            return Result(content=str(e), is_error=True)

        path_str = data.get("path")
        old = data.get("old_string")
        new = data.get("new_string")
        if not path_str:
            return Result(content="缺少必填参数: path", is_error=True)
        if old is None:
            return Result(content="缺少必填参数: old_string", is_error=True)
        if new is None:
            return Result(content="缺少必填参数: new_string", is_error=True)

        path = Path(path_str)
        if not path.exists():
            return Result(content=f"文件不存在: {path}", is_error=True)
        if path.is_dir():
            return Result(content=f"路径是目录而非文件: {path}", is_error=True)

        try:
            content = path.read_text(encoding="utf-8")
        except Exception as e:
            return Result(content=f"读取文件失败: {e}", is_error=True)

        count = content.count(old)
        if count == 0:
            return Result(
                content="未找到匹配的内容——old_string 在文件中未出现，请检查拼写与空格。",
                is_error=True,
            )
        if count > 1:
            return Result(
                content=f"匹配到 {count} 处，old_string 不唯一。请提供更长上下文使其唯一。",
                is_error=True,
            )

        # count == 1：唯一替换
        new_content = content.replace(old, new, 1)
        try:
            path.write_text(new_content, encoding="utf-8")
        except OSError as e:
            return Result(content=f"写入文件失败: {e}", is_error=True)

        return Result(content=f"已编辑 {path}（1 处替换）")
