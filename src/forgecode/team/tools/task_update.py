"""TaskUpdate 工具：更新共享任务，维护双向依赖。"""

from __future__ import annotations

import json
from typing import Any

from forgecode.team.tasks import Patch, Store
from forgecode.team.tools.common import current_team_name
from forgecode.tool import Result


class TaskUpdateTool:
    """更新 Team 共享任务（F29）。"""

    def __init__(self, mgr: Any) -> None:
        self._mgr = mgr

    read_only = False
    is_system = False
    is_teammate_only = True

    def name(self) -> str:
        return "TaskUpdate"

    def description(self) -> str:
        return "更新 Team 共享任务（标题/描述/状态/负责人/依赖关系）"

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "任务 id（必填）"},
                "title": {"type": "string"},
                "description": {"type": "string"},
                "status": {"type": "string", "description": "pending/in_progress/completed/blocked"},
                "assignee": {"type": "string"},
                "add_blocks": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "追加阻塞的任务 id 列表",
                },
                "add_blocked_by": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "追加被其阻塞的任务 id 列表",
                },
                "remove_blocks": {"type": "array", "items": {"type": "string"}},
                "remove_blocked_by": {"type": "array", "items": {"type": "string"}},
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
        team_name = current_team_name(self._mgr)
        if not team_name:
            return Result(content="不在任何 Team 上下文中，无法更新任务", is_error=True)
        team = self._mgr.get(team_name)
        if team is None:
            return Result(content=f"团队不存在: {team_name}", is_error=True)

        def _list(key: str) -> list[str]:
            v = data.get(key) or []
            return [str(x) for x in v] if isinstance(v, list) else []

        patch = Patch(
            title=data.get("title"),
            description=data.get("description"),
            status=data.get("status"),
            assignee=data.get("assignee"),
            add_blocks=_list("add_blocks"),
            add_blocked_by=_list("add_blocked_by"),
            remove_blocks=_list("remove_blocks"),
            remove_blocked_by=_list("remove_blocked_by"),
        )
        store = Store(team.tasks_path)
        try:
            await store.update(task_id, patch)
        except Exception as e:
            return Result(content=f"task not found: {task_id} ({e})", is_error=True)
        return Result(content=json.dumps({"task_id": task_id, "updated": True}, ensure_ascii=False))
