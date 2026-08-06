"""TeamCreate 工具：主 Agent 调用创建 Team。"""

from __future__ import annotations

import json
from typing import Any

from forgecode.tool import Result


class TeamCreateTool:
    """创建 Team（F20-F21）。"""

    def __init__(self, mgr: Any) -> None:
        self._mgr = mgr

    read_only = False
    is_system = False
    is_teammate_only = False

    def name(self) -> str:
        return "TeamCreate"

    def description(self) -> str:
        return "创建一个 Team：主 Agent 升任 Lead，用于多 Agent 协作"

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "team_name": {"type": "string", "description": "团队名（必填）"},
                "description": {"type": "string", "description": "团队描述（可选）"},
                "agent_type": {"type": "string", "description": "保留位，本期不使用"},
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
        try:
            team = await self._mgr.create(
                name,
                agent_type=str(data.get("agent_type", "")),
                description=str(data.get("description", "")),
            )
        except Exception as e:
            return Result(content=f"TeamCreate 失败: {e}", is_error=True)
        # 设为活跃 Team（Lead 后续协作工具默认寻址）
        self._mgr.active_team_name = team.sanitized_name
        return Result(
            content=json.dumps(
                {
                    "team_name": team.sanitized_name,
                    "backend": str(team.backend),
                    "config_path": team.config_path,
                },
                ensure_ascii=False,
            )
        )
