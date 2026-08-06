"""Agent Team 模块：多 Agent 网状协作（Team / 队员 / 邮箱 / 共享任务 / 三种后端）。

顶层包导出 Manager / 类型 / 协作工具 / 邮箱 / 注册表 / 任务存储。
"""

from forgecode.team.backend import Backend, SpawnRequest, new_backend
from forgecode.team.backend.detect import detect
from forgecode.team.feature import fork_teammate_enabled
from forgecode.team.mailbox import Box
from forgecode.team.mailbox.message import Message, MessageType
from forgecode.team.manager import Manager
from forgecode.team.registry import AgentNameRegistry
from forgecode.team.spawn import (
    build_team_context_reminder,
    team_system_prompt_suffix,
    truncate_for_summary,
)
from forgecode.team.tasks import Filter, Patch, Status, Store, Task
from forgecode.team.types import (
    BackendType,
    InProcessTeammateNoSpawnError,
    LeadMessage,
    MemberExistsError,
    MemberNotFoundError,
    Team,
    TeamError,
    TeamHasActiveMembersError,
    TeammateInfo,
    TeamNotFoundError,
)

__all__ = [
    "AgentNameRegistry",
    "Backend",
    "BackendType",
    "Box",
    "Filter",
    "InProcessTeammateNoSpawnError",
    "LeadMessage",
    "Manager",
    "MemberExistsError",
    "MemberNotFoundError",
    "Message",
    "MessageType",
    "Patch",
    "SpawnRequest",
    "Status",
    "Store",
    "Task",
    "Team",
    "TeamError",
    "TeamHasActiveMembersError",
    "TeamNotFoundError",
    "TeammateInfo",
    "build_team_context_reminder",
    "detect",
    "fork_teammate_enabled",
    "new_backend",
    "team_system_prompt_suffix",
    "truncate_for_summary",
]
