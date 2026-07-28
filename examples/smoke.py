"""端到端冒烟测试：验证系统提示工程化 + 缓存策略。

用法：
    python examples/smoke.py

在合法配置下连发两条消息，观察：
- 首轮 cache_write > 0（Anthropic 创建缓存）
- 次轮 cache_read > 0（命中缓存前缀）
- 两轮系统提示与环境信息正确装配
"""

from __future__ import annotations

import asyncio
import sys

from forgecode.agent import Agent, Mode
from forgecode.config.loader import load_config
from forgecode.conversation.history import Conversation
from forgecode.providers import create_provider
from forgecode.tool import new_default_registry

VERSION = "dev"


async def main() -> None:
    # 加载配置
    try:
        app_config = load_config(None)
    except ValueError as e:
        print(f"配置错误: {e}", file=sys.stderr)
        sys.exit(1)

    active_config = None
    for p in app_config.providers:
        if p.name == app_config.active_provider_name:
            active_config = p
            break

    if active_config is None:
        print("错误: 无可用供应商", file=sys.stderr)
        sys.exit(1)

    provider = create_provider(active_config)
    registry = new_default_registry()
    agent = Agent(provider, registry, VERSION)

    # ── 第一轮 ──
    print("=" * 60)
    print("第 1 轮: 简单问题（预期 cache_write > 0 for Anthropic）")
    print("=" * 60)

    conv1 = Conversation()
    conv1.add_user("用一句话介绍你自己")

    async for ev in agent.run(conv1, Mode.NORMAL):
        if ev.text:
            print(ev.text, end="", flush=True)
        elif ev.usage is not None:
            print()
            print(
                f"[用量] input={ev.usage.input_tokens} "
                f"output={ev.usage.output_tokens} "
                f"cache_write={ev.usage.cache_write} "
                f"cache_read={ev.usage.cache_read}"
            )
        elif ev.err:
            print(f"\n[错误] {ev.err}")
        elif ev.done:
            print()

    # ── 第二轮（同一会话） ──
    print()
    print("=" * 60)
    print("第 2 轮: 追问（预期 cache_read > 0 for Anthropic）")
    print("=" * 60)

    conv2 = Conversation()
    conv2.add_user("用一句话介绍你自己")

    async for ev in agent.run(conv2, Mode.NORMAL):
        if ev.text:
            print(ev.text, end="", flush=True)
        elif ev.usage is not None:
            print()
            print(
                f"[用量] input={ev.usage.input_tokens} "
                f"output={ev.usage.output_tokens} "
                f"cache_write={ev.usage.cache_write} "
                f"cache_read={ev.usage.cache_read}"
            )
        elif ev.err:
            print(f"\n[错误] {ev.err}")
        elif ev.done:
            print()

    print()
    print("=" * 60)
    print("冒烟测试完成。")
    print("如果 provider 为 Anthropic：")
    print("  - 第 1 轮 cache_write 应 > 0（缓存创建）")
    print("  - 第 2 轮 cache_read 应 > 0（缓存命中）")
    print("如果 provider 为 OpenAI：")
    print("  - cache_write 恒为 0（自动缓存无写计数）")
    print("  - cache_read 取决于端点是否返回 cached_tokens")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
