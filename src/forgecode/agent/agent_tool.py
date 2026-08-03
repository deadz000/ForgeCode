"""统一 Agent 工具：主 Agent 通过 subagent_type 调用预定义/ Fork 子 Agent。

嵌套阻断用 contextvars（IN_SUBAGENT）替代文档的 QuerySource：
子 Agent 跑动期间 contextvar 置 True，任何 Agent 工具调用都被拦截。
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from forgecode.agent import Agent
from forgecode.agent.fork import build_forked_messages, is_fork_context
from forgecode.agent.run_to_completion import IN_SUBAGENT
from forgecode.conversation.history import Conversation
from forgecode.subagent import Definition
from forgecode.tool import Result
from forgecode.tool.filter import FilterParams, apply_agent_tool_filter

# 前台子 Agent 超时自动切后台的秒数（spec F17-2）
AUTO_BACKGROUND_SECONDS: float = 120.0


class AgentCatalog(Protocol):
    """Agent 工具所需的角色 Catalog 最小接口。"""

    def resolve(self, name: str) -> Definition | None: ...
    def fork_definition(self) -> Definition: ...
    def list(self) -> list[Definition]: ...


class TaskManager(Protocol):
    """Agent 工具所需的后台任务管理器最小接口。"""

    async def launch(self, ag: Any, conv: Conversation, name: str, task: str) -> str: ...
    async def adopt_running(
        self, ag: Any, conv: Conversation, name: str, events: Any, partial: Any
    ) -> str: ...
    async def upgrade_approval(self, req: Any) -> tuple[Any, bool]: ...


@dataclass
class AgentArgs:
    """Agent 工具的参数（spec F1）。"""

    prompt: str
    description: str
    subagent_type: str = ""
    model: str = ""
    run_in_background: bool = False
    name: str = ""


class AgentTool:
    """注册到 tool.Registry 的统一 Agent 工具。"""

    def __init__(
        self,
        catalog: AgentCatalog,
        task_mgr: TaskManager,
        parent: Agent | None = None,
        bg_enabled: bool = True,
    ) -> None:
        self._catalog = catalog
        self._task_mgr = task_mgr
        self._parent = parent
        self._bg_enabled = bg_enabled
        self._get_parent_conv: Callable[[], Conversation] | None = None

    read_only = False
    is_system = False

    def set_parent(self, parent: Agent) -> None:
        self._parent = parent

    def bind_conv_source(self, fn: Callable[[], Conversation]) -> None:
        """绑定父对话获取函数（Fork 路径需要克隆父消息）。"""
        self._get_parent_conv = fn

    def name(self) -> str:
        return "Agent"

    def description(self) -> str:
        names = ", ".join(d.name for d in self._catalog.list())
        base = "启动一个子 Agent 处理独立任务；subagent_type 指定预定义角色，留空走 Fork 路径"
        return f"{base}；可用 subagent_type: {names}"

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "交给子 Agent 的任务指令（必填）"},
                "description": {"type": "string", "description": "一句话任务描述，供 UI 展示（必填）"},
                "subagent_type": {"type": "string", "description": "预定义角色名，留空走 Fork 路径"},
                "model": {"type": "string", "description": "模型覆盖：haiku/sonnet/opus/inherit"},
                "run_in_background": {"type": "boolean", "description": "true 时强制后台启动"},
                "name": {"type": "string", "description": "给本次子 Agent 命名，供 SendMessage 使用"},
            },
            "required": ["prompt", "description"],
        }

    async def execute(self, args: str) -> Result:
        parent = self._parent
        if parent is None:
            return Result(content="Agent tool not bound to a parent agent", is_error=True)

        try:
            data = json.loads(args) if args.strip() else {}
        except json.JSONDecodeError as e:
            return Result(content=f"参数 JSON 解析失败: {e}", is_error=True)

        a_args = AgentArgs(
            prompt=str(data.get("prompt", "")),
            description=str(data.get("description", "")),
            subagent_type=str(data.get("subagent_type", "")),
            model=str(data.get("model", "")),
            run_in_background=bool(data.get("run_in_background", False)),
            name=str(data.get("name", "")),
        )
        if not a_args.prompt:
            return Result(content="prompt is required", is_error=True)
        if not a_args.description:
            return Result(content="description is required", is_error=True)

        # ── 嵌套阻断 ──
        if IN_SUBAGENT.get():
            return Result(content="subagent cannot spawn Agent", is_error=True)
        parent_msgs: list[Any] = (
            self._get_parent_conv().messages if self._get_parent_conv is not None else []
        )
        if is_fork_context(parent_msgs):
            return Result(
                content="Fork subagent cannot spawn Agent (boilerplate detected)",
                is_error=True,
            )

        # ── resolve 定义 ──
        if a_args.subagent_type:
            defi = self._catalog.resolve(a_args.subagent_type)
            if defi is None:
                return Result(content=f"unknown subagent_type: {a_args.subagent_type}", is_error=True)
        else:
            defi = self._catalog.fork_definition()

        # ── 决定后台 ──
        background = defi.background or a_args.run_in_background or defi.is_fork()
        if background and not self._bg_enabled:
            return Result(content="background mode is disabled by config", is_error=True)

        # ── 工具过滤（多层防线）──
        names = [d.name for d in parent._registry.definitions()]
        if defi.is_fork():
            # Fork 子 Agent 保留 Agent 工具（嵌套靠 contextvar 拦截），其余仍走后台白名单
            allowed = apply_agent_tool_filter(
                FilterParams(all=names, source=int(defi.source), background=True)
            )
            if "Agent" in names and "Agent" not in allowed:
                allowed.append("Agent")
        else:
            allowed = apply_agent_tool_filter(
                FilterParams(
                    all=names,
                    source=int(defi.source),
                    background=background,
                    allowed=defi.tools,
                    disallowed=defi.disallowed_tools,
                )
            )

        # ── 构造子 Agent（provider 沿用父，model 切换本期从简）──
        from forgecode.agent.runtime import new_runtime

        sub_runtime = new_runtime(str(os.getcwd()))
        approval_upgrader = (
            self._task_mgr.upgrade_approval  # 后台任务无人在线审批 → 拒绝
            if background
            else None  # 前台路径在起跑前绑定弹窗回调
        )
        sub_agent = Agent(
            parent._provider,
            parent._registry,
            parent._engine,
            parent._version,
            runtime=sub_runtime,
            allowed_tools=allowed,
            system_prompt=defi.system_prompt,
            max_turns=defi.max_turns,
            permission_mode=defi.permission_mode,
            dont_ask=defi.dont_ask,
            approval_upgrader=approval_upgrader,
            hook_engine=parent._hook_engine,
        )

        # ── 子 conv ──
        if defi.is_fork():
            forked = build_forked_messages(parent_msgs, a_args.prompt)
            sub_conv = Conversation.from_messages(forked)
        else:
            sub_conv = Conversation()

        # ── 后台路径 ──
        if background:
            task_id = await self._task_mgr.launch(
                sub_agent, sub_conv, a_args.name, a_args.prompt
            )
            return Result(content=json.dumps({"task_id": task_id, "status": "async_launched"}))

        # ── 前台路径（超时自动切后台）──
        from forgecode.agent.permission_upgrade import make_approval_prompter

        sub_agent.approval_upgrader = make_approval_prompter(defi.name)
        from forgecode.task.manager import PartialState

        events: asyncio.Queue[Any] = asyncio.Queue(maxsize=64)
        partial = PartialState()
        aggregator = asyncio.create_task(_aggregate_partial(events, partial))
        try:
            final_text = await asyncio.wait_for(
                sub_agent.run_to_completion(sub_conv, a_args.prompt, events),  # type: ignore[attr-defined]
                timeout=AUTO_BACKGROUND_SECONDS,
            )
        except TimeoutError:
            task_id = await self._task_mgr.adopt_running(
                sub_agent, sub_conv, a_args.name, events, partial
            )
            return Result(
                content=json.dumps({"task_id": task_id, "status": "timed_out_to_background"})
            )
        except Exception as e:
            return Result(content=f"subagent error: {e}", is_error=True)
        finally:
            aggregator.cancel()
            try:
                await events.put(None)
            except asyncio.QueueFull:
                pass

        return Result(content=final_text)


async def _aggregate_partial(events: asyncio.Queue[Any], partial: Any) -> None:
    """前台路径的中间状态聚合（超时切后台时移交 Manager）。"""
    from forgecode.agent import Phase

    while True:
        ev = await events.get()
        if ev is None:
            break
        if ev.tool is not None and ev.tool.phase is Phase.START:
            partial.tool_count += 1
            partial.last_activity = ev.tool.name
        if ev.usage is not None:
            partial.usage.input += ev.usage.input_tokens
            partial.usage.output += ev.usage.output_tokens
            partial.usage.cache_write += ev.usage.cache_write
            partial.usage.cache_read += ev.usage.cache_read
