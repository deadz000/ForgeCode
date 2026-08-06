"""Team Manager：创建/查询/删除 + 成员操作 + 任务完成回调 + Lead 邮箱轮询。

跨进程并发由 Team._lock + reload_from_disk_locked 兜底（F19c）。
"""

from __future__ import annotations

import asyncio
import shutil
import sys
from pathlib import Path
from typing import Any

from forgecode.team.backend import new_backend
from forgecode.team.mailbox import Box
from forgecode.team.mailbox.message import Message, MessageType
from forgecode.team.persistence import (
    atomic_write_json,
    read_json,
    reload_from_disk_locked,
    sanitize,
)
from forgecode.team.types import (
    LeadMessage,
    MemberExistsError,
    MemberNotFoundError,
    Team,
    TeamHasActiveMembersError,
    TeammateInfo,
    TeamNotFoundError,
)
from forgecode.worktree import ExitOptions

TEAMS_DIR_NAME = ".forgecode"
TEAMS_SUBDIR = "teams"
LEAD_AGENT_ID = "lead"


class Manager:
    """管理 Team 全生命周期（F3-F10）。"""

    def __init__(
        self,
        home_dir: str | Path,
        project_root: str | Path,
        wt_mgr: Any = None,
        task_mgr: Any = None,
        reg: Any = None,
    ) -> None:
        self.teams_dir = Path(home_dir) / TEAMS_DIR_NAME / TEAMS_SUBDIR
        self.project_root = str(project_root)
        self.wt_mgr = wt_mgr
        self.task_mgr = task_mgr
        self.registry = reg
        self._lock = asyncio.Lock()
        self.teams: dict[str, Team] = {}
        # Lead 协作工具默认寻址的活跃 Team（TeamCreate 后设置）
        self.active_team_name: str | None = None
        # spawn 依赖（main.py wire 注入）
        self._spawn_deps: dict[str, Any] = {}

        # 校验目录可写；失败抛异常（启动方降级为 None）
        self.teams_dir.mkdir(parents=True, exist_ok=True)

        # 扫描还原
        self._scan()

    def bind_spawn_deps(
        self,
        *,
        provider: Any = None,
        engine: Any = None,
        registry: Any = None,
        catalog: Any = None,
        version: str = "",
        hook_engine: Any = None,
        fork_enabled: bool = False,
    ) -> None:
        """注入 in-process 队员构造所需依赖（main.py 调用）。"""
        self._spawn_deps = {
            "provider": provider,
            "engine": engine,
            "registry": registry,
            "catalog": catalog,
            "version": version,
            "hook_engine": hook_engine,
            "fork_enabled": fork_enabled,
        }

    async def spawn_teammate(self, req: Any) -> str:
        """队员 spawn 主流程（委托 spawn.py）。"""
        from forgecode.team.spawn import spawn_teammate

        return await spawn_teammate(self, req)

    def _scan(self) -> None:
        """扫描 teams 目录还原；解析失败的子目录跳过并 stderr 警告。"""
        if not self.teams_dir.is_dir():
            return
        for p in sorted(self.teams_dir.iterdir()):
            if not p.is_dir():
                continue
            cfg = p / "config.json"
            if not cfg.is_file():
                continue
            try:
                data = read_json(cfg)
            except Exception as e:
                print(f"team {p.name}: config 解析失败, skipped: {e}", file=sys.stderr)
                continue
            if not isinstance(data, dict):
                print(f"team {p.name}: config 非法, skipped", file=sys.stderr)
                continue
            try:
                team = Team.from_dict(
                    data,
                    config_dir=str(p),
                    config_path=str(cfg),
                    tasks_path=str(p / "tasks.json"),
                    mailbox_dir=str(p / "mailbox"),
                )
            except Exception as e:
                print(f"team {p.name}: 反序列化失败, skipped: {e}", file=sys.stderr)
                continue
            if not team.sanitized_name:
                print(f"team {p.name}: 缺少 sanitized_name, skipped", file=sys.stderr)
                continue
            self.teams[team.sanitized_name] = team

    # ── 查询 ─────────────────────────────────────

    def get(self, name: str) -> Team | None:
        """按 sanitized name 查询。"""
        return self.teams.get(name)

    def list_(self) -> list[Team]:
        """按创建时间排序返回所有 Team。"""
        return sorted(self.teams.values(), key=lambda t: t.created_at)

    # ── 创建 / 删除 ──────────────────────────────

    async def create(self, name: str, agent_type: str = "", description: str = "") -> Team:
        """创建 Team（F5）。同名冲突自动追加 -2 / -3。"""
        sanitized = sanitize(name)
        if not sanitized:
            raise ValueError(f"非法团队名: {name!r}")
        base = sanitized
        i = 2
        while sanitized in self.teams or (self.teams_dir / sanitized).exists():
            sanitized = f"{base}-{i}"
            i += 1

        from forgecode.team.backend.detect import detect

        backend = detect()
        config_dir = self.teams_dir / sanitized
        mailbox_dir = config_dir / "mailbox"
        try:
            config_dir.mkdir(parents=True, exist_ok=False)
        except FileExistsError as e:
            raise ValueError(f"团队目录已存在: {config_dir}") from e
        mailbox_dir.mkdir(parents=True, exist_ok=True)

        team = Team(
            name=name,
            sanitized_name=sanitized,
            lead_agent_id=LEAD_AGENT_ID,
            backend=backend,
            description=description,
            members=[TeammateInfo(name=LEAD_AGENT_ID, agent_id=LEAD_AGENT_ID, is_active=None)],
            config_dir=str(config_dir),
            config_path=str(config_dir / "config.json"),
            tasks_path=str(config_dir / "tasks.json"),
            mailbox_dir=str(mailbox_dir),
        )
        try:
            atomic_write_json(team.config_path, team.to_dict())
        except Exception:
            shutil.rmtree(config_dir, ignore_errors=True)
            raise
        async with self._lock:
            self.teams[sanitized] = team
        return team

    async def delete(self, name: str, force: bool = False) -> None:
        """删除 Team（F7 + F66）。非 force 时拒绝活跃成员。"""
        team = self.get(name)
        if team is None:
            raise TeamNotFoundError(name)
        async with team._lock:
            if not force:
                for m in team.members:
                    if m.name == LEAD_AGENT_ID:
                        continue
                    if m.is_active is not False:
                        raise TeamHasActiveMembersError(
                            f"团队 {name} 仍有活跃成员 {m.name}，无法删除（或使用 --force）"
                        )

            # 1. kill 每个非 lead 成员（best-effort）
            for m in team.members:
                if m.name == LEAD_AGENT_ID:
                    continue
                if m.pane_id or m.backend_type.value != "in-process":
                    try:
                        be = new_backend(m.backend_type, task_mgr=self.task_mgr)
                        await be.kill(m.pane_id, m.agent_id)
                    except Exception as e:
                        print(f"team delete: kill {m.name} 失败: {e}", file=sys.stderr)
                elif self.task_mgr is not None:
                    try:
                        await self.task_mgr.stop(m.agent_id)
                    except Exception as e:
                        print(f"team delete: stop {m.name} 失败: {e}", file=sys.stderr)

            # 2. 清理 worktree 与 session 目录
            await self._cleanup_member_resources(team)

            # 3. 删整个 Team 目录
            shutil.rmtree(team.config_dir, ignore_errors=True)

        async with self._lock:
            self.teams.pop(team.sanitized_name, None)

    async def _cleanup_member_resources(self, team: Team) -> None:
        """删除所有成员的 worktree 与 session 目录（best-effort）。"""
        for m in team.members:
            if m.name == LEAD_AGENT_ID:
                continue
            if m.session_dir:
                shutil.rmtree(m.session_dir, ignore_errors=True)
            if self.wt_mgr is not None and m.worktree_path:
                for wt in self.wt_mgr.list():
                    if wt.path == m.worktree_path:
                        try:
                            await self.wt_mgr.remove(wt.name, ExitOptions(discard_changes=True))
                        except Exception as e:
                            print(f"team delete: worktree {wt.name} 清理失败: {e}", file=sys.stderr)
                        break

    # ── 成员操作（跨进程 reload 兜底）──────────────

    async def add_member(self, team: Team, info: TeammateInfo) -> None:
        """给 Team 添加成员并持久化（F8）。"""
        async with team._lock:
            await reload_from_disk_locked(team)
            if team.member_by_name(info.name) is not None:
                raise MemberExistsError(info.name)
            team.members.append(info)
            atomic_write_json(team.config_path, team.to_dict())

    async def set_member_active(self, team: Team, name: str, active: bool) -> None:
        """更新成员活跃状态并持久化（F9）。"""
        async with team._lock:
            await reload_from_disk_locked(team)
            m = team.member_by_name(name)
            if m is None:
                raise MemberNotFoundError(name)
            m.is_active = active
            atomic_write_json(team.config_path, team.to_dict())

    async def remove_member(self, team: Team, name: str) -> None:
        """从 Team 移除成员并持久化（F10）。"""
        async with team._lock:
            await reload_from_disk_locked(team)
            before = len(team.members)
            team.members = [m for m in team.members if m.name != name]
            if len(team.members) == before:
                raise MemberNotFoundError(name)
            atomic_write_json(team.config_path, team.to_dict())

    # ── 任务完成回调（F45）────────────────────────

    async def handle_task_done(self, agent_id: str) -> None:
        """队员 run_to_completion 结束：标 idle + 给 Lead 邮箱写 idle 通知。"""
        if self.registry is None:
            return
        name = self.registry.name_of(agent_id)
        if not name:
            return
        for team in self.teams.values():
            if team.member_by_agent_id(agent_id) is None:
                continue
            try:
                await self.set_member_active(team, name, False)
            except MemberNotFoundError:
                return
            box = Box(team.mailbox_dir)
            await box.write(
                team.lead_agent_id,
                Message(
                    from_=name,
                    to=team.lead_agent_id,
                    type=MessageType.TEXT,
                    summary=f"{name} idle",
                    content=f"agent {agent_id} finished work, available for new tasks",
                ),
            )
            return

    async def kill_member(self, team_name: str, member_name: str) -> bool:
        """杀掉指定队员（F62）：kill pane/task 后移除成员。返回是否找到。"""
        team = self.get(team_name)
        if team is None:
            return False
        m = team.member_by_name(member_name)
        if m is None:
            return False
        try:
            if m.pane_id or m.backend_type.value != "in-process":
                be = new_backend(m.backend_type, task_mgr=self.task_mgr)
                await be.kill(m.pane_id, m.agent_id)
            elif self.task_mgr is not None:
                await self.task_mgr.stop(m.agent_id)
        except Exception as e:
            print(f"team kill {member_name} 失败: {e}", file=sys.stderr)
        if self.registry is not None:
            self.registry.unregister(member_name)
        try:
            await self.remove_member(team, member_name)
        except Exception as e:
            print(f"team kill: remove_member 失败: {e}", file=sys.stderr)
        return True

    # ── Lead 邮箱轮询（F41a）──────────────────────

    async def poll_lead_mailboxes(self) -> list[LeadMessage]:
        """轮询所有 Team 的 Lead 邮箱，读未读并标 read。"""
        out: list[LeadMessage] = []
        for team in self.teams.values():
            box = Box(team.mailbox_dir)
            idx, msgs = await box.read_unread(team.lead_agent_id)
            if not idx:
                continue
            for m in msgs:
                out.append(
                    LeadMessage(
                        team_name=team.sanitized_name,
                        from_=m.from_,
                        type=str(m.type),
                        summary=m.summary,
                        content=m.content,
                        timestamp=m.timestamp,
                    )
                )
            try:
                await box.mark_read(team.lead_agent_id, idx)
            except Exception as e:
                print(f"team: mark lead mailbox read 失败: {e}", file=sys.stderr)
        return out
