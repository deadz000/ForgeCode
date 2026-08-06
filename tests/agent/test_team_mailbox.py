"""agent.team_mailbox 单测：队员 Loop 头部邮箱注入（AC16）。"""

from __future__ import annotations

import pytest

from forgecode.agent.runtime import SessionRuntime, new_runtime
from forgecode.agent.team_hook import (
    IncomingMessage,
    TeammateContext,
    with_teammate_context,
)
from forgecode.agent.team_mailbox import (
    build_incoming_messages_reminder,
    ingest_team_mailbox,
)
from forgecode.permission import Mode


class _FakeAgent:
    """最小 Agent 桩：仅持 runtime 与 permission_mode。"""

    def __init__(self, runtime: SessionRuntime) -> None:
        self.runtime = runtime
        self.permission_mode = Mode.DEFAULT


class _Mailbox:
    def __init__(self) -> None:
        self._msgs: list[IncomingMessage] = []
        self._marked: list[list[int]] = []
        self._read_calls = 0

    def seed(self, msg: IncomingMessage) -> None:
        self._msgs.append(msg)

    async def _read_unread(self) -> tuple[list[int], list[IncomingMessage]]:
        self._read_calls += 1
        return list(range(len(self._msgs))), list(self._msgs)

    async def _mark_read(self, indices: list[int]) -> None:
        self._marked.append(indices)


def _ctx(mb: _Mailbox) -> TeammateContext:
    return TeammateContext(
        team_name="demo",
        member_name="alice",
        agent_id="agent-1",
        backend_type="in-process",
        read_unread=mb._read_unread,
        mark_read=mb._mark_read,
    )


def test_build_reminder_format() -> None:
    r = build_incoming_messages_reminder(
        [IncomingMessage(from_="lead", type="text", summary="do work", content="写一个文件")]
    )
    assert "<incoming-messages>" in r
    assert "收到 1 条新消息" in r
    assert "do work" in r
    assert "写一个文件" in r


def test_content_truncated() -> None:
    long = "x" * 500
    r = build_incoming_messages_reminder(
        [IncomingMessage(from_="lead", type="text", summary="s", content=long)]
    )
    assert "x" * 201 not in r
    assert "…" in r


async def test_ingest_injects_reminder_and_marks_read() -> None:
    mb = _Mailbox()
    mb.seed(IncomingMessage(from_="lead", type="text", summary="hi", content="hello"))
    agent = _FakeAgent(new_runtime("."))
    with with_teammate_context(_ctx(mb)):
        await ingest_team_mailbox(agent)
    reminders = agent.runtime.pending_reminders
    assert len(reminders) == 1
    assert "<incoming-messages>" in reminders[0]
    assert mb._marked == [[0]]


async def test_ingest_noop_without_context() -> None:
    agent = _FakeAgent(new_runtime("."))
    await ingest_team_mailbox(agent)
    assert agent.runtime.pending_reminders == []


async def test_plan_approval_switches_mode() -> None:
    mb = _Mailbox()
    mb.seed(
        IncomingMessage(
            from_="lead",
            type="plan_approval_response",
            summary="approved",
            payload={"approve": True},
        )
    )
    agent = _FakeAgent(new_runtime("."))
    agent.permission_mode = Mode.PLAN
    with with_teammate_context(_ctx(mb)):
        await ingest_team_mailbox(agent)
    assert agent.permission_mode is Mode.DEFAULT
    assert any("已批准计划" in r for r in agent.runtime.pending_reminders)


async def test_plan_reject_keeps_mode() -> None:
    mb = _Mailbox()
    mb.seed(
        IncomingMessage(
            from_="lead",
            type="plan_approval_response",
            summary="rejected",
            payload={"approve": False, "feedback": "改一下"},
        )
    )
    agent = _FakeAgent(new_runtime("."))
    agent.permission_mode = Mode.PLAN
    with with_teammate_context(_ctx(mb)):
        await ingest_team_mailbox(agent)
    assert agent.permission_mode is Mode.PLAN
    assert any("驳回了计划" in r for r in agent.runtime.pending_reminders)
