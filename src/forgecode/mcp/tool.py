"""MCP 工具适配：远端工具包装为 forgecode Tool 协议。"""

from __future__ import annotations

import asyncio
import re
import sys
from dataclasses import dataclass
from typing import Any, Protocol

import mcp.types as mtypes

from forgecode.tool import Result

# ── 常量 ──────────────────────────────────────────

CALL_TIMEOUT: float = 30.0
_VALID_NAME = re.compile(r"^[A-Za-z0-9_-]+$")
_non_text_warn_once: set[str] = set()

# ── CallerSession ─────────────────────────────────


class CallerSession(Protocol):
    """MCP 会话的调用接口（便于单测注入 stub）。"""

    async def call_tool(
        self, name: str, arguments: dict[str, Any] | None = None
    ) -> mtypes.CallToolResult: ...


# ── McpTool ───────────────────────────────────────


@dataclass
class McpTool:
    """实现 forgecode.tool.Tool 协议的 MCP 远端工具适配器。"""

    full_name: str  # "mcp__<server>__<tool>"
    remote_name: str  # server 上的原始工具名
    _desc: str
    _params: dict[str, Any]  # JSON Schema 透传
    read_only: bool
    caller: CallerSession
    is_system: bool = False

    def name(self) -> str:
        return self.full_name

    def description(self) -> str:
        return self._desc

    def parameters(self) -> dict[str, Any]:
        return self._params

    async def execute(self, args: str) -> Result:
        """调用远端工具，返回 Result。"""
        # 解析 JSON 参数
        arg_map: dict[str, Any] | None = None
        if args and args.strip():
            import json

            try:
                parsed = json.loads(args)
                if isinstance(parsed, dict) and parsed:
                    arg_map = parsed
            except json.JSONDecodeError:
                return Result(content=f"MCP 工具参数 JSON 解析失败: {args[:200]}", is_error=True)

        try:
            result = await asyncio.wait_for(
                self.caller.call_tool(self.remote_name, arg_map),
                timeout=CALL_TIMEOUT,
            )
        except TimeoutError:
            return Result(content="MCP 工具调用超时 (30s)", is_error=True)
        except Exception as e:
            return Result(content=f"MCP 工具调用失败: {e}", is_error=True)

        # 收集文本块
        texts: list[str] = []
        non_text_count = 0
        for block in result.content:
            if isinstance(block, mtypes.TextContent):
                texts.append(block.text)
            else:
                non_text_count += 1

        # 非 text 块告警（每 tool 限一次）
        if non_text_count > 0 and self.full_name not in _non_text_warn_once:
            _non_text_warn_once.add(self.full_name)
            print(
                f"[mcp] warn: tool {self.full_name} returned {non_text_count} "
                "non-text content block(s) (dropped)",
                file=sys.stderr,
            )

        content = "\n".join(texts) if texts else ""
        return Result(content=content, is_error=bool(result.is_error))


# ── adapt_tool ────────────────────────────────────


def adapt_tool(server_name: str, t: mtypes.Tool, session: CallerSession) -> McpTool | None:
    """将 MCP 远端工具适配为 McpTool；失败（非法名）返回 None。"""
    full_name = f"mcp__{server_name}__{t.name}"

    # 禁用字符校验
    if not _VALID_NAME.fullmatch(full_name):
        print(
            f"[mcp] warn: skip tool {full_name}: name contains illegal characters",
            file=sys.stderr,
        )
        return None

    description = t.description or f"来自 MCP server {server_name} 的工具 {t.name}"

    # 参数 schema 透传（Pydantic 模型字段为 snake_case）
    raw_schema = t.input_schema if t.input_schema else {"type": "object"}
    parameters = dict(raw_schema) if isinstance(raw_schema, dict) else {"type": "object"}

    # 只读性：严格只信 annotations.read_only_hint==True
    read_only = bool(t.annotations is not None and getattr(t.annotations, "read_only_hint", False))

    return McpTool(
        full_name=full_name,
        remote_name=t.name,
        _desc=description,
        _params=parameters,
        read_only=read_only,
        caller=session,
    )
