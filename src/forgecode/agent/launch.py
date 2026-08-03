"""公共 Fork 启动函数：供 skill fork 与未来其他调用方复用 SubAgent 底座。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from forgecode.agent import Agent
from forgecode.conversation.history import Conversation


async def launch_fork(
    *,
    provider: Any,
    registry: Any,
    engine: Any,
    version: str,
    conv: Conversation,
    task: str = "",
    allowed_tools: list[str] | None = None,
    system_prompt: str = "",
    max_turns: int = 0,
    hook_engine: Any = None,
    runtime: Any = None,
) -> str:
    """用 SubAgent 底座跑一个 Fork 子 Agent，返回 final_text。

    与 AgentTool 的前台路径同构：构造受限子 Agent + run_to_completion。
    conv 需已装填任务（task="" 时不再追加）。
    """
    from forgecode.agent.runtime import new_runtime

    sub_runtime = runtime or new_runtime(str(Path.cwd()))
    sub_agent = Agent(
        provider,
        registry,
        engine,
        version,
        runtime=sub_runtime,
        allowed_tools=allowed_tools,
        system_prompt=system_prompt or None,
        max_turns=max_turns,
        hook_engine=hook_engine,
    )
    return await sub_agent.run_to_completion(conv, task, events=None)  # type: ignore[attr-defined,no-any-return]
