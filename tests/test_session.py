"""Session 子包测试：Writer、列表、加载恢复、过期清理。"""

from __future__ import annotations

import json
import os
from datetime import timedelta

from forgecode.conversation.history import (
    ROLE_ASSISTANT,
    ROLE_USER,
    Message,
    ToolCall,
    ToolResult,
)
from forgecode.session import Writer, clean_expired, list_sessions, load_session


def _make_message(role: str, content: str, **kwargs) -> Message:
    """构造测试用 Message。"""
    return Message(role=role, content=content, **kwargs)


# ── Writer 测试 ───────────────────────────────────


def test_writer_append_and_read(tmp_path):
    """写入 3 条消息 → 逐行读回验证 JSON 结构。"""
    session_dir = str(tmp_path / "test-session")
    w = Writer(session_dir)
    try:
        w.append(_make_message(ROLE_USER, "你好"), model="gpt-4", is_first=True)
        w.append(_make_message(ROLE_ASSISTANT, "你好！"), is_first=False)
        w.append(_make_message(ROLE_USER, "再聊"), is_first=False)
    finally:
        w.close()

    jsonl_path = os.path.join(session_dir, "conversation.jsonl")
    with open(jsonl_path, encoding="utf-8") as f:
        lines = [json.loads(line) for line in f if line.strip()]

    assert len(lines) == 3
    assert lines[0]["role"] == "user"
    assert lines[0]["content"] == "你好"
    assert lines[0]["model"] == "gpt-4"
    assert "ts" in lines[0]

    assert lines[1]["role"] == "assistant"
    assert lines[1]["content"] == "你好！"
    assert "model" not in lines[1]  # is_first=False


def test_writer_tool_calls_record(tmp_path):
    """工具调用和结果写入 JSONL。"""
    session_dir = str(tmp_path / "test-session")
    w = Writer(session_dir)
    try:
        call = ToolCall(id="tc_1", name="read_file", input='{"path":"f.txt"}')
        w.append(
            Message(role=ROLE_ASSISTANT, content="", tool_calls=[call]),
            model="gpt-4",
            is_first=True,
        )
        result = ToolResult(tool_call_id="tc_1", content="file content", is_error=False)
        w.append(
            Message(role="tool", content="", tool_results=[result]),
            is_first=False,
        )
    finally:
        w.close()

    jsonl_path = os.path.join(session_dir, "conversation.jsonl")
    with open(jsonl_path, encoding="utf-8") as f:
        lines = [json.loads(line) for line in f if line.strip()]

    assert len(lines) == 2
    assert lines[0]["tool_calls"][0]["name"] == "read_file"
    assert lines[1]["tool_results"][0]["content"] == "file content"


def test_writer_compact_marker(tmp_path):
    """写入消息 → compact 标记 → 新消息 → load_session 只返回 compact 后的。"""
    session_dir = str(tmp_path / "test-session")
    w = Writer(session_dir)
    try:
        w.append(_make_message(ROLE_USER, "旧消息"), model="gpt-4", is_first=True)
        w.append(_make_message(ROLE_ASSISTANT, "旧回复"), is_first=False)
        w.write_compact_marker()
        w.append(_make_message(ROLE_USER, "新消息"), is_first=False)
        w.append(_make_message(ROLE_ASSISTANT, "新回复"), is_first=False)
    finally:
        w.close()

    msgs = load_session(session_dir)
    # 只应包含 compact 后的新消息
    assert len(msgs) == 2
    assert msgs[0].content == "新消息"
    assert msgs[1].content == "新回复"


def test_open_existing_append(tmp_path):
    """open_existing 追加模式正常。"""
    session_dir = str(tmp_path / "test-session")
    w1 = Writer(session_dir)
    w1.append(_make_message(ROLE_USER, "msg1"), model="gpt-4", is_first=True)
    w1.close()

    w2 = Writer.open_existing(session_dir)
    w2.append(_make_message(ROLE_ASSISTANT, "reply1"), is_first=False)
    w2.close()

    jsonl_path = os.path.join(session_dir, "conversation.jsonl")
    with open(jsonl_path, encoding="utf-8") as f:
        lines = [json.loads(line) for line in f if line.strip()]
    assert len(lines) == 2


def test_writer_path_property(tmp_path):
    """Writer.path 返回 conversation.jsonl 的绝对路径。"""
    session_dir = str(tmp_path / "test-session")
    w = Writer(session_dir)
    assert w.path.endswith("conversation.jsonl")
    assert os.path.isabs(w.path)
    assert os.path.isfile(w.path)


# ── load_session 测试 ─────────────────────────────


def test_load_session_bad_line_skip(tmp_path):
    """插入坏行 → 被跳过，其余正常。"""
    session_dir = str(tmp_path / "test-session")
    w = Writer(session_dir)
    try:
        w.append(_make_message(ROLE_USER, "msg1"), model="gpt-4", is_first=True)
    finally:
        w.close()

    # 手动在 JSONL 中插入坏行
    jsonl_path = os.path.join(session_dir, "conversation.jsonl")
    with open(jsonl_path, "ab") as f:
        f.write(b"{this is bad json\n")
        w2 = Writer.open_existing(session_dir)
        w2.append(_make_message(ROLE_ASSISTANT, "msg2"), is_first=False)
        w2.close()

    msgs = load_session(session_dir)
    assert len(msgs) == 2
    assert msgs[0].content == "msg1"
    assert msgs[1].content == "msg2"


def test_load_session_orphaned_tool_calls(tmp_path):
    """末尾是带 tool_calls 的 assistant → 被截断。"""
    session_dir = str(tmp_path / "test-session")
    w = Writer(session_dir)
    try:
        w.append(_make_message(ROLE_USER, "读文件"), model="gpt-4", is_first=True)
        call = ToolCall(id="tc_1", name="read_file", input='{"path":"f.txt"}')
        w.append(
            Message(role=ROLE_ASSISTANT, content="我来读", tool_calls=[call]),
            is_first=False,
        )
        # 没有后续 tool 结果（模拟崩溃）
    finally:
        w.close()

    msgs = load_session(session_dir)
    # 只应保留 user 消息，assistant 带 tool_calls 被截断
    assert len(msgs) == 1
    assert msgs[0].role == ROLE_USER


def test_load_session_empty(tmp_path):
    """空目录 → 空列表。"""
    msgs = load_session(str(tmp_path / "nonexistent"))
    assert msgs == []


# ── list_sessions 测试 ────────────────────────────


def test_list_sessions_empty(tmp_path):
    """空目录 → 空列表。"""
    result = list_sessions(str(tmp_path / "nonexistent"))
    assert result == []


def test_list_sessions_new_format(tmp_path):
    """新格式 session ID → 列出。"""
    sessions_dir = tmp_path / "sessions"
    s1 = sessions_dir / "20260601-143022-a1b2"
    s1.mkdir(parents=True)
    (s1 / "conversation.jsonl").write_text(
        '{"role":"user","content":"测试消息","ts":1717200000,"model":"gpt-4"}\n',
        encoding="utf-8",
    )

    result = list_sessions(str(sessions_dir))
    assert len(result) == 1
    assert result[0].id == "20260601-143022-a1b2"
    assert result[0].title == "测试消息"
    assert result[0].model == "gpt-4"


def test_list_sessions_skips_old_format(tmp_path):
    """旧格式 session ID → 不在列表中。"""
    sessions_dir = tmp_path / "sessions"
    s_old = sessions_dir / "1717000000-abc12345"  # 旧格式 unix_ts-hex
    s_old.mkdir(parents=True)
    (s_old / "conversation.jsonl").write_text(
        '{"role":"user","content":"旧格式","ts":1717000000}\n', encoding="utf-8"
    )

    s_new = sessions_dir / "20260601-143022-dead"
    s_new.mkdir(parents=True)
    (s_new / "conversation.jsonl").write_text(
        '{"role":"user","content":"新格式","ts":1717200000,"model":"gpt-4"}\n',
        encoding="utf-8",
    )

    result = list_sessions(str(sessions_dir))
    assert len(result) == 1
    assert result[0].id == "20260601-143022-dead"


def test_list_sessions_no_jsonl(tmp_path):
    """有目录但无 conversation.jsonl → 跳过。"""
    sessions_dir = tmp_path / "sessions"
    s = sessions_dir / "20260601-143022-dead"
    s.mkdir(parents=True)
    # 不创建 JSONL

    result = list_sessions(str(sessions_dir))
    assert len(result) == 0


def test_list_sessions_order_by_modified(tmp_path):
    """按修改时间倒序排列。"""
    sessions_dir = tmp_path / "sessions"
    s1 = sessions_dir / "20260601-120000-a111"
    s1.mkdir(parents=True)
    (s1 / "conversation.jsonl").write_text(
        '{"role":"user","content":"older","ts":1,"model":"gpt-4"}\n', encoding="utf-8"
    )

    s2 = sessions_dir / "20260602-120000-b222"
    s2.mkdir(parents=True)
    (s2 / "conversation.jsonl").write_text(
        '{"role":"user","content":"newer","ts":2,"model":"gpt-4"}\n', encoding="utf-8"
    )

    # 手动设置 mtime 确保排序正确
    import os as _os
    _os.utime(str(s1 / "conversation.jsonl"), (1000000000, 1000000000))  # old
    _os.utime(str(s2 / "conversation.jsonl"), (2000000000, 2000000000))  # newer

    result = list_sessions(str(sessions_dir))
    assert len(result) == 2
    # newer 在前
    assert result[0].id == "20260602-120000-b222"


# ── clean_expired 测试 ────────────────────────────


def test_clean_expired_removes_old(tmp_path):
    """31 天前的目录被删除，1 天前的保留。"""
    sessions_dir = tmp_path / "sessions"

    # 创建 session 目录（模拟 31 天前和 1 天前）
    # clean_expired 用 datetime.now(timezone.utc) 比较，所以用绝对时间
    old_id = "20200101-000000-dead"  # 很久以前
    recent_id = "20990101-000000-beef"  # 未来

    s_old = sessions_dir / old_id
    s_old.mkdir(parents=True)
    (s_old / "conversation.jsonl").write_text("{}", encoding="utf-8")

    s_recent = sessions_dir / recent_id
    s_recent.mkdir(parents=True)
    (s_recent / "conversation.jsonl").write_text("{}", encoding="utf-8")

    clean_expired(str(sessions_dir), timedelta(days=30))

    assert not s_old.exists()
    assert s_recent.exists()


def test_clean_expired_skips_old_format(tmp_path):
    """旧格式 session ID 不被清理。"""
    sessions_dir = tmp_path / "sessions"
    s_old = sessions_dir / "1717000000-abc12345"
    s_old.mkdir(parents=True)
    (s_old / "conversation.jsonl").write_text("{}", encoding="utf-8")

    clean_expired(str(sessions_dir), timedelta(days=0))  # 任何超期

    # 旧格式仍然存在
    assert s_old.exists()
