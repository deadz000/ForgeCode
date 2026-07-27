"""工具抽象：Tool Protocol、Result、Registry、6个核心工具。"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from forgecode.conversation.history import ToolDefinition

# ── 常量 ──────────────────────────────────────────

DEFAULT_TIMEOUT: float = 30.0  # 单个工具执行的默认超时秒数（不可配）


# ── 工具结果 ──────────────────────────────────────


@dataclass
class Result:
    """工具执行结果——永不以 Python 异常形式抛给上层。"""

    content: str
    is_error: bool = False


# ── 工具抽象 ──────────────────────────────────────


@runtime_checkable
class Tool(Protocol):
    """统一工具抽象（F1）。"""

    read_only: bool  # True=只读（可并发执行 & Plan Mode 放行）

    def name(self) -> str: ...
    def description(self) -> str: ...
    def parameters(self) -> dict[str, Any]: ...
    async def execute(self, args: str) -> Result: ...


# ── 辅助 ──────────────────────────────────────────


def _truncate(s: str, max_lines: int, max_chars: int) -> str:
    """超出上限尾部追加 [truncated] 标注。"""
    lines = s.split("\n")
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines.append("[truncated]")
        s = "\n".join(lines)
    if len(s) > max_chars:
        s = s[:max_chars] + "\n[truncated]"
    return s


def _parse_args(args: str) -> dict[str, Any]:
    """安全解析工具参数 JSON，空串归一为 {}。"""
    args = args.strip()
    if not args:
        return {}
    try:
        result = json.loads(args)
        if not isinstance(result, dict):
            raise ValueError("参数必须是 JSON 对象")
        return result
    except json.JSONDecodeError as e:
        raise ValueError(f"参数 JSON 解析失败: {e}")


# ── 注册中心 ──────────────────────────────────────


class Registry:
    """集中登记、按名查找、导出定义、按名执行。"""

    def __init__(self) -> None:
        self._order: list[str] = []
        self._tools: dict[str, Tool] = {}

    def register(self, t: Tool) -> None:
        name = t.name()
        if name in self._tools:
            raise ValueError(f"工具 '{name}' 已注册")
        self._order.append(name)
        self._tools[name] = t

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def definitions(self) -> list[ToolDefinition]:
        """按注册顺序导出所有工具定义（F3）。"""
        result: list[ToolDefinition] = []
        for name in self._order:
            tool = self._tools[name]
            result.append(
                ToolDefinition(
                    name=tool.name(),
                    description=tool.description(),
                    input_schema=tool.parameters(),
                )
            )
        return result

    def read_only_definitions(self) -> list[ToolDefinition]:
        """Plan Mode：只导出 read_only==True 的工具定义。"""
        result: list[ToolDefinition] = []
        for name in self._order:
            tool = self._tools[name]
            if getattr(tool, "read_only", False):
                result.append(
                    ToolDefinition(
                        name=tool.name(),
                        description=tool.description(),
                        input_schema=tool.parameters(),
                    )
                )
        return result

    def is_read_only(self, name: str) -> bool:
        """分批判定；未知工具返回 False。"""
        t = self.get(name)
        return t is not None and getattr(t, "read_only", False)

    async def execute(
        self, name: str, args: str, timeout: float = DEFAULT_TIMEOUT
    ) -> Result:
        """按名查找工具并执行，带超时保护。"""
        tool = self.get(name)
        if tool is None:
            return Result(
                content=f"未知工具: {name}",
                is_error=True,
            )
        try:
            return await asyncio.wait_for(tool.execute(args), timeout=timeout)
        except TimeoutError:
            return Result(
                content=f"工具 {name} 执行超时（{timeout}s）",
                is_error=True,
            )
        except Exception as e:
            return Result(
                content=f"工具 {name} 异常: {e}",
                is_error=True,
            )


# ── 默认注册 ──────────────────────────────────────


def new_default_registry() -> Registry:
    """构造并注册全部 6 个核心工具。"""
    from forgecode.tool.bash import BashTool
    from forgecode.tool.edit_file import EditFileTool
    from forgecode.tool.glob_tool import GlobTool
    from forgecode.tool.grep_tool import GrepTool
    from forgecode.tool.read_file import ReadFileTool
    from forgecode.tool.write_file import WriteFileTool

    registry = Registry()
    registry.register(ReadFileTool())
    registry.register(WriteFileTool())
    registry.register(EditFileTool())
    registry.register(BashTool())
    registry.register(GlobTool())
    registry.register(GrepTool())
    return registry
