"""后台任务管理：Manager + BackgroundTask + launch/adopt/stop/send_message。

asyncio 单事件循环，无跨线程竞态。任务协程内任何异常都转 status=failed（N3）。
"""

from __future__ import annotations

import asyncio
import sys
import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Protocol

from forgecode.conversation.history import Conversation


class SubAgent(Protocol):
    """Manager 所需的子 Agent 最小接口（run_to_completion 由 agent 包运行时绑定）。"""

    async def run_to_completion(
        self,
        conv: Conversation,
        task: str,
        events: asyncio.Queue[Any] | None = None,
    ) -> str: ...


class Status(IntEnum):
    RUNNING = 0
    COMPLETED = 1
    FAILED = 2
    CANCELLED = 3


@dataclass
class Usage:
    """后台任务的 token 用量汇总。"""

    input: int = 0
    output: int = 0
    cache_write: int = 0
    cache_read: int = 0


@dataclass
class BackgroundTask:
    """一个后台子 Agent 的完整状态快照。"""

    id: str  # manager 生成
    name: str  # Agent 工具 name 参数，可空
    sub_agent: SubAgent  # 子 Agent（实现 run_to_completion）
    conv: Conversation  # 子对话
    task: str  # 初始任务文本
    status: Status = Status.RUNNING
    result: str = ""  # 跑完的最终文本
    err: BaseException | None = None
    start_time: float = field(default_factory=time.monotonic)
    end_time: float = 0.0
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    handle: asyncio.Task[Any] | None = None  # 跑动协程的 asyncio.Task，stop 时 cancel
    usage: Usage = field(default_factory=Usage)
    tool_count: int = 0
    last_activity: str = ""


@dataclass
class PartialState:
    """前台→后台移交时已收集的中间状态。"""

    tool_count: int = 0
    last_activity: str = ""
    usage: Usage = field(default_factory=Usage)


class TaskNotFound(Exception):  # noqa: N818 — 文档 API 命名（spec F20）
    pass


class TaskBusy(Exception):  # noqa: N818 — 文档 API 命名（spec F20）
    pass


class Manager:
    """管理后台任务生命周期。"""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._tasks: dict[str, BackgroundTask] = {}
        self._by_name: dict[str, str] = {}  # name -> id，后启动的覆盖
        self._done: asyncio.Queue[str] = asyncio.Queue(maxsize=32)
        self._counter: int = 0

    def _next_id(self) -> str:
        self._counter += 1
        return f"task_{self._counter:04x}"

    # ── 查询 ─────────────────────────────────────

    def get(self, task_id: str) -> BackgroundTask | None:
        return self._tasks.get(task_id)

    def list(self) -> list[BackgroundTask]:
        return sorted(self._tasks.values(), key=lambda t: t.start_time)

    def subscribe_done(self) -> asyncio.Queue[str]:
        return self._done

    # ── 生命周期 ─────────────────────────────────

    async def launch(
        self,
        ag: SubAgent,
        conv: Conversation,
        name: str,
        task_text: str,
    ) -> str:
        """起后台协程跑 run_to_completion，返回 task_id。"""
        task_id = self._next_id()
        bt = BackgroundTask(
            id=task_id,
            name=name,
            sub_agent=ag,
            conv=conv,
            task=task_text,
            status=Status.RUNNING,
            start_time=time.monotonic(),
        )
        async with self._lock:
            self._tasks[task_id] = bt
            if name:
                self._by_name[name] = task_id  # 后启动覆盖前

        events: asyncio.Queue[Any] = asyncio.Queue(maxsize=64)
        aggregator = asyncio.create_task(self._aggregate_task_events(events, bt))
        self._start_runner(bt, events, aggregator, task_text)
        return task_id

    async def adopt_running(
        self,
        ag: SubAgent,
        conv: Conversation,
        name: str,
        events: asyncio.Queue[Any],
        partial: PartialState | None = None,
    ) -> str:
        """接管一个已在前台启动的子 Agent（超时/ESC 切后台），继续后台跑完。"""
        task_id = self._next_id()
        bt = BackgroundTask(
            id=task_id,
            name=name,
            sub_agent=ag,
            conv=conv,
            task="",  # 前台已把任务写入 conv
            status=Status.RUNNING,
            start_time=time.monotonic(),
        )
        if partial is not None:
            bt.tool_count = partial.tool_count
            bt.last_activity = partial.last_activity
            bt.usage = partial.usage
        async with self._lock:
            self._tasks[task_id] = bt
            if name:
                self._by_name[name] = task_id

        aggregator = asyncio.create_task(self._aggregate_task_events(events, bt))
        self._start_runner(bt, events, aggregator, "")
        return task_id

    def _start_runner(
        self,
        bt: BackgroundTask,
        events: asyncio.Queue[Any],
        aggregator: asyncio.Task[Any],
        task_text: str,
    ) -> None:
        """起后台跑动协程，并挂 done 回调——无论任务如何结束都推送 done。

        done 推送放在独立 finalize 协程（而非 runner 的 finally）：
        即使任务在开始执行前就被取消（协程体不运行），回调仍会触发。
        """
        runner = asyncio.create_task(self._run_body(bt, events, task_text))
        bt.handle = runner
        runner.add_done_callback(
            lambda _t: asyncio.create_task(self._finalize(bt, events, aggregator))
        )

    async def _run_body(
        self,
        bt: BackgroundTask,
        events: asyncio.Queue[Any],
        task_text: str,
    ) -> None:
        """后台跑动主体：跑完写终态；任何异常转 failed（N3）。"""
        try:
            text = await bt.sub_agent.run_to_completion(bt.conv, task_text, events)
            bt.result = text
            bt.status = Status.COMPLETED
        except asyncio.CancelledError:
            if bt.status is Status.RUNNING:
                bt.status = Status.CANCELLED
            raise
        except BaseException as e:  # noqa: BLE001 — 任何异常都不得击穿主程序
            bt.status = Status.FAILED
            bt.err = e

    async def _finalize(
        self,
        bt: BackgroundTask,
        events: asyncio.Queue[Any],
        aggregator: asyncio.Task[Any],
    ) -> None:
        """终止聚合器并推送 done（回调触发，覆盖取消-before-start 场景）。"""
        if bt.status is Status.RUNNING:
            # 协程体未执行即被取消（如 launch 后立刻 stop）
            bt.status = Status.CANCELLED
        bt.end_time = time.monotonic()
        try:
            await events.put(None)  # 聚合器收到哨兵后退出
        except asyncio.QueueFull:
            pass
        if not aggregator.done():
            try:
                await aggregator
            except Exception:
                pass
        try:
            self._done.put_nowait(bt.id)
        except asyncio.QueueFull:
            print(
                f"task manager: done queue full, dropping notification for {bt.id}",
                file=sys.stderr,
            )

    async def stop(self, task_id: str) -> bool:
        """触发取消；返回是否找到任务。"""
        bt = self.get(task_id)
        if bt is None:
            return False
        if bt.handle is not None and not bt.handle.done():
            bt.handle.cancel()
        return True

    async def send_message(self, name: str, message: str) -> str:
        """给一个已完成的同名后台任务续派新任务（同 id 复用）。"""
        task_id = self._by_name.get(name)
        if task_id is None:
            raise TaskNotFound(name)
        bt = self.get(task_id)
        if bt is None:
            raise TaskNotFound(name)
        if bt.status != Status.COMPLETED:
            raise TaskBusy(name, bt.status)

        bt.conv.add_user(message)
        bt.status = Status.RUNNING
        events: asyncio.Queue[Any] = asyncio.Queue(maxsize=64)
        aggregator = asyncio.create_task(self._aggregate_task_events(events, bt))
        self._start_runner(bt, events, aggregator, "")
        return task_id

    # ── 审批升级（后台任务直接拒绝，避免阻塞）──

    async def upgrade_approval(self, req: Any) -> tuple[Any, bool]:
        """后台任务无人在线审批：直接拒绝。"""
        from forgecode.permission import Outcome

        return Outcome.DENY_ONCE, True

    # ── 事件聚合 ─────────────────────────────────

    async def _aggregate_task_events(
        self, events: asyncio.Queue[Any], bt: BackgroundTask
    ) -> None:
        """消费 run_to_completion 转发的事件，聚合 tool_count / last_activity / usage。"""
        from forgecode.agent import Phase

        while True:
            ev = await events.get()
            if ev is None:
                break
            if ev.tool is not None and ev.tool.phase is Phase.START:
                bt.tool_count += 1
                bt.last_activity = ev.tool.name
            if ev.usage is not None:
                bt.usage.input += ev.usage.input_tokens
                bt.usage.output += ev.usage.output_tokens
                bt.usage.cache_write += ev.usage.cache_write
                bt.usage.cache_read += ev.usage.cache_read
