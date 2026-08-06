"""In-process 后端：同进程 asyncio task 跑队员（F18）。"""

from __future__ import annotations

from typing import Any

from forgecode.team.backend import SpawnRequest
from forgecode.team.types import BackendType


class InProcessBackend:
    """同进程后端：复用 task.Manager.launch。"""

    def __init__(self, task_mgr: Any = None) -> None:
        self._task_mgr = task_mgr

    def type(self) -> BackendType:
        return BackendType.IN_PROCESS

    async def spawn(self, req: SpawnRequest) -> tuple[str, str]:
        """起 asyncio task 跑 run_to_completion；返回 ("", agent_id)。

        agent_id 复用为后台任务 id，保证 SendMessage 续派可解析。
        """
        if self._task_mgr is None or req.sub_agent is None or req.conv is None:
            raise RuntimeError("in-process 后端缺少 task_mgr / sub_agent / conv")
        await self._task_mgr.launch(
            req.sub_agent,
            req.conv,
            req.member_name,
            req.initial_prompt,
            task_id=req.agent_id,
        )
        return "", req.agent_id

    async def wake(self, pane_id: str, agent_id: str) -> None:
        """no-op：同进程，下一轮 Loop 自动读邮箱。"""

    async def kill(self, pane_id: str, agent_id: str) -> None:
        """取消运行中的后台 task。"""
        if self._task_mgr is not None:
            await self._task_mgr.stop(agent_id)
