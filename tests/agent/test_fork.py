"""agent.fork 单测：消息克隆与上下文识别。"""

from __future__ import annotations

from forgecode.agent.fork import (
    FORK_BOILERPLATE,
    FORK_BOILERPLATE_TAG,
    build_forked_messages,
    is_fork_context,
)
from forgecode.conversation.history import Conversation, Message, ToolCall, ToolResult


def test_empty_parent() -> None:
    msgs = build_forked_messages([], "任务")
    assert len(msgs) == 1
    assert msgs[-1].role == "user"
    assert msgs[-1].content.startswith(FORK_BOILERPLATE_TAG)
    assert msgs[-1].content.endswith("任务")


def test_complete_pair_unchanged_plus_user() -> None:
    parent = [
        Message(role="user", content="hi"),
        Message(
            role="assistant",
            content="",
            tool_calls=[ToolCall(id="c1", name="read_file", input='{"path":"a"}')],
        ),
        Message(
            role="tool",
            tool_results=[ToolResult(tool_call_id="c1", content="ok")],
        ),
        Message(role="assistant", content="done"),
    ]
    msgs = build_forked_messages(parent, "任务")
    assert len(msgs) == len(parent) + 1
    assert msgs[-1].role == "user"
    # 无新增 placeholder
    tool_msgs = [m for m in msgs if m.role == "tool"]
    assert len(tool_msgs) == 1
    assert len(tool_msgs[0].tool_results) == 1


def test_dangling_tool_use_gets_placeholder() -> None:
    parent = [
        Message(
            role="assistant",
            content="",
            tool_calls=[
                ToolCall(id="c1", name="read_file", input="{}"),
                ToolCall(id="c2", name="grep", input="{}"),
            ],
        )
    ]
    msgs = build_forked_messages(parent, "任务")
    tool_msgs = [m for m in msgs if m.role == "tool"]
    assert len(tool_msgs) == 1
    placeholders = tool_msgs[0].tool_results
    assert {r.tool_call_id for r in placeholders} == {"c1", "c2"}
    assert all(r.is_error for r in placeholders)


def test_is_fork_context_true() -> None:
    conv = Conversation()
    conv.add_user(FORK_BOILERPLATE + "task")
    assert is_fork_context(conv.messages) is True


def test_is_fork_context_false() -> None:
    conv = Conversation()
    conv.add_user("普通消息")
    assert is_fork_context(conv.messages) is False


def test_from_messages_loads() -> None:
    msgs = build_forked_messages([], "任务")
    conv = Conversation.from_messages(msgs)
    assert conv.length() == 1
