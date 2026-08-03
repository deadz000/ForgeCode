"""ToolSpec 适配为 Tool：通过 asyncio 子进程执行专属脚本。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from forgecode.tool import DEFAULT_TIMEOUT, Result, _parse_args


class SkillTool:
    """Skill tool.json 声明的专属工具。"""

    read_only = False
    is_system = False

    def __init__(
        self,
        name: str,
        description: str,
        input_schema: dict,
        command: list[str],
        base_dir: Path,
    ) -> None:
        self._name = name
        self._description = description
        self._input_schema = input_schema
        self._command = command
        self._base_dir = base_dir

    def name(self) -> str:
        return self._name

    def description(self) -> str:
        return self._description

    def parameters(self) -> dict:
        return self._input_schema

    async def execute(self, args: str) -> Result:
        try:
            data = _parse_args(args)
        except ValueError as e:
            return Result(content=str(e), is_error=True)

        try:
            proc = await asyncio.create_subprocess_exec(
                *self._command,
                cwd=str(self._base_dir),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(input=json.dumps(data).encode("utf-8")),
                timeout=DEFAULT_TIMEOUT,
            )
        except TimeoutError:
            return Result(content=f"工具 {self._name} 执行超时（{DEFAULT_TIMEOUT}s）", is_error=True)
        except Exception as e:
            return Result(content=f"工具 {self._name} 执行失败: {e}", is_error=True)

        stdout = stdout_b.decode("utf-8", errors="replace").strip()
        stderr = stderr_b.decode("utf-8", errors="replace").strip()
        if proc.returncode != 0:
            content = f"exit_code: {proc.returncode}"
            if stdout:
                content += f"\nstdout:\n{stdout}"
            if stderr:
                content += f"\nstderr:\n{stderr}"
            return Result(content=content, is_error=True)
        return Result(content=stdout)


def new_skill_tool(
    name: str,
    description: str,
    input_schema: dict,
    command: list[str],
    base_dir: Path,
) -> SkillTool:
    return SkillTool(name, description, input_schema, command, base_dir)
