"""task 4 个内置工具单测。"""

from __future__ import annotations

import asyncio
import json

import pytest

from forgecode.conversation.history import Conversation
from forgecode.task.manager import Manager, Status
from forgecode.task.tools import SendMessageTool, TaskGetTool, TaskListTool, TaskStopTool


class FakeSubAgent:
    def __init__(self, results: list[str] | None = None) -> None:
        self._results = results or ["ok"]
        self._calls = 0

    async def run_to_completion(self, conv, task, events=None) -> str:
        idx = min(self._calls, len(self._results) - 1)
        self._calls += 1
        return self._results[idx]


async def _wait_done(mgr: Manager) -> None:
    q = mgr.subscribe_done()
    await asyncio.wait_for(q.get(), 5.0)


@pytest.mark.asyncio
async def test_task_list() -> None:
    mgr = Manager()
    await mgr.launch(FakeSubAgent(["a"]), Conversation(), "w1", "t1")
    await mgr.launch(FakeSubAgent(["b"]), Conversation(), "w2", "t2")
    tool = TaskListTool(mgr)
    result = await tool.execute("")
    data = json.loads(result.content)
    assert len(data) == 2
    assert all(t["status"] == "running" for t in data)
    assert {t["name"] for t in data} == {"w1", "w2"}


@pytest.mark.asyncio
async def test_task_get_found() -> None:
    mgr = Manager()
    task_id = await mgr.launch(FakeSubAgent(["ok"]), Conversation(), "w", "t")
    await _wait_done(mgr)
    tool = TaskGetTool(mgr)
    result = await tool.execute(json.dumps({"task_id": task_id}))
    data = json.loads(result.content)
    assert data["id"] == task_id
    assert data["status"] == "completed"
    assert data["result"] == "ok"


@pytest.mark.asyncio
async def test_task_get_not_found() -> None:
    tool = TaskGetTool(Manager())
    result = await tool.execute(json.dumps({"task_id": "nope"}))
    assert result.is_error


@pytest.mark.asyncio
async def test_task_stop() -> None:
    mgr = Manager()

    class SlowAgent(FakeSubAgent):
        async def run_to_completion(self, conv, task, events=None) -> str:
            await asyncio.sleep(60)
            return "never"

    task_id = await mgr.launch(SlowAgent(), Conversation(), "w", "t")
    tool = TaskStopTool(mgr)
    result = await tool.execute(json.dumps({"task_id": task_id}))
    data = json.loads(result.content)
    assert data["status"] == "cancellation_requested"
    await _wait_done(mgr)
    assert mgr.get(task_id).status is Status.CANCELLED


@pytest.mark.asyncio
async def test_send_message_tool() -> None:
    mgr = Manager()
    await mgr.launch(FakeSubAgent(["r1", "r2"]), Conversation(), "worker", "t")
    await _wait_done(mgr)
    tool = SendMessageTool(mgr)
    result = await tool.execute(json.dumps({"name": "worker", "message": "再来"}))
    data = json.loads(result.content)
    assert data["status"] == "resumed"
    await _wait_done(mgr)


@pytest.mark.asyncio
async def test_send_message_tool_not_found() -> None:
    tool = SendMessageTool(Manager())
    result = await tool.execute(json.dumps({"name": "ghost", "message": "hi"}))
    assert result.is_error
