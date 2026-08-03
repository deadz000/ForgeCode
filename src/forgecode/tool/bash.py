"""bash 工具：执行 shell 命令。"""

from __future__ import annotations

import asyncio

from forgecode.tool import Result, _parse_args, _truncate


class BashTool:
    """执行 shell 命令，返回 stdout/stderr/exit_code。"""

    read_only = False
    is_system = False

    def name(self) -> str:
        return "bash"

    def description(self) -> str:
        return (
            "在工作目录下执行一个 shell 命令。"
            "返回标准输出、标准错误和退出码。"
            "命令执行受超时约束（默认 30 秒）。"
            "读文件、找文件、搜内容请优先用 read_file / glob / grep，"
            "不要用 bash 拼凑 cat / find / grep 命令来替代。"
        )

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "要执行的 shell 命令",
                }
            },
            "required": ["command"],
        }

    async def execute(self, args: str) -> Result:
        try:
            data = _parse_args(args)
        except ValueError as e:
            return Result(content=str(e), is_error=True)

        cmd = data.get("command")
        if not cmd:
            return Result(content="缺少必填参数: command", is_error=True)

        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_b, stderr_b = await proc.communicate()
        except Exception as e:
            return Result(content=f"命令执行失败: {e}", is_error=True)

        stdout = stdout_b.decode("utf-8", errors="replace")
        stderr = stderr_b.decode("utf-8", errors="replace")

        parts = [f"exit_code: {proc.returncode}"]
        if stdout:
            parts.append(f"stdout:\n{stdout}")
        if stderr:
            parts.append(f"stderr:\n{stderr}")

        result = "\n".join(parts)
        result = _truncate(result, max_lines=10000, max_chars=30000)

        # 非零退出不作为 is_error——结果回灌让模型自行判断
        return Result(content=result)
