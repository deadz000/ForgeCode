"""TaskCreate 工具：队员创建共享任务。"""

from __future__ import annotations

import json
from typing import Any

from forgecode.team.tasks import Store, Task
from forgecode.team.tools.common import current_team_name
from forgecode.tool import Result


class TaskCreateTool:
    """在 Team 共享任务列表创建任务（F26）。"""

    def __init__(self, mgr: Any) -> None:
        self._mgr = mgr

    read_only = False
    is_system = False
    is_teammate_only = True

    def name(self) -> str:
        return "TaskCreate"

    def description(self) -> str:
        return "在 Team 共享任务列表创建一个任务"

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "任务标题（必填）"},
                "description": {"type": "string", "description": "任务描述（可选）"},
                "assignee": {"type": "string", "description": "负责队员名（可选）"},
                "blocked_by": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "被哪些任务阻塞（task_id 列表，可选）",
                },
            },
            "required": ["title"],
        }

    async def execute(self, args: str) -> Result:
        try:
            data = json.loads(args) if args.strip() else {}
        except json.JSONDecodeError as e:
            return Result(content=f"参数 JSON 解析失败: {e}", is_error=True)
        title = str(data.get("title", "")).strip()
        if not title:
            return Result(content="缺少必填参数 title", is_error=True)
        team_name = current_team_name(self._mgr)
        if not team_name:
            return Result(content="不在任何 Team 上下文中，无法创建任务", is_error=True)
        team = self._mgr.get(team_name)
        if team is None:
            return Result(content=f"团队不存在: {team_name}", is_error=True)
        blocked_by = data.get("blocked_by") or []
        if not isinstance(blocked_by, list):
            blocked_by = []
        store = Store(team.tasks_path)
        tid = await store.create(
            Task(
                id="",
                title=title,
                description=str(data.get("description", "")),
                assignee=str(data.get("assignee", "")),
                blocked_by=[str(x) for x in blocked_by],
            )
        )
        return Result(content=json.dumps({"task_id": tid}, ensure_ascii=False))
