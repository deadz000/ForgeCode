"""后端抽象：Backend Protocol + SpawnRequest + new_backend 工厂。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from forgecode.team.types import BackendType


@dataclass
class SpawnRequest:
    """一次队员 spawn 的完整入参（F13）。"""

    team_name: str
    member_name: str
    agent_id: str
    worktree_path: str
    session_dir: str
    agent_type: str
    model: str
    initial_prompt: str
    plan_mode_required: bool

    # in-process 专用——同进程后端直接复用这三个对象
    sub_agent: Any = None  # agent.Agent
    conv: Any = None  # conversation.Conversation
    task_mgr: Any = None  # task.Manager


class Backend(Protocol):
    """统一后端接口（F12）。"""

    def type(self) -> BackendType: ...

    # spawn 返回 (pane_id, agent_id)；Pane 后端 pane_id 非空，in-process 为空串
    async def spawn(self, req: SpawnRequest) -> tuple[str, str]: ...

    # wake 用于消息到达时唤醒目标 pane；in-process 为 no-op
    async def wake(self, pane_id: str, agent_id: str) -> None: ...

    # kill 终止 pane（Pane 后端）或 cancel task（in-process）
    async def kill(self, pane_id: str, agent_id: str) -> None: ...


def new_backend(t: BackendType, **deps: Any) -> Backend:
    """按类型构造后端实例。

    deps: inprocess 需要 task_mgr；tmux/iterm2 无依赖。
    """
    if t is BackendType.TMUX:
        from forgecode.team.backend.tmux import TmuxBackend

        return TmuxBackend()
    if t is BackendType.ITERM2:
        from forgecode.team.backend.iterm2 import Iterm2Backend

        return Iterm2Backend()
    if t is BackendType.IN_PROCESS:
        from forgecode.team.backend.inprocess import InProcessBackend

        return InProcessBackend(task_mgr=deps.get("task_mgr"))
    raise ValueError(f"未知后端: {t}")
