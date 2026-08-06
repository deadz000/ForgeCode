"""TaskGet / TaskList 工具：统一 Team 共享任务 与 ch13 后台任务 分流。"""

from __future__ import annotations

import json
from typing import Any

from forgecode.team.tasks import Filter, Store
from forgecode.team.tools.common import current_team_name
from forgecode.tool import Result


def _in_team_ctx(mgr: Any) -> bool:
    return current_team_name(mgr) is not None


class TaskGetTool:
    """取任务详情。Team 上下文取共享任务；否则取 ch13 后台任务。"""

    def __init__(self, mgr: Any, fallback: Any = None) -> None:
        self._mgr = mgr
        self._fallback = fallback  # ch13 后台任务 TaskGetTool

    read_only = True
    is_system = False
    is_teammate_only = False

    def name(self) -> str:
        return "TaskGet"

    def description(self) -> str:
        return "返回指定任务详情（Team 上下文为共享任务，否则为后台任务）"

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "任务 id"},
            },
            "required": ["task_id"],
        }

    async def execute(self, args: str) -> Result:
        try:
            data = json.loads(args) if args.strip() else {}
        except json.JSONDecodeError as e:
            return Result(content=f"参数 JSON 解析失败: {e}", is_error=True)
        task_id = str(data.get("task_id", "")).strip()
        if not task_id:
            return Result(content="task_id is required", is_error=True)
        if _in_team_ctx(self._mgr):
            team = self._mgr.get(current_team_name(self._mgr) or "")
            if team is None:
                return Result(content="团队不存在", is_error=True)
            store = Store(team.tasks_path)
            try:
                t = await store.get(task_id)
            except Exception as e:
                return Result(content=f"task not found: {task_id} ({e})", is_error=True)
            return Result(content=json.dumps(_task_to_dict(t), ensure_ascii=False))
        if self._fallback is not None:
            result = await self._fallback.execute(args)
            assert isinstance(result, Result)
            return result
        return Result(content=f"task not found: {task_id}", is_error=True)


class TaskListTool:
    """列任务。Team 上下文按 status 过滤共享任务；否则列 ch13 后台任务。"""

    def __init__(self, mgr: Any, fallback: Any = None) -> None:
        self._mgr = mgr
        self._fallback = fallback  # ch13 后台任务 TaskListTool

    read_only = True
    is_system = False
    is_teammate_only = False

    def name(self) -> str:
        return "TaskList"

    def description(self) -> str:
        return "列出任务（Team 上下文为共享任务可带 status 过滤，否则为后台任务）"

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "过滤: pending/in_progress/completed/blocked（Team 上下文）",
                }
            },
        }

    async def execute(self, args: str) -> Result:
        try:
            data = json.loads(args) if args.strip() else {}
        except json.JSONDecodeError as e:
            return Result(content=f"参数 JSON 解析失败: {e}", is_error=True)
        status = str(data.get("status", "")).strip() or None
        if _in_team_ctx(self._mgr):
            team = self._mgr.get(current_team_name(self._mgr) or "")
            if team is None:
                return Result(content="团队不存在", is_error=True)
            store = Store(team.tasks_path)
            tasks = await store.list_(Filter(status=status))
            return Result(content=json.dumps([_task_to_dict(t) for t in tasks], ensure_ascii=False))
        if self._fallback is not None:
            result = await self._fallback.execute(args)
            assert isinstance(result, Result)
            return result
        return Result(content=json.dumps([], ensure_ascii=False))


def _task_to_dict(t: Any) -> dict[str, Any]:
    return {
        "id": t.id,
        "title": t.title,
        "description": t.description,
        "status": str(t.status),
        "assignee": t.assignee,
        "blocked_by": list(t.blocked_by),
        "blocks": list(t.blocks),
        "is_ready": t.is_ready,
        "created_at": t.created_at,
        "updated_at": t.updated_at,
    }
