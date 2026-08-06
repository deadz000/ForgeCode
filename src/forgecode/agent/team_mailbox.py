"""队员 Loop 头部邮箱注入：<incoming-messages> reminder + 审批处理。

在 agent.Agent.run 每轮迭代调 LLM 之前调用 ingest_team_mailbox(self)；
非队员上下文（无 TeammateContext）时静默 no-op。
"""

from __future__ import annotations

from typing import Any

from forgecode.agent.team_hook import IncomingMessage, teammate_context_from_ctx
from forgecode.permission import Mode

_CONTENT_PREVIEW: int = 200


def build_incoming_messages_reminder(msgs: list[IncomingMessage]) -> str:
    """构造 <incoming-messages> reminder（F42）。"""
    lines: list[str] = [f"收到 {len(msgs)} 条新消息:"]
    for i, m in enumerate(msgs, 1):
        content = m.content or ""
        if len(content) > _CONTENT_PREVIEW:
            content = content[:_CONTENT_PREVIEW] + "…"
        lines.append(f"[{i}] 来自 {m.from_}(type={m.type}): {m.summary}")
        if content:
            lines.append(f"    {content}")
    return "<incoming-messages>\n" + "\n".join(lines) + "\n</incoming-messages>"


def _approval_reminder(m: IncomingMessage) -> str | None:
    """plan_approval_response 的附加文案。"""
    if m.type != "plan_approval_response":
        return None
    payload = m.payload or {}
    if payload.get("approve"):
        return "Lead 已批准计划，权限模式已切到 default，可执行计划。"
    feedback = payload.get("feedback", "")
    return f"Lead 驳回了计划，反馈：{feedback}。请调整后重新提交。"


async def ingest_team_mailbox(agent: Any) -> None:
    """读邮箱未读消息并注入 pending_reminders（run 每轮迭代头部调用）。"""
    tc = teammate_context_from_ctx()
    if tc is None:
        return
    try:
        indices, msgs = await tc.read_unread()
    except Exception:
        return
    if not msgs:
        return
    reminders: list[str] = [build_incoming_messages_reminder(msgs)]
    switched_default = False
    for m in msgs:
        extra = _approval_reminder(m)
        if extra is not None:
            reminders.append(extra)
            if (m.payload or {}).get("approve") and agent.permission_mode is not Mode.DEFAULT:
                agent.permission_mode = Mode.DEFAULT
                switched_default = True
        if m.type == "shutdown_request":
            reminders.append(
                "收到 shutdown_request：你可以在本轮自主回复 shutdown_response(approve=True)"
                " 后停止，或 approve=False 拒绝并附 reason。"
            )
    if switched_default:
        reminders.append("已按 Lead 批准切换权限模式到 default。")
    try:
        await tc.mark_read(indices)
    except Exception:
        pass
    if agent.runtime is not None:
        agent.runtime.append_reminders(reminders)
