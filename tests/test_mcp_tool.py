"""MCP 工具适配单测：命名、schema 透传、execute 各分支。"""

from __future__ import annotations

import asyncio

import mcp.types as mtypes
import pytest

from forgecode.mcp.tool import McpTool, adapt_tool

# ── Stub CallerSession ────────────────────────────


class StubSession:
    """注入预编程的 call_tool 返回值或异常。"""

    def __init__(self, result=None, error=None, block_event=None):
        self._result = result
        self._error = error
        self._block = block_event  # asyncio.Event: 阻塞用

    async def call_tool(self, name, arguments=None):
        if self._block is not None:
            await self._block.wait()
        if self._error is not None:
            raise self._error
        return self._result


# ── 工具构造辅助 ──────────────────────────────────


def _make_tool(name="test_tool", description="A test tool", input_schema=None, annotations=None):
    return mtypes.Tool(
        name=name,
        description=description,
        input_schema=input_schema or {"type": "object", "properties": {}},
        annotations=annotations,
    )


# ── T3.1: 命名拼接与禁用字符 ──────────────────────


def test_adapt_tool_full_name():
    """合法名 → full_name = mcp__<server>__<tool>。"""
    t = _make_tool(name="my_tool")
    stub = StubSession()
    at = adapt_tool("github", t, stub)
    assert at is not None
    assert at.full_name == "mcp__github__my_tool"
    assert at.name() == "mcp__github__my_tool"
    assert at.remote_name == "my_tool"


def test_adapt_tool_illegal_chars_dot(capsys):
    """工具名含 . → 跳过并告警。"""
    t = _make_tool(name="bad.name")
    stub = StubSession()
    at = adapt_tool("srv", t, stub)
    assert at is None
    assert "illegal characters" in capsys.readouterr().err


def test_adapt_tool_illegal_chars_at(capsys):
    """server 名含 @ → 跳过并告警。"""
    t = _make_tool(name="ok")
    stub = StubSession()
    at = adapt_tool("bad@srv", t, stub)
    assert at is None
    assert "illegal characters" in capsys.readouterr().err


# ── T3.2: 字段适配 ────────────────────────────────


def test_adapt_tool_description_fallback():
    """description 为空 → 兜底文案。"""
    t = _make_tool(name="t1", description=None)
    stub = StubSession()
    at = adapt_tool("srv", t, stub)
    assert at is not None
    assert "来自 MCP server srv" in at.description()


def test_adapt_tool_schema_transparent():
    """schema 透传为 dict。"""
    schema = {"type": "object", "properties": {"msg": {"type": "string"}}}
    t = _make_tool(name="t1", input_schema=schema)
    stub = StubSession()
    at = adapt_tool("srv", t, stub)
    assert at is not None
    assert at.parameters() == schema


def test_adapt_tool_schema_none_default():
    """schema 为 None → 兜底含 type: object。"""
    t = _make_tool(name="t1", input_schema=None)
    stub = StubSession()
    at = adapt_tool("srv", t, stub)
    assert at is not None
    assert at.parameters()["type"] == "object"


def test_adapt_tool_read_only_true():
    """annotations.read_only_hint=True → read_only=True。"""
    ann = mtypes.ToolAnnotations(read_only_hint=True)
    t = _make_tool(name="t1", annotations=ann)
    stub = StubSession()
    at = adapt_tool("srv", t, stub)
    assert at is not None
    assert at.read_only is True


def test_adapt_tool_read_only_false_when_none():
    """annotations 为 None → read_only=False。"""
    t = _make_tool(name="t1", annotations=None)
    stub = StubSession()
    at = adapt_tool("srv", t, stub)
    assert at is not None
    assert at.read_only is False


def test_adapt_tool_read_only_false_by_default():
    """read_only_hint=False → read_only=False。"""
    ann = mtypes.ToolAnnotations(read_only_hint=False)
    t = _make_tool(name="t1", annotations=ann)
    stub = StubSession()
    at = adapt_tool("srv", t, stub)
    assert at is not None
    assert at.read_only is False


# ── T3.3: Execute 成功 ────────────────────────────


@pytest.mark.asyncio
async def test_execute_success_single_text():
    """成功调用返回单个 TextContent → content 拼接。"""
    result = mtypes.CallToolResult(content=[mtypes.TextContent(type="text", text="hello world")])
    stub = StubSession(result=result)
    tool = McpTool(
        full_name="mcp__s__t",
        remote_name="t",
        _desc="d",
        _params={"type": "object"},
        read_only=False,
        caller=stub,
    )
    r = await tool.execute('{"msg":"hi"}')
    assert r.content == "hello world"
    assert r.is_error is False


@pytest.mark.asyncio
async def test_execute_success_multi_text():
    """多 TextContent 按顺序 \n 拼接。"""
    result = mtypes.CallToolResult(
        content=[
            mtypes.TextContent(type="text", text="line1"),
            mtypes.TextContent(type="text", text="line2"),
        ]
    )
    stub = StubSession(result=result)
    tool = McpTool(
        full_name="mcp__s__t",
        remote_name="t",
        _desc="d",
        _params={"type": "object"},
        read_only=False,
        caller=stub,
    )
    r = await tool.execute("{}")
    assert r.content == "line1\nline2"


@pytest.mark.asyncio
async def test_execute_success_empty_args():
    """空参数 → 正常调用（arg_map=None）。"""
    result = mtypes.CallToolResult(content=[mtypes.TextContent(type="text", text="ok")])
    stub = StubSession(result=result)
    tool = McpTool(
        full_name="mcp__s__t",
        remote_name="t",
        _desc="d",
        _params={"type": "object"},
        read_only=False,
        caller=stub,
    )
    r = await tool.execute("")
    assert r.content == "ok"
    assert r.is_error is False


# ── T3.4: Execute 远端错误 ────────────────────────


@pytest.mark.asyncio
async def test_execute_remote_is_error():
    """远端 is_error=True → ToolResult.is_error=True。"""
    result = mtypes.CallToolResult(
        content=[mtypes.TextContent(type="text", text="something went wrong")],
        is_error=True,
    )
    stub = StubSession(result=result)
    tool = McpTool(
        full_name="mcp__s__t",
        remote_name="t",
        _desc="d",
        _params={"type": "object"},
        read_only=False,
        caller=stub,
    )
    r = await tool.execute("{}")
    assert r.is_error is True
    assert "something went wrong" in r.content


# ── T3.5: Execute 异常 ────────────────────────────


@pytest.mark.asyncio
async def test_execute_call_tool_exception():
    """call_tool 抛异常 → is_error=True。"""
    stub = StubSession(error=RuntimeError("connection lost"))
    tool = McpTool(
        full_name="mcp__s__t",
        remote_name="t",
        _desc="d",
        _params={"type": "object"},
        read_only=False,
        caller=stub,
    )
    r = await tool.execute("{}")
    assert r.is_error is True
    assert "MCP 工具调用失败" in r.content
    assert "connection lost" in r.content


@pytest.mark.asyncio
async def test_execute_timeout(monkeypatch):
    """call_tool 阻塞至超时 → is_error=True。"""
    monkeypatch.setattr("forgecode.mcp.tool.CALL_TIMEOUT", 0.1)
    block = asyncio.Event()
    stub = StubSession(block_event=block)
    tool = McpTool(
        full_name="mcp__s__t",
        remote_name="t",
        _desc="d",
        _params={"type": "object"},
        read_only=False,
        caller=stub,
    )
    r = await tool.execute("{}")
    assert r.is_error is True
    assert "超时" in r.content


# ── T3.6: 非 text 块跳过 ──────────────────────────


@pytest.mark.asyncio
async def test_execute_non_text_dropped(capsys):
    """非 TextContent 块静默丢弃 + 一次性告警。"""
    result = mtypes.CallToolResult(
        content=[
            mtypes.TextContent(type="text", text="keep"),
            # ImageContent 等其他类型不会被收集
        ]
    )
    # 手动插入一个模拟非 text 块
    result.content.append(mtypes.TextContent(type="text", text="also-keep"))

    stub = StubSession(result=result)
    tool = McpTool(
        full_name="mcp__s__t",
        remote_name="t",
        _desc="d",
        _params={"type": "object"},
        read_only=False,
        caller=stub,
    )
    r = await tool.execute("{}")
    assert "keep" in r.content
    assert "also-keep" in r.content
