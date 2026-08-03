"""Hook 引擎：事件分派主流程 + only_once 集合管理。"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass, field

from forgecode.hook.event import Event, is_blocking
from forgecode.hook.executor import Executor
from forgecode.hook.matcher import eval_condition
from forgecode.hook.rule import Payload, Rule


@dataclass
class DispatchResult:
    """一次事件分派的汇总结果。"""

    blocked: bool = False
    reason: str = ""
    blocking_hook_name: str = ""
    injected_prompts: list[str] = field(default_factory=list)


class Engine:
    """事件总线：按声明顺序串行求值命中规则的 hook，聚合拦截与 prompt 注入。"""

    def __init__(self, rules: list[Rule], sources: list[str]) -> None:
        self._rules = rules  # 按加载顺序
        self._sources = sources  # 加载来源文件列表，供 /hooks 显示
        self._once_fired: set[str] = set()  # only_once 已触发的 hook name
        self._lock = asyncio.Lock()
        self._executor = Executor()

    async def dispatch(self, event: Event, payload: Payload) -> DispatchResult:
        """分派一个事件到所有匹配的 hook，返回聚合结果。"""
        result = DispatchResult()
        for rule in self._rules:
            if rule.event is not event:
                continue
            async with self._lock:
                if rule.only_once and rule.name in self._once_fired:
                    continue
            if not eval_condition(rule.condition, payload):
                continue

            if rule.asyncio_mode:
                # async hook：起后台 task 后立即继续，不参与 Blocked / InjectedPrompts
                asyncio.create_task(self._executor.run(rule, payload, blocking=False))
                if rule.only_once:
                    async with self._lock:
                        self._once_fired.add(rule.name)
                continue

            outcome = await self._executor.run(rule, payload, blocking=is_blocking(event))
            if outcome.err is not None:
                print(
                    f"[hook {rule.name}] {event.value} failed: {outcome.err}",
                    file=sys.stderr,
                )
                continue
            if outcome.prompt:
                result.injected_prompts.append(outcome.prompt)
            if rule.only_once:
                async with self._lock:
                    self._once_fired.add(rule.name)
            if outcome.blocked and is_blocking(event):
                result.blocked = True
                result.reason = outcome.reason
                result.blocking_hook_name = rule.name
                break
        return result

    def reset_for_new_session(self) -> None:
        """清空 only_once 集合。

        asyncio 单线程：dispatch 内锁区间无 await、不阻塞，
        此处直接清空不会与正在进行的 dispatch 产生竞态。
        """
        self._once_fired.clear()

    @property
    def sources(self) -> list[str]:
        return list(self._sources)

    @property
    def rules(self) -> list[Rule]:
        return list(self._rules)
