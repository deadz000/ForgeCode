"""--team-member 自治循环（F19a/F19b）：Pane 子进程不启动 TUI。

读 mailbox → 分流消息 → run_to_completion → 通知 Lead idle → stdin Wake 等下一条。
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Any

from forgecode.agent import Agent
from forgecode.agent.team_hook import (
    IncomingMessage,
    TeammateContext,
    with_teammate_context,
)
from forgecode.conversation.history import Conversation
from forgecode.permission import Mode
from forgecode.tool.filter import FilterParams, apply_agent_tool_filter

POLL_TIMEOUT: float = 2.0

LEAD_NAME = "lead"


async def run_team_member(ctx: dict[str, Any]) -> None:
    """Pane 后端子进程主循环。ctx 含 main.py wire 好的全部依赖。"""
    args = ctx["args"]
    os.chdir(args.worktree)

    team_mgr = ctx["team_mgr"]
    team = team_mgr.get(args.team)
    if team is None:
        print(f"[team-member] 团队不存在: {args.team}", file=sys.stderr)
        return

    # 子进程与 Lead 不同进程：reload-from-disk 兜底
    from forgecode.team.persistence import reload_from_disk_locked

    try:
        async with team._lock:
            await reload_from_disk_locked(team)
    except Exception:
        pass
    mem = team.member_by_agent_id(args.agent_id)
    if mem is None:
        mem = team.member_by_name(args.member)

    print(f"[team-member] {args.member} · team={args.team} · agent={args.agent_id} · cwd={os.getcwd()}")
    sys.stdout.flush()

    # ── 构造队员 Agent（dont_ask=True，F39a）──
    catalog = ctx["subagent_catalog"]
    if args.agent_type:
        defi = catalog.resolve(args.agent_type)
        if defi is None:
            print(f"[team-member] 未知角色: {args.agent_type}", file=sys.stderr)
            return
    else:
        defi = catalog.fork_definition() or catalog.resolve("general-purpose")

    registry = ctx["registry"]
    names = [d.name for d in registry.definitions()]
    allowed = apply_agent_tool_filter(
        FilterParams(
            all=names,
            source=int(defi.source),
            background=False,
            allowed=defi.tools,
            disallowed=defi.disallowed_tools,
            teammate=True,
        )
    )

    from forgecode.agent.runtime import (
        append_reminders as _append_reminders,
    )
    from forgecode.agent.runtime import (
        new_runtime,
    )
    from forgecode.team.spawn import (
        build_team_context_reminder,
        team_system_prompt_suffix,
    )

    sys_prompt = (
        defi.system_prompt + "\n\n" + team_system_prompt_suffix()
        if defi.system_prompt
        else team_system_prompt_suffix()
    )
    sub_runtime = new_runtime(os.getcwd())
    plan_required = bool(getattr(args, "plan_mode", False)) or (defi.permission_mode is Mode.PLAN)
    agent = Agent(
        ctx["provider"],
        registry,
        ctx["engine"],
        ctx["version"],
        runtime=sub_runtime,
        allowed_tools=allowed,
        system_prompt=sys_prompt,
        max_turns=defi.max_turns,
        permission_mode=Mode.PLAN if plan_required else defi.permission_mode,
        dont_ask=True,
        hook_engine=ctx["hook_engine"],
    )
    conv = Conversation()

    from forgecode.team.mailbox import Box

    box = Box(team.mailbox_dir)
    roster = [m.name for m in team.members]
    _append_reminders(
        sub_runtime,
        [build_team_context_reminder(team.sanitized_name, args.member, args.agent_id, os.getcwd(), roster)],
    )

    async def _read_unread() -> tuple[list[int], list[IncomingMessage]]:
        idx, msgs = await box.read_unread(args.agent_id)
        return idx, [
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

    async def _mark_read(indices: list[int]) -> None:
        await box.mark_read(args.agent_id, indices)

    tc = TeammateContext(
        team_name=team.sanitized_name,
        member_name=args.member,
        agent_id=args.agent_id,
        backend_type=str(team.backend),
        read_unread=_read_unread,
        mark_read=_mark_read,
        mailbox_dir=team.mailbox_dir,
    )

    # ── stdin reader：回车唤醒即时轮询 ──
    wake_event = asyncio.Event()
    reader_task = asyncio.create_task(_stdin_reader(wake_event))

    try:
        await _member_loop(
            ctx,
            team_mgr,
            team,
            args,
            mem,
            agent,
            conv,
            box,
            tc,
            wake_event,
        )
    finally:
        reader_task.cancel()
        try:
            await reader_task
        except asyncio.CancelledError:
            pass


async def _member_loop(
    ctx: dict[str, Any],
    team_mgr: Any,
    team: Any,
    args: Any,
    mem: Any,
    agent: Agent,
    conv: Conversation,
    box: Any,
    tc: TeammateContext,
    wake_event: asyncio.Event,
) -> None:
    """读 mailbox → 分流 → run_to_completion → 通知 Lead idle。"""
    from forgecode.team.mailbox.message import Message, MessageType

    while True:
        # 检测 mailbox 目录被删（Lead /team delete）→ 优雅退出
        if not os.path.isdir(team.mailbox_dir):
            print("[team-member] mailbox 已消失，退出", file=sys.stderr)
            break

        idx, msgs = await box.read_unread(args.agent_id)
        if not msgs:
            try:
                await asyncio.wait_for(wake_event.wait(), timeout=POLL_TIMEOUT)
                wake_event.clear()
            except TimeoutError:
                pass
            continue

        # 分流消息
        task_text: str | None = None
        shutdown = False
        approved = False
        for m in msgs:
            if m.type == MessageType.TEXT:
                task_text = m.content
            elif m.type == MessageType.PLAN_APPROVAL_RESPONSE:
                payload = m.payload or {}
                if payload.get("approve"):
                    approved = True
                    task_text = "[plan-approved] Lead 已批准计划，开始执行。"
                else:
                    task_text = (
                        "Lead 驳回了计划，反馈：" + str(payload.get("feedback", "")) + "。请调整后重新提交。"
                    )
            elif m.type == MessageType.SHUTDOWN_REQUEST:
                shutdown = True
        await box.mark_read(args.agent_id, idx)

        if shutdown:
            await box.write(
                team.lead_agent_id,
                Message(
                    from_=args.member,
                    to=LEAD_NAME,
                    type=MessageType.SHUTDOWN_RESPONSE,
                    summary="shutdown ok",
                    content="member stopping",
                ),
            )
            print("[team-member] 收到 shutdown_request，退出", file=sys.stderr)
            break

        if task_text is None:
            continue

        if approved:
            agent.permission_mode = Mode.DEFAULT

        events: asyncio.Queue[Any] = asyncio.Queue(maxsize=64)
        printer = asyncio.create_task(_print_events(events))
        try:
            with with_teammate_context(tc):
                final = await agent.run_to_completion(conv, task_text, events)  # type: ignore[attr-defined]
            if final.strip():
                print(final)
        except Exception as e:
            print(f"[team-member] 执行异常: {e}", file=sys.stderr)
        finally:
            printer.cancel()
            try:
                await events.put(None)
            except asyncio.QueueFull:
                pass
            try:
                await printer
            except asyncio.CancelledError:
                pass

        # 通知 Lead idle（F45）
        if mem is not None:
            try:
                await team_mgr.set_member_active(team, mem.name, False)
            except Exception as e:
                print(f"[team-member] set_member_active 失败: {e}", file=sys.stderr)
        await box.write(
            team.lead_agent_id,
            Message(
                from_=args.member,
                to=LEAD_NAME,
                type=MessageType.TEXT,
                summary=f"{args.member} idle",
                content=f"agent {args.agent_id} finished work, available for new tasks",
            ),
        )
        sys.stdout.flush()


async def _print_events(events: asyncio.Queue[Any]) -> None:
    """把内部事件转 stdout 只读日志流（F19b）。"""
    while True:
        ev = await events.get()
        if ev is None:
            break
        if ev.tool is not None:
            if ev.tool.phase.name == "START":
                print(f"● {ev.tool.name}({ev.tool.args})")
            else:
                print(f"  ⎿ {ev.tool.result}")
            sys.stdout.flush()
        elif ev.text:
            print(ev.text, end="")
            sys.stdout.flush()
        elif ev.err is not None:
            print(f"✕ {ev.err}", file=sys.stderr)


async def _stdin_reader(wake_event: asyncio.Event) -> None:
    """读 stdin 行；任何回车都置 wake_event。"""
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)
    try:
        while True:
            line = await reader.readline()
            if not line:
                break
            wake_event.set()
    except (OSError, ValueError):
        pass
