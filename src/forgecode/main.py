"""ForgeCode 命令行入口。"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from forgecode.agent.runtime import SessionRuntime
from forgecode.compact.state import CompactCircuitBreaker, ContentReplacementState, RecoveryState
from forgecode.compact.state import new_session_context as _new_session_context
from forgecode.config.loader import load_config
from forgecode.config.schema import effective_context_window
from forgecode.conversation.history import Conversation
from forgecode.mcp import load_config as load_mcp_config
from forgecode.mcp import new_manager as new_mcp_manager
from forgecode.permission.engine import new_engine
from forgecode.providers import create_provider
from forgecode.tool import new_default_registry
from forgecode.tui.app import VERSION, ForgeApp


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="forgecode",
        description="命令行 AI 编程助手",
    )
    parser.add_argument(
        "--provider",
        type=str,
        default=None,
        help="指定使用的供应商名称（不指定则使用第一个）",
    )
    return parser.parse_args()


def cli() -> None:
    """同步入口（供 pyproject.toml scripts 调用）。"""
    args = parse_args()

    try:
        app_config = load_config(args.provider)
    except ValueError as e:
        print(f"配置错误: {e}", file=sys.stderr)
        sys.exit(1)

    # 获取活动供应商配置
    active_config = None
    for p in app_config.providers:
        if p.name == app_config.active_provider_name:
            active_config = p
            break

    if active_config is None:
        print("错误: 无可用供应商", file=sys.stderr)
        sys.exit(1)

    try:
        provider = create_provider(active_config)
    except ValueError as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)

    conversation = Conversation()
    registry = new_default_registry()

    # ── 构造 SessionRuntime ──
    workspace = str(Path.cwd())
    runtime = SessionRuntime(
        replacement=ContentReplacementState(),
        recovery=RecoveryState(),
        auto_tracking=CompactCircuitBreaker(),
        session=_new_session_context(workspace),
        context_window=effective_context_window(active_config),
    )

    # 启动异步主流程（含 MCP 连接 + TUI）
    try:
        asyncio.run(_amain(app_config, provider, conversation, registry, runtime))
    except KeyboardInterrupt:
        pass


async def _amain(app_config, provider, conversation, registry, runtime) -> None:
    """异步主流程：MCP 连接 → 注册工具 → 启动 TUI → 关闭 MCP。"""
    root = os.getcwd()

    # ── MCP 后台连接（不阻塞 TUI）──
    mcp_cfg = load_mcp_config(root)
    mcp_mgr = await new_mcp_manager(mcp_cfg, version=VERSION, registry=registry)

    try:
        engine, err = new_engine(".")
        if err is not None:
            print(f"权限引擎降级: {err}", file=sys.stderr)

        app = ForgeApp(
            config=app_config,
            provider=provider,
            conversation=conversation,
            registry=registry,
            engine=engine,
            runtime=runtime,
        )
        await app.run_async()
    finally:
        await mcp_mgr.close()


if __name__ == "__main__":
    cli()
