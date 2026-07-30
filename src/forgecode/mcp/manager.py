"""MCP 连接管理器：并发连接、会话缓存、生命周期管理。

每个 server 连接跑在自己的 asyncio Task 中——mcp SDK 内部的 anyio cancel scope
要求 __aenter__ 与 __aexit__ 在同一 task。Task 完成握手+列工具后注册工具，
然后阻塞等待关闭信号；close() 发信号后 gather 所有 task 完成清理。
"""

from __future__ import annotations

import asyncio
import os
import sys

import httpx2
import mcp.types as mtypes
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client

from forgecode.mcp.config import Config, ServerConfig
from forgecode.mcp.tool import McpTool, adapt_tool

# ── 超时常量（非常量，便于单测 monkeypatch）────────

connect_timeout: float = 30.0
close_timeout: float = 5.0


# ── Manager ───────────────────────────────────────


class Manager:
    """持有所有 MCP 会话与适配好的工具列表。"""

    def __init__(self, registry: object | None = None) -> None:
        self._lock = asyncio.Lock()
        self._tools: list[McpTool] = []
        self._shutdown = asyncio.Event()
        self._tasks: list[asyncio.Task[None]] = []
        self._registry = registry  # 可选：自动注册工具

    def tools(self) -> list[McpTool]:
        """返回工具列表副本（防外部修改）。"""
        return list(self._tools)

    async def close(self) -> None:
        """通知所有连接 task 退出并等待完成，5s 兜底。"""
        self._shutdown.set()
        if not self._tasks:
            return
        try:
            await asyncio.wait_for(
                asyncio.gather(*self._tasks, return_exceptions=True),
                timeout=close_timeout,
            )
        except TimeoutError:
            print(
                f"[mcp] warn: close timeout ({close_timeout}s), some sessions may leak",
                file=sys.stderr,
            )


# ── 工厂函数 ──────────────────────────────────────


async def new_manager(cfg: Config, version: str, registry: object | None = None) -> Manager:
    """后台并发连接所有 server，立即返回。

    若传入 registry，连接成功后自动注册工具——TUI 不阻塞。
    """
    mgr = Manager(registry=registry)

    for name, srv in cfg.servers.items():
        mgr._tasks.append(asyncio.create_task(_run_connection(mgr, name, srv, version)))

    return mgr


# ── 连接逻辑 ──────────────────────────────────────


async def _run_connection(mgr: Manager, name: str, srv: ServerConfig, version: str) -> None:
    """在一个 asyncio Task 内完成：连接(30s超时)→注册工具→等待关闭→清理。"""
    # 阶段1：连接 + 握手 + 列工具（有超时）
    transport_ctx, session, adapted = await _connect_and_init(mgr, name, srv, version)
    if transport_ctx is None:
        return  # 连接失败，已在 _connect_and_init 内告警

    # 阶段2：注册工具 + 等待关闭信号（无超时，保持连接活跃）
    async with mgr._lock:
        mgr._tools.extend(adapted)

    # 自动注册进全局 Registry
    if mgr._registry is not None:
        for t in adapted:
            try:
                mgr._registry.register(t)  # type: ignore[union-attr]
            except ValueError:
                pass  # 同名工具已存在则跳过
    print(
        f"[mcp] server {name} ready: {len(adapted)} tool(s)",
        file=sys.stderr,
    )

    # 阻塞等待关闭信号——用 try/finally 保证清理
    try:
        await mgr._shutdown.wait()
    finally:
        await session.__aexit__(None, None, None)
        await transport_ctx.__aexit__(None, None, None)


async def _connect_and_init(
    mgr: Manager, name: str, srv: ServerConfig, version: str
) -> tuple:
    """连接 MCP server 并完成握手、列工具。30s 超时，失败返回 (None, None, [])。"""
    try:
        return await asyncio.wait_for(
            _do_connect_and_init(name, srv, version),
            timeout=connect_timeout,
        )
    except TimeoutError:
        print(
            f"[mcp] warn: connect server {name} timeout after {connect_timeout}s",
            file=sys.stderr,
        )
    except Exception as e:
        print(f"[mcp] warn: connect server {name} failed: {e}", file=sys.stderr)
    return None, None, []


async def _do_connect_and_init(name: str, srv: ServerConfig, version: str) -> tuple:
    """打开 transport、初始化 session、列出工具。返回 (transport_ctx, session, adapted_tools)。"""
    if srv.type == "stdio":
        params = StdioServerParameters(
            command=srv.command,
            args=srv.args or [],
            env={**os.environ, **srv.env} if srv.env else None,
        )
        transport_ctx = stdio_client(params)
    else:
        http_kwargs: dict = {}
        if srv.headers:
            http_kwargs["headers"] = srv.headers
        http_client = httpx2.AsyncClient(**http_kwargs)
        transport_ctx = streamable_http_client(srv.url, http_client=http_client)

    # 进入 transport
    transport = await transport_ctx.__aenter__()
    read, write = transport[0], transport[1]

    try:
        session = ClientSession(
            read,
            write,
            client_info=mtypes.Implementation(name="forgecode", version=version),
        )
        await session.__aenter__()
        try:
            await session.initialize()
            listed = await session.list_tools()

            adapted: list[McpTool] = []
            for t in listed.tools:
                at = adapt_tool(name, t, session)
                if at is not None:
                    adapted.append(at)

            return transport_ctx, session, adapted
        except Exception:
            await session.__aexit__(None, None, None)
            raise
    except Exception:
        await transport_ctx.__aexit__(None, None, None)
        raise
