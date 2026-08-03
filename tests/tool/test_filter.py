"""tool.filter 单测：工具过滤多层防线。"""

from __future__ import annotations

from forgecode.tool.filter import (
    ALL_AGENT_DISALLOWED_TOOLS,
    ASYNC_AGENT_ALLOWED_TOOLS,
    CUSTOM_AGENT_DISALLOWED_TOOLS,
    FilterParams,
    apply_agent_tool_filter,
    is_mcp_or_skill,
)

ALL = ["read_file", "write_file", "edit_file", "bash", "glob", "grep", "Agent", "TaskList", "load_skill"]


def test_constants() -> None:
    assert ALL_AGENT_DISALLOWED_TOOLS == ["Agent"]
    assert CUSTOM_AGENT_DISALLOWED_TOOLS == []
    assert "bash" in ASYNC_AGENT_ALLOWED_TOOLS
    assert "Agent" not in ASYNC_AGENT_ALLOWED_TOOLS


def test_default_removes_agent() -> None:
    out = apply_agent_tool_filter(FilterParams(all=ALL, source=0, background=False))
    assert "Agent" not in out
    assert "read_file" in out
    assert "TaskList" in out  # 前台定义式子 Agent 仍可见（spec F26 仅禁 Agent）


def test_background_whitelist() -> None:
    out = apply_agent_tool_filter(FilterParams(all=ALL, source=0, background=True))
    for t in out:
        assert t in ASYNC_AGENT_ALLOWED_TOOLS
    assert "TaskList" not in out
    assert "Agent" not in out


def test_disallowed() -> None:
    out = apply_agent_tool_filter(
        FilterParams(all=ALL, source=0, background=False, disallowed=["bash"])
    )
    assert "bash" not in out
    assert "read_file" in out


def test_allowed_whitelist() -> None:
    out = apply_agent_tool_filter(
        FilterParams(all=ALL, source=0, background=False, allowed=["read_file", "grep"])
    )
    assert set(out) == {"read_file", "grep"}


def test_whitelist_then_blacklist() -> None:
    out = apply_agent_tool_filter(
        FilterParams(
            all=ALL,
            source=0,
            background=False,
            allowed=["read_file", "bash", "grep"],
            disallowed=["bash"],
        )
    )
    assert set(out) == {"read_file", "grep"}


def test_background_keeps_mcp() -> None:
    all_with_mcp = ALL + ["mcp__server__tool"]
    out = apply_agent_tool_filter(FilterParams(all=all_with_mcp, source=0, background=True))
    assert "mcp__server__tool" in out


def test_is_mcp_or_skill() -> None:
    assert is_mcp_or_skill("mcp__x__y") is True
    assert is_mcp_or_skill("read_file") is False
