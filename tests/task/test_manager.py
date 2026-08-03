"""task.Manager 单测：launch / 异常 / stop / send_message / by_name。"""

from __future__ import annotations

import asyncio

import pytest

from forgecode.agent import Event, Phase, ToolEvent
from forgecode.conversation.history import Conversation
from forgecode.providers import Usage
from forgecode.task.manager import Manager, Status


class FakeSubAgent:
    """模拟子 Agent：run_to_completion 返回预设结果并转发事件。"""

    def __init__(self, results: list[str] | None = None, raise_exc: Exception | None = None) -> None:
        self._results = results or ["done"]
        self._raise = raise_exc
        self._calls = 0

    async def run_to_completion(self, conv, task, events=None) -> str:
        if events is not None:
            events.put_nowait(Event(tool=ToolEvent(name="bash", phase=Phase.START)))
            events.put_nowait(Event(usage=Usage(input_tokens=10, output_tokens=5)))
        if self._raise is not None:
            raise self._raise
        idx = min(self._calls, len(self._results) - 1)
        self._calls += 1
        return self._results[idx]


async def _wait_done(mgr: Manager, timeout: float = 5.0) -> str:
    q = mgr.subscribe_done()
    return await asyncio.wait_for(q.get(), timeout)


@pytest.mark.asyncio
async def test_launch_completes() -> None:
    mgr = Manager()
    task_id = await mgr.launch(FakeSubAgent(["ok"]), Conversation(), "w", "任务")
    got = await _wait_done(mgr)
    assert got == task_id
    bt = mgr.get(task_id)
    assert bt is not None
    assert bt.status is Status.COMPLETED
    assert bt.result == "ok"
    assert bt.tool_count == 1
    assert bt.last_activity == "bash"
    assert bt.usage.input == 10
    assert bt.usage.output == 5


@pytest.mark.asyncio
async def test_launch_failed() -> None:
    mgr = Manager()
    task_id = await mgr.launch(FakeSubAgent(raise_exc=RuntimeError("boom")), Conversation(), "w", "任务")
    got = await _wait_done(mgr)
    assert got == task_id
    bt = mgr.get(task_id)
    assert bt is not None
    assert bt.status is Status.FAILED
    assert bt.err is not None


@pytest.mark.asyncio
async def test_stop_cancels() -> None:
    mgr = Manager()

    class SlowAgent(FakeSubAgent):
        async def run_to_completion(self, conv, task, events=None) -> str:
            await asyncio.sleep(60)
            return "never"

    task_id = await mgr.launch(SlowAgent(), Conversation(), "w", "任务")
    await mgr.stop(task_id)
    got = await _wait_done(mgr, timeout=5)
    assert got == task_id
    bt = mgr.get(task_id)
    assert bt.status is Status.CANCELLED


@pytest.mark.asyncio
async def test_send_message_resumes() -> None:
    mgr = Manager()
    task_id = await mgr.launch(FakeSubAgent(["r1", "r2"]), Conversation(), "worker", "任务")
    await _wait_done(mgr)
    assert mgr.get(task_id).result == "r1"

    new_id = await mgr.send_message("worker", "再来一轮")
    assert new_id == task_id  # 同 id 复用
    await _wait_done(mgr)
    assert mgr.get(task_id).status is Status.COMPLETED
    assert mgr.get(task_id).result == "r2"


@pytest.mark.asyncio
async def test_send_message_busy() -> None:
    mgr = Manager()

    class SlowAgent(FakeSubAgent):
        async def run_to_completion(self, conv, task, events=None) -> str:
            await asyncio.sleep(60)
            return "never"

    await mgr.launch(SlowAgent(), Conversation(), "busy", "任务")
    with pytest.raises(Exception):
        await mgr.send_message("busy", "x")


@pytest.mark.asyncio
async def test_by_name_overwrite() -> None:
    mgr = Manager()
    id1 = await mgr.launch(FakeSubAgent(["a"]), Conversation(), "w", "任务1")
    id2 = await mgr.launch(FakeSubAgent(["b"]), Conversation(), "w", "任务2")
    assert id1 != id2
    assert mgr._by_name["w"] == id2
