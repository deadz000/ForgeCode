"""摘要 Prompt 与解析单元测试。"""

from __future__ import annotations

from forgecode.compact.summary_prompt import (
    build_summary_prompt,
    extract_summary,
    serialize_conversation,
)
from forgecode.conversation.history import Message


def test_build_summary_prompt_shape():
    """返回 1 条 user 消息，包含 9 部分标题。"""
    msgs = [Message(role="user", content="hello")]
    result = build_summary_prompt(msgs)
    assert len(result) == 1
    assert result[0].role == "user"

    content = result[0].content
    assert "<analysis>" in content
    assert "<summary>" in content
    assert "不" in content and "调用" in content and "工具" in content
    # 9 个小节
    for section in [
        "主要请求和意图",
        "关键技术概念",
        "文件和代码段",
        "错误和修复",
        "问题解决过程",
        "所有用户消息原文",
        "待办任务",
        "当前工作",
        "可能的下一步",
    ]:
        assert section in content


def test_serialize_conversation_deterministic():
    """相同 msgs 两次序列化返回逐字节相等。"""
    msgs = [
        Message(role="user", content="hello"),
        Message(role="assistant", content="hi there"),
    ]
    s1 = serialize_conversation(msgs)
    s2 = serialize_conversation(msgs)
    assert s1 == s2


def test_extract_summary_standard():
    """标准格式提取 <summary> 内容。"""
    raw = "blah<analysis>draft</analysis>some<summary>the summary</summary>end"
    assert extract_summary(raw) == "the summary"


def test_extract_summary_missing():
    """缺失 <summary> 标签时返回原文。"""
    raw = "no summary tags here"
    assert extract_summary(raw) == raw


def test_extract_summary_nested():
    """多个 <summary> 标签取最后一个。"""
    raw = "<summary>old</summary>middle<summary>new</summary>"
    assert extract_summary(raw) == "new"
