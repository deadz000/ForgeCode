"""SendMessage 工具：Team 邮箱消息（统一 ch13 后台续派分流）。

Team 上下文（队员/Lead 有 active team）走邮箱 + wake + in-process 续派；
否则回退 ch13 后台任务 send_message（name + message）。
"""

from __future__ import annotations

import json
import time
from typing import Any

from forgecode.team.mailbox import Box
from forgecode.team.mailbox.message import Message, MessageType
from forgecode.team.tools.common import current_team_name, is_lead_call
from forgecode.tool import Result


class SendMessageTool:
    """Team 邮箱消息发送（F31-F34）；非 Team 场景回退 ch13 后台任务。"""

    def __init__(self, mgr: Any, fallback: Any = None) -> None:
        self._mgr = mgr
        self._fallback = fallback  # ch13 后台任务 SendMessageTool

    read_only = False
    is_system = False
    is_teammate_only = False

    def name(self) -> str:
        return "SendMessage"

    def description(self) -> str:
        return (
            "Team 上下文：给队员/Lead 发消息（to=名称/id/* 广播）。"
            " 非 Team 上下文：给已完成的同名后台 Agent 续派新任务（name + message）"
        )

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "接收者：队员名 / agent_id / *（广播）"},
                "summary": {"type": "string", "description": "纯文本消息必填，5-10 词摘要"},
                "message": {"type": "string", "description": "纯文本消息体"},
                "type": {
                    "type": "string",
                    "description": "text / shutdown_request / shutdown_response / plan_approval_response",
                },
                "payload": {"type": "object", "description": "结构化消息载荷"},
                "name": {"type": "string", "description": "非 Team 上下文后台任务续派用 name"},
            },
        }

    async def execute(self, args: str) -> Result:
        try:
            data = json.loads(args) if args.strip() else {}
        except json.JSONDecodeError as e:
            return Result(content=f"参数 JSON 解析失败: {e}", is_error=True)

        team_name = current_team_name(self._mgr)
        if not team_name:
            # 非 Team 上下文 → ch13 后台续派
            if self._fallback is not None:
                result = await self._fallback.execute(args)
                assert isinstance(result, Result)
                return result
            return Result(content="不在任何 Team 上下文中，且后台任务工具不可用", is_error=True)

        team = self._mgr.get(team_name)
        if team is None:
            return Result(content=f"团队不存在: {team_name}", is_error=True)

        mtype_s = str(data.get("type", "text"))
        try:
            mtype = MessageType(mtype_s)
        except ValueError:
            return Result(content=f"未知消息类型: {mtype_s}", is_error=True)

        to_spec = str(data.get("to", "")).strip()
        if not to_spec:
            return Result(content="缺少必填参数 to", is_error=True)

        summary = str(data.get("summary", ""))
        message = str(data.get("message", ""))
        payload = data.get("payload")
        if not summary and mtype is MessageType.TEXT:
            summary = message[:60] if message else ""

        lead = is_lead_call()
        if mtype is MessageType.PLAN_APPROVAL_RESPONSE and not lead:
            return Result(content="plan_approval_response 仅 Lead 可发送", is_error=True)
        if mtype is MessageType.SHUTDOWN_RESPONSE and to_spec not in ("lead", team.lead_agent_id):
            return Result(content="shutdown_response 只能发送给 Lead", is_error=True)

        sender = self._sender_name()
        box = Box(team.mailbox_dir)
        targets = self._resolve_targets(team, to_spec, sender)
        if not targets:
            return Result(content=f"无法解析接收者: {to_spec}", is_error=True)

        delivered: list[str] = []
        ts = int(time.time())
        for mem in targets:
            msg = Message(
                from_=sender,
                to=mem.name,
                type=mtype,
                summary=summary,
                content=message,
                payload=payload,
                timestamp=ts,
            )
            await box.write(mem.agent_id, msg)
            delivered.append(mem.agent_id)
            await self._wake_or_resume(team, mem, message)

        return Result(
            content=json.dumps(
                {"delivered_to": delivered, "timestamp": ts},
                ensure_ascii=False,
            )
        )

    # ── 内部 ─────────────────────────────────────

    def _sender_name(self) -> str:
        """当前调用者名称：Lead 固定 "lead"，队员取 member_name。"""
        from forgecode.agent.team_hook import teammate_context_from_ctx

        tc = teammate_context_from_ctx()
        return tc.member_name if tc is not None else "lead"

    def _resolve_targets(self, team: Any, to_spec: str, sender: str) -> list[Any]:
        """解析目标成员列表：* 广播（除自己） / 名称 / agent_id。"""
        members = [m for m in team.members if m.name != "lead"]
        if to_spec == "*":
            return [m for m in members if m.name != sender]
        for m in members:
            if m.name == to_spec:
                return [m]
        for m in members:
            if m.agent_id == to_spec:
                return [m]
        # Lead 寻址
        if to_spec in ("lead", team.lead_agent_id):
            lead_mem = team.member_by_name("lead")
            if lead_mem is not None:
                return [lead_mem]
        return []

    async def _wake_or_resume(self, team: Any, mem: Any, message: str) -> None:
        """Pane 后端 wake；in-process 已 stop 则续派（F46/T31）。"""
        from forgecode.team.backend import new_backend
        from forgecode.team.types import BackendType

        if mem.name == "lead" or mem.backend_type is not BackendType.IN_PROCESS:
            if mem.backend_type is not BackendType.IN_PROCESS and mem.pane_id:
                try:
                    be = new_backend(mem.backend_type, task_mgr=self._mgr.task_mgr)
                    await be.wake(mem.pane_id, mem.agent_id)
                except Exception:
                    pass
            return

        if self._mgr.task_mgr is None:
            return
        bt = self._mgr.task_mgr.get(mem.agent_id)
        if bt is not None and bt.status.name != "RUNNING":
            try:
                await self._mgr.set_member_active(team, mem.name, True)
            except Exception:
                pass
            try:
                await self._mgr.task_mgr.send_message(mem.name, message)
            except Exception:
                pass
