"""ForgeCode 命令行入口。"""

from __future__ import annotations

import argparse
import sys

from forgecode.config.loader import load_config
from forgecode.conversation.history import Conversation
from forgecode.permission.engine import new_engine
from forgecode.providers import create_provider
from forgecode.tool import new_default_registry
from forgecode.tui.app import ForgeApp


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
    engine, err = new_engine(".")
    if err is not None:
        print(f"权限引擎降级: {err}", file=sys.stderr)
    app = ForgeApp(
        config=app_config,
        provider=provider,
        conversation=conversation,
        registry=registry,
        engine=engine,
    )
    app.run()


if __name__ == "__main__":
    cli()
