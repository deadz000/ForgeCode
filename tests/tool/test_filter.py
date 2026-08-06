"""tool.filter 单测：工具过滤多层防线。"""

from __future__ import annotations

from forgecode.tool.filter import (
    ALL_AGENT_DISALLOWED_TOOLS,
    ASYNC_AGENT_ALLOWED_TOOLS,
    CUSTOM_AGENT_DISALLOWED_TOOLS,
    FilterParams,
    TEAMMATE_DISALLOWED_TOOLS,
    TEAMMATE_EXTRA_TOOLS,
    apply_agent_tool_filter,
    is_mcp_or_skill,
)

ALL = [
    "read_file",
    "write_file",
    "edit_file",
    "bash",
    "glob",
    "grep",
    "Agent",
    "TaskList",
    "TaskGet",
    "TaskCreate",
    "TaskUpdate",
    "SendMessage",
    "TeamCreate",
    "TeamDelete",
    "load_skill",
]


def test_constants() -> None:
    assert ALL_AGENT_DISALLOWED_TOOLS == ["Agent"]
    assert CUSTOM_AGENT_DISALLOWED_TOOLS == []
    assert "bash" in ASYNC_AGENT_ALLOWED_TOOLS
    assert "Agent" not in ASYNC_AGENT_ALLOWED_TOOLS
    assert set(TEAMMATE_EXTRA_TOOLS) == {"TaskCreate", "TaskGet", "TaskList", "TaskUpdate", "SendMessage"}
    assert "TeamCreate" in TEAMMATE_DISALLOWED_TOOLS


def test_default_removes_agent() -> None:
    out = apply_agent_tool_filter(FilterParams(all=ALL, source=0, background=False))
    assert "Agent" not in out
    assert "read_file" in out
    # 协作/管理工具对普通子 Agent 不可见（spec AC9/N2）
    assert "TaskList" not in out
    assert "SendMessage" not in out
    assert "TeamCreate" not in out


def test_teammate_extra_visible() -> None:
    out = apply_agent_tool_filter(
        FilterParams(all=ALL, source=0, background=False, teammate=True)
    )
    assert "TaskCreate" in out
    assert "TaskGet" in out
    assert "TaskList" in out
    assert "TaskUpdate" in out
    assert "SendMessage" in out
    # 管理工具即使 teammate 也不可见
    assert "TeamCreate" not in out
    assert "TeamDelete" not in out
    assert "Agent" not in out


def test_teammate_with_allowed_whitelist() -> None:
    out = apply_agent_tool_filter(
        FilterParams(
            all=ALL,
            source=0,
            background=False,
            teammate=True,
            allowed=["read_file", "SendMessage"],
        )
    )
    assert set(out) == {"read_file", "SendMessage"}


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
