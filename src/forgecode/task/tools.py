"""4 个后台任务工具：TaskList / TaskGet / TaskStop / SendMessage（spec F20）。"""

from __future__ import annotations

import json
from typing import Any

from forgecode.task.manager import TaskBusy, TaskNotFound
from forgecode.tool import Result


class TaskListTool:
    """列出当前所有后台任务。"""

    def __init__(self, mgr: Any) -> None:
        self._mgr = mgr

    read_only = True
    is_system = False

    def name(self) -> str:
        return "TaskList"

    def description(self) -> str:
        return "列出当前所有后台子任务（id / name / status / tool_count / last_activity）"

    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, args: str) -> Result:
        data = [
            {
                "id": t.id,
                "name": t.name,
                "status": t.status.name.lower(),
                "tool_count": t.tool_count,
                "last_activity": t.last_activity,
            }
            for t in self._mgr.list()
        ]
        return Result(content=json.dumps(data, ensure_ascii=False))


class TaskGetTool:
    """返回指定任务的完整状态。"""

    def __init__(self, mgr: Any) -> None:
        self._mgr = mgr

    read_only = True
    is_system = False

    def name(self) -> str:
        return "TaskGet"

    def description(self) -> str:
        return "返回指定后台任务的完整状态（含 result / err）"

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "后台任务 id"},
            },
            "required": ["task_id"],
        }

    async def execute(self, args: str) -> Result:
        try:
            data = json.loads(args) if args.strip() else {}
        except json.JSONDecodeError as e:
            return Result(content=f"参数 JSON 解析失败: {e}", is_error=True)
        task_id = data.get("task_id", "")
        if not isinstance(task_id, str) or not task_id:
            return Result(content="task_id is required", is_error=True)

        bt = self._mgr.get(task_id)
        if bt is None:
            return Result(content=f"task not found: {task_id}", is_error=True)

        payload = {
            "id": bt.id,
            "name": bt.name,
            "status": bt.status.name.lower(),
            "task": bt.task,
            "result": bt.result,
            "err": str(bt.err) if bt.err is not None else None,
            "tool_count": bt.tool_count,
            "last_activity": bt.last_activity,
            "usage": {
                "input": bt.usage.input,
                "output": bt.usage.output,
                "cache_write": bt.usage.cache_write,
                "cache_read": bt.usage.cache_read,
            },
        }
        return Result(content=json.dumps(payload, ensure_ascii=False))


class TaskStopTool:
    """取消指定后台任务。"""

    def __init__(self, mgr: Any) -> None:
        self._mgr = mgr

    read_only = False
    is_system = False

    def name(self) -> str:
        return "TaskStop"

    def description(self) -> str:
        return "取消指定的后台任务"

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "后台任务 id"},
            },
            "required": ["task_id"],
        }

    async def execute(self, args: str) -> Result:
        try:
            data = json.loads(args) if args.strip() else {}
        except json.JSONDecodeError as e:
            return Result(content=f"参数 JSON 解析失败: {e}", is_error=True)
        task_id = data.get("task_id", "")
        if not isinstance(task_id, str) or not task_id:
            return Result(content="task_id is required", is_error=True)
        ok = await self._mgr.stop(task_id)
        if not ok:
            return Result(content=f"task not found: {task_id}", is_error=True)
        return Result(content=json.dumps({"status": "cancellation_requested"}))


class SendMessageTool:
    """给一个仍存活的后台任务续派新任务。"""

    def __init__(self, mgr: Any) -> None:
        self._mgr = mgr

    read_only = False
    is_system = False

    def name(self) -> str:
        return "SendMessage"

    def description(self) -> str:
        return "给一个已完成的同名后台 Agent 发送新任务并重新跑动"

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "后台任务 name"},
                "message": {"type": "string", "description": "新任务指令"},
            },
            "required": ["name", "message"],
        }

    async def execute(self, args: str) -> Result:
        try:
            data = json.loads(args) if args.strip() else {}
        except json.JSONDecodeError as e:
            return Result(content=f"参数 JSON 解析失败: {e}", is_error=True)
        name = data.get("name", "")
        message = data.get("message", "")
        if not isinstance(name, str) or not name:
            return Result(content="name is required", is_error=True)
        if not isinstance(message, str) or not message:
            return Result(content="message is required", is_error=True)
        try:
            task_id = await self._mgr.send_message(name, message)
        except TaskNotFound:
            return Result(content=f"task not found: {name}", is_error=True)
        except TaskBusy as e:
            return Result(content=f"task busy: {name} ({e.args[1].name})", is_error=True)
        return Result(content=json.dumps({"task_id": task_id, "status": "resumed"}))
