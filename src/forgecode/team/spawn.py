"""spawn_teammate 主流程：worktree → session → 子 Agent → backend.spawn → 注册。

in-process 后端构造子 Agent 并注入 TeammateContext；Pane 后端预写 mailbox。
"""

from __future__ import annotations

import json
import secrets
from typing import Any

from forgecode.agent.team_hook import (
    IncomingMessage,
    TeammateContext,
    TeamSpawnRequest,
    with_teammate_context,
)
from forgecode.conversation.history import Conversation
from forgecode.permission import Mode
from forgecode.tool.filter import FilterParams, apply_agent_tool_filter

# 队员系统提示词附录（F39）
TEAM_SYSTEM_PROMPT_SUFFIX = """\
IMPORTANT: You are running as an agent in a team.
Just writing a response in text is not visible to others
on your team - you MUST use the SendMessage tool.
The user interacts primarily with the team lead.
Your work is coordinated through the task system
and teammate messaging.
"""


def team_system_prompt_suffix() -> str:
    """返回队员系统提示词附录（F39）。"""
    return TEAM_SYSTEM_PROMPT_SUFFIX


def truncate_for_summary(prompt: str, limit: int = 60) -> str:
    """给初始任务 mailbox 消息生成 5-10 词 summary（取前 limit 字符）。"""
    flat = " ".join(prompt.split())
    return flat[:limit]


def build_team_context_reminder(
    team_name: str,
    member_name: str,
    agent_id: str,
    worktree_path: str,
    members: list[str],
) -> str:
    """构造 <team-context> reminder（F40）。"""
    roster = ", ".join(members) if members else "(仅你)"
    return (
        "<team-context>\n"
        f"team: {team_name}\n"
        f"你的成员名: {member_name}\n"
        f"你的 agent_id: {agent_id}\n"
        f"worktree 目录: {worktree_path}\n"
        f"当前团队成员: {roster}\n"
        "</team-context>"
    )


def _new_agent_id() -> str:
    return f"agent-{secrets.token_hex(7)}"


def _default_member_name() -> str:
    return f"teammate-{secrets.token_hex(3)}"


def _is_inprocess(backend_type: Any) -> bool:
    from forgecode.team.types import BackendType

    return backend_type is BackendType.IN_PROCESS


async def spawn_teammate(mgr: Any, req: TeamSpawnRequest) -> str:
    """队员 spawn 主流程（F25）。返回 JSON 字符串。"""
    team = mgr.get(req.team_name)
    if team is None:
        raise LookupError(f"团队不存在: {req.team_name}")

    member_name = req.member_name or _default_member_name()
    if team.member_by_name(member_name) is not None:
        raise ValueError(f"成员名已存在: {member_name}")

    deps = mgr._spawn_deps
    catalog = deps.get("catalog")
    if catalog is None:
        raise RuntimeError("Team spawn 依赖未注入（catalog 缺失）")

    # ── resolve 定义 ──
    if req.agent_type:
        defi = catalog.resolve(req.agent_type)
        if defi is None:
            raise ValueError(f"未知 subagent_type: {req.agent_type}")
    else:
        if deps.get("fork_enabled") and catalog.fork_definition() is not None:
            defi = catalog.fork_definition()
        else:
            defi = catalog.resolve("general-purpose") or catalog.fork_definition()

    # ── 创建 Worktree（嵌套 slug: team-<sanitized>/<member>）──
    if mgr.wt_mgr is None:
        raise RuntimeError("worktree manager not configured")
    wt_name = f"team-{team.sanitized_name}/{member_name}"
    wt = await mgr.wt_mgr.create(wt_name, "HEAD", manual=False)

    # ── 申请 session 目录（项目根下）──
    from forgecode.compact.state import new_session_context

    ses_ctx = new_session_context(mgr.project_root)
    session_dir = ses_ctx.session_dir

    agent_id = _new_agent_id()

    # ── 计算 allowed tools（teammate=True）──
    registry = deps.get("registry")
    all_names = [d.name for d in registry.definitions()] if registry is not None else []
    allowed = apply_agent_tool_filter(
        FilterParams(
            all=all_names,
            source=int(defi.source),
            background=False,
            allowed=defi.tools,
            disallowed=defi.disallowed_tools,
            teammate=True,
        )
    )

    # ── system_prompt：定义正文 + 队员附录 ──
    if defi.system_prompt:
        sys_prompt = defi.system_prompt + "\n\n" + team_system_prompt_suffix()
    else:
        sys_prompt = team_system_prompt_suffix()

    # ── 后端决定 ──
    from forgecode.team.backend import SpawnRequest, new_backend
    from forgecode.team.types import TeammateInfo

    be = new_backend(team.backend, task_mgr=mgr.task_mgr)
    is_inproc = _is_inprocess(team.backend)

    plan_required = req.plan_mode_required or (defi.permission_mode is Mode.PLAN)

    sr = SpawnRequest(
        team_name=team.sanitized_name,
        member_name=member_name,
        agent_id=agent_id,
        worktree_path=wt.path,
        session_dir=session_dir,
        agent_type=req.agent_type,
        model=req.model,
        initial_prompt=req.prompt,
        plan_mode_required=plan_required,
    )

    from forgecode.team.mailbox import Box
    from forgecode.team.mailbox.message import Message, MessageType

    box = Box(team.mailbox_dir)

    if is_inproc:
        # ── in-process：构造子 Agent + Conv，注入 TeammateContext ──
        from forgecode.agent import Agent

        provider = deps.get("provider")
        engine = deps.get("engine")
        if provider is None or engine is None or registry is None:
            raise RuntimeError("Team spawn 依赖未注入（provider/engine/registry）")
        from forgecode.agent.runtime import new_runtime

        sub_runtime = new_runtime(wt.path)
        sub_agent = Agent(
            provider,
            registry,
            engine,
            deps.get("version", ""),
            runtime=sub_runtime,
            allowed_tools=allowed,
            system_prompt=sys_prompt,
            max_turns=defi.max_turns,
            permission_mode=Mode.PLAN if plan_required else defi.permission_mode,
            dont_ask=True,  # F39a：队员一律 dont_ask
            hook_engine=deps.get("hook_engine"),
        )
        sub_conv = Conversation()
        tc = _build_teammate_context(team.sanitized_name, member_name, agent_id, team.backend, box)
        from forgecode.agent.runtime import append_reminders as _append_reminders

        _append_reminders(
            sub_runtime,
            [build_team_context_reminder(team.sanitized_name, member_name, agent_id, wt.path, _roster(team))],
        )
        sr.sub_agent = sub_agent
        sr.conv = sub_conv
        sr.task_mgr = mgr.task_mgr

        from forgecode.tool.ctx import with_cwd

        # in-process 队员在 worktree 内运行（AC25）：ctx cwd 注入后，
        # 工具 resolve_path / bash 子进程都落到 worktree，实现文件系统隔离。
        with with_cwd(wt.path), with_teammate_context(tc):
            pane_id, _ = await be.spawn(sr)
    else:
        # ── Pane 后端：预写 mailbox（F13）──
        await box.write(
            agent_id,
            Message(
                from_=LEAD_NAME,
                to=member_name,
                type=MessageType.TEXT,
                summary=truncate_for_summary(req.prompt),
                content=req.prompt,
            ),
        )
        pane_id, _ = await be.spawn(sr)

    # ── 注册 + 落盘成员 ──
    if mgr.registry is not None:
        mgr.registry.register(member_name, agent_id)
    info = TeammateInfo(
        name=member_name,
        agent_id=agent_id,
        agent_type=req.agent_type,
        model=req.model,
        worktree_path=wt.path,
        branch=wt.branch,
        backend_type=team.backend,
        pane_id=pane_id,
        is_active=True,
        plan_mode_required=plan_required,
        session_dir=session_dir,
    )
    await mgr.add_member(team, info)

    return json.dumps(
        {
            "member_name": member_name,
            "agent_id": agent_id,
            "worktree": wt.path,
            "backend": str(team.backend),
            "pane_id": pane_id,
        },
        ensure_ascii=False,
    )


LEAD_NAME = "lead"


def _roster(team: Any) -> list[str]:
    return [m.name for m in team.members]


def _build_teammate_context(
    team_name: str,
    member_name: str,
    agent_id: str,
    backend_type: Any,
    box: Any,
) -> TeammateContext:
    """构造队员上下文（含 mailbox 闭包）。"""

    async def _read_unread() -> tuple[list[int], list[IncomingMessage]]:
        idx, msgs = await box.read_unread(agent_id)
        incoming = [
            IncomingMessage(
                from_=m.from_,
                type=str(m.type),
                summary=m.summary,
                content=m.content,
                payload=m.payload,
                timestamp=m.timestamp,
            )
            for m in msgs
        ]
        return idx, incoming

    async def _mark_read(indices: list[int]) -> None:
        await box.mark_read(agent_id, indices)

    return TeammateContext(
        team_name=team_name,
        member_name=member_name,
        agent_id=agent_id,
        backend_type=str(backend_type),
        read_unread=_read_unread,
        mark_read=_mark_read,
        mailbox_dir=str(box._dir) if hasattr(box, "_dir") else "",
    )
