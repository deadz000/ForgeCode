"""Team 核心数据结构：Team / TeammateInfo / BackendType 与异常。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class BackendType(StrEnum):
    """三种执行后端。"""

    TMUX = "tmux"
    ITERM2 = "iterm2"
    IN_PROCESS = "in-process"


@dataclass
class TeammateInfo:
    """一个 Team 队员的完整信息（spec F2）。"""

    name: str
    agent_id: str
    agent_type: str = ""  # 使用的 subagent 定义名；Fork 路径下为空串
    model: str = ""  # 模型覆盖，空表 inherit
    worktree_path: str = ""  # 绝对路径
    branch: str = ""  # 对应 worktree 分支名
    backend_type: BackendType = BackendType.IN_PROCESS
    pane_id: str = ""  # tmux pane / iterm2 split id，in-process 为空
    is_active: bool | None = None  # None/True 活跃，False 空闲；终止后从 members 移除
    plan_mode_required: bool = False
    session_dir: str = ""  # 队员独立 session 目录绝对路径

    def to_dict(self) -> dict[str, Any]:
        """序列化为 config.json 结构（backend_type 用枚举值）。"""
        return {
            "name": self.name,
            "agent_id": self.agent_id,
            "agent_type": self.agent_type,
            "model": self.model,
            "worktree_path": self.worktree_path,
            "branch": self.branch,
            "backend_type": str(self.backend_type),
            "pane_id": self.pane_id,
            "is_active": self.is_active,
            "plan_mode_required": self.plan_mode_required,
            "session_dir": self.session_dir,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TeammateInfo:
        """从 config.json 结构反序列化。"""
        backend = data.get("backend_type", "in-process")
        try:
            bt = BackendType(backend)
        except ValueError:
            bt = BackendType.IN_PROCESS
        return cls(
            name=str(data.get("name", "")),
            agent_id=str(data.get("agent_id", "")),
            agent_type=str(data.get("agent_type", "")),
            model=str(data.get("model", "")),
            worktree_path=str(data.get("worktree_path", "")),
            branch=str(data.get("branch", "")),
            backend_type=bt,
            pane_id=str(data.get("pane_id", "")),
            is_active=data.get("is_active"),
            plan_mode_required=bool(data.get("plan_mode_required", False)),
            session_dir=str(data.get("session_dir", "")),
        )


@dataclass
class Team:
    """一个长期存在的小组对象（spec F1）。"""

    name: str  # 用户给的原始名
    sanitized_name: str  # 经 sanitize 后用于路径，Team 主键
    lead_agent_id: str  # 固定 "lead"（本期 Lead = 主 Agent）
    backend: BackendType  # 全 team 默认后端；可被 member 覆盖
    description: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    members: list[TeammateInfo] = field(default_factory=list)

    # 派生路径（不持久化）
    config_dir: str = ""
    config_path: str = ""
    tasks_path: str = ""
    mailbox_dir: str = ""

    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False, compare=False)

    def to_dict(self) -> dict[str, Any]:
        """序列化 Team 到 config.json。"""
        return {
            "name": self.name,
            "sanitized_name": self.sanitized_name,
            "lead_agent_id": self.lead_agent_id,
            "backend": str(self.backend),
            "description": self.description,
            "created_at": self.created_at.isoformat(),
            "members": [m.to_dict() for m in self.members],
        }

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
        *,
        config_dir: str,
        config_path: str,
        tasks_path: str,
        mailbox_dir: str,
    ) -> Team:
        """从 config.json 结构反序列化并填充派生路径。"""
        backend = data.get("backend", "in-process")
        try:
            bt = BackendType(backend)
        except ValueError:
            bt = BackendType.IN_PROCESS
        created = data.get("created_at")
        try:
            created_dt = datetime.fromisoformat(created) if created else datetime.now()
        except (ValueError, TypeError):
            created_dt = datetime.now()
        return cls(
            name=str(data.get("name", "")),
            sanitized_name=str(data.get("sanitized_name", "")),
            lead_agent_id=str(data.get("lead_agent_id", "lead")),
            backend=bt,
            description=str(data.get("description", "")),
            created_at=created_dt,
            members=[TeammateInfo.from_dict(m) for m in data.get("members", [])],
            config_dir=config_dir,
            config_path=config_path,
            tasks_path=tasks_path,
            mailbox_dir=mailbox_dir,
        )

    # ── 成员查询工具方法（纯内存，无锁）──

    def member_by_name(self, name: str) -> TeammateInfo | None:
        for m in self.members:
            if m.name == name:
                return m
        return None

    def member_by_agent_id(self, agent_id: str) -> TeammateInfo | None:
        for m in self.members:
            if m.agent_id == agent_id:
                return m
        return None


@dataclass(frozen=True)
class LeadMessage:
    """Lead 邮箱轮询返回的消息摘要（F41a）。"""

    team_name: str
    from_: str
    type: str
    summary: str
    content: str
    timestamp: int = 0


class TeamError(Exception):
    """Team 模块异常基类。"""


class TeamNotFoundError(TeamError):
    """团队不存在。"""


class TeamHasActiveMembersError(TeamError):
    """团队还有活跃成员，非 force 拒绝删除。"""


class MemberExistsError(TeamError):
    """成员名在 Team 内已存在。"""


class MemberNotFoundError(TeamError):
    """成员不存在。"""


class InProcessTeammateNoSpawnError(TeamError):
    """in-process 后端队员禁止再 spawn 其他队员。"""
