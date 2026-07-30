"""Token 估算单元测试。"""

from __future__ import annotations

import math

from forgecode.compact.token import estimate_tokens, message_chars, usage_anchor
from forgecode.conversation.history import Message
from forgecode.providers import Usage


def test_usage_anchor_sum():
    """usage_anchor 返回四个字段之和。"""
    u = Usage(input_tokens=100, output_tokens=50, cache_write=10, cache_read=20)
    assert usage_anchor(u) == 180


def test_estimate_tokens_zero():
    """anchor=0 且空消息返回 0。"""
    assert estimate_tokens(0, [], 0) == 0


def test_estimate_tokens_anchor():
    """anchor 非零时返回 anchor + 增量估算。"""
    m = Message(role="user", content="hello world")  # 11 chars
    result = estimate_tokens(1000, [m], 0)
    expected = 1000 + math.ceil(11 / 3.5)
    assert result == expected


def test_estimate_tokens_anchor_msg_len():
    """anchor_msg_len 跳过的消息不计入增量。"""
    m1 = Message(role="user", content="first message")
    m2 = Message(role="assistant", content="second message")
    # anchor=500, anchor_msg_len=1 → 只算 m2
    result = estimate_tokens(500, [m1, m2], 1)
    expected = 500 + math.ceil(len(b"second message") / 3.5)
    assert result == expected


def test_message_chars():
    """message_chars 累加 content + tool_calls + tool_results。"""
    from forgecode.conversation.history import ToolCall, ToolResult

    m = Message(
        role="assistant",
        content="text",
        tool_calls=[ToolCall(id="1", name="echo", input='{"msg":"hi"}')],
        tool_results=[ToolResult(tool_call_id="1", content="result")],
    )
    chars = message_chars([m])
    # content "text" = 4 bytes + input '{"msg":"hi"}' = 12 bytes + result "result" = 6 bytes = 22
    assert chars == 22
