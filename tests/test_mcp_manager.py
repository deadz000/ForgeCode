"""MCP 连接管理器单测：成功/失败/超时、close 兜底、并发安全。"""

from __future__ import annotations

import asyncio

import pytest

from forgecode.mcp.config import Config, ServerConfig
from forgecode.mcp.manager import Manager, new_manager

# ── 空配置 ────────────────────────────────────────


@pytest.mark.asyncio
async def test_manager_empty_config():
    """空 Config → tools() 为空、close() 立即返回。"""
    mgr = await new_manager(Config(), version="test")
    assert mgr.tools() == []
    await mgr.close()


# ── 失败隔离 ──────────────────────────────────────


@pytest.mark.asyncio
async def test_manager_connect_failure_isolated(monkeypatch, capsys):
    """单 server 连接失败不影响启动，无工具注册。"""
    cfg = Config(
        servers={
            "bad": ServerConfig(type="stdio", command="/no/such/command"),
        }
    )
    mgr = await new_manager(cfg, version="test")
    tools = mgr.tools()
    await mgr.close()

    assert tools == []
    err = capsys.readouterr().err
    assert "connect server bad" in err.lower() or "bad" in err.lower()


# ── 超时收尾 ──────────────────────────────────────


@pytest.mark.asyncio
async def test_manager_connect_timeout(monkeypatch, capsys):
    """连接卡住时超时后跳过（使用阻塞 stub 避免真实子进程）。"""
    monkeypatch.setattr("forgecode.mcp.manager.connect_timeout", 0.2)

    from forgecode.mcp import manager as mgr_mod

    original = mgr_mod._do_connect_and_init

    async def blocking_connect(name, srv, version):
        await asyncio.Event().wait()  # 永远阻塞
        return None, None, []

    monkeypatch.setattr(mgr_mod, "_do_connect_and_init", blocking_connect)

    try:
        cfg = Config(
            servers={
                "slow": ServerConfig(type="stdio", command="echo"),
            }
        )
        mgr = await new_manager(cfg, version="test")
        tools = mgr.tools()
        await mgr.close()

        assert tools == []
        err = capsys.readouterr().err
        assert "timeout" in err.lower()
    finally:
        monkeypatch.setattr(mgr_mod, "_do_connect_and_init", original)


# ── close 兜底 ────────────────────────────────────


@pytest.mark.asyncio
async def test_manager_close_timeout(monkeypatch, capsys):
    """关闭卡住时 5s 兜底。"""
    monkeypatch.setattr("forgecode.mcp.manager.close_timeout", 0.1)

    mgr = Manager()
    # 注入一个永不完成的 daemon task
    async def never_done():
        await asyncio.Event().wait()

    mgr._tasks = [asyncio.create_task(never_done())]
    mgr._shutdown.set()  # 发信号，但 task 忽略它

    await mgr.close()
    err = capsys.readouterr().err
    assert "timeout" in err.lower()
    assert "close" in err.lower()


# ── 工具排序 ──────────────────────────────────────


def test_manager_tools_sorted():
    """tools() 按 full_name 排序。"""
    from forgecode.mcp.tool import McpTool

    mgr = Manager()

    class FakeSession:
        async def call_tool(self, name, arguments=None):
            pass

    t1 = McpTool(
        full_name="mcp__b__t2",
        remote_name="t2",
        _desc="",
        _params={},
        read_only=False,
        caller=FakeSession(),  # type: ignore[arg-type]
    )
    t2 = McpTool(
        full_name="mcp__a__t1",
        remote_name="t1",
        _desc="",
        _params={},
        read_only=False,
        caller=FakeSession(),  # type: ignore[arg-type]
    )
    mgr._tools = [t1, t2]
    mgr._tools.sort(key=lambda t: t.full_name)
    names = [t.full_name for t in mgr.tools()]
    assert names == ["mcp__a__t1", "mcp__b__t2"]


# ── Manager 返回副本 ──────────────────────────────


def test_manager_tools_is_copy():
    """tools() 返回副本，外部修改不影响内部。"""
    from forgecode.mcp.tool import McpTool

    mgr = Manager()

    class FakeSession:
        async def call_tool(self, name, arguments=None):
            pass

    t = McpTool(
        full_name="mcp__s__t",
        remote_name="t",
        _desc="",
        _params={},
        read_only=False,
        caller=FakeSession(),  # type: ignore[arg-type]
    )
    mgr._tools = [t]
    tools = mgr.tools()
    tools.clear()
    assert len(mgr._tools) == 1  # 内部不变
