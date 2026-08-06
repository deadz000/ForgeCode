"""TeamDelete 工具：主 Agent 删除 Team。"""

from __future__ import annotations

import json
from typing import Any

from forgecode.team.types import TeamHasActiveMembersError, TeamNotFoundError
from forgecode.tool import Result


class TeamDeleteTool:
    """删除 Team（F22-F23）。"""

    def __init__(self, mgr: Any) -> None:
        self._mgr = mgr

    read_only = False
    is_system = False
    is_teammate_only = False

    def name(self) -> str:
        return "TeamDelete"

    def description(self) -> str:
        return "删除一个 Team（有活跃成员时需 force）"

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "team_name": {"type": "string", "description": "团队名（必填）"},
                "force": {"type": "boolean", "description": "true 时忽略活跃成员直接删除"},
            },
            "required": ["team_name"],
        }

    async def execute(self, args: str) -> Result:
        try:
            data = json.loads(args) if args.strip() else {}
        except json.JSONDecodeError as e:
            return Result(content=f"参数 JSON 解析失败: {e}", is_error=True)
        name = str(data.get("team_name", "")).strip()
        if not name:
            return Result(content="缺少必填参数 team_name", is_error=True)
        force = bool(data.get("force", False))
        try:
            await self._mgr.delete(name, force)
        except TeamNotFoundError as e:
            return Result(content=f"TeamDelete 失败: {e}", is_error=True)
        except TeamHasActiveMembersError as e:
            return Result(content=f"TeamDelete 失败: {e}", is_error=True)
        except Exception as e:
            return Result(content=f"TeamDelete 失败: {e}", is_error=True)
        if getattr(self._mgr, "active_team_name", None) == name:
            self._mgr.active_team_name = None
        return Result(content=json.dumps({"team_name": name, "deleted": True}, ensure_ascii=False))
