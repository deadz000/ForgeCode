"""Layer1 单元测试：落盘 / 预览体 / 决策冻结。"""

from __future__ import annotations

from pathlib import Path

from forgecode.compact.layer1 import (
    build_preview,
    offload_and_snip,
    spill_single,
)
from forgecode.compact.state import ContentReplacementState, SessionContext
from forgecode.conversation.history import Message, ToolResult


def _make_session(tmp_path) -> SessionContext:
    session_dir = str(tmp_path / "sessions" / "test")
    d = str(tmp_path / "sessions" / "test" / "tool-results")
    Path(d).mkdir(parents=True, exist_ok=True)
    return SessionContext(session_id="test", session_dir=session_dir, spill_dir=d)


def _make_tool_msg(results: list[ToolResult]) -> Message:
    return Message(role="tool", tool_results=results)


def test_spill_single_idempotent(tmp_path):
    """连续两次 spill_single，文件只写一次。"""
    session = _make_session(tmp_path)
    content = "hello world"
    tool_id = "test-id-1"

    spill_single(session, tool_id, content)
    p = Path(session.spill_dir) / tool_id
    mtime1 = p.stat().st_mtime_ns

    # 第二次不重写
    spill_single(session, tool_id, content)
    mtime2 = p.stat().st_mtime_ns
    assert mtime1 == mtime2


def test_build_preview_contains_four_parts():
    """预览体包含原始字节数、路径、头部标记、重读提示。"""
    preview = build_preview(60000, "line1\nline2\n", "/tmp/spill/test-id")
    assert "original size: 60000 bytes" in preview
    assert "/tmp/spill/test-id" in preview
    assert "head preview" in preview
    assert "不要凭头部预览猜测" in preview


def test_build_preview_stable():
    """相同入参两次调用返回逐字节相等。"""
    p1 = build_preview(100, "abc", "/tmp/x")
    p2 = build_preview(100, "abc", "/tmp/x")
    assert p1 == p2


def test_offload_single_result(tmp_path):
    """单条超阈值工具结果被替换。"""
    session = _make_session(tmp_path)
    state = ContentReplacementState()
    big_content = "x" * 60000  # 60000 bytes > 50000
    tool_id = "big-result"
    msg = _make_tool_msg([ToolResult(tool_call_id=tool_id, content=big_content)])

    out, _ = offload_and_snip([msg], state, session)

    # 结果被替换为预览体
    result_content = out[0].tool_results[0].content
    assert "original size: 60000 bytes" in result_content
    assert "head preview" in result_content

    # 落盘文件存在
    spill_file = Path(session.spill_dir) / tool_id
    assert spill_file.exists()
    assert spill_file.read_bytes() == big_content.encode("utf-8")


def test_offload_small_result_kept(tmp_path):
    """小工具结果不被替换。"""
    session = _make_session(tmp_path)
    state = ContentReplacementState()
    small_content = "small"
    msg = _make_tool_msg([ToolResult(tool_call_id="small", content=small_content)])

    out, _ = offload_and_snip([msg], state, session)

    assert out[0].tool_results[0].content == small_content


def test_offload_aggregate_f2(tmp_path):
    """F2 聚合落盘：单条均低于 F1 阈值但集体超 200KB，按字节倒序落盘至聚合 ≤ 200KB。"""
    session = _make_session(tmp_path)
    state = ContentReplacementState()

    # 15 条各 15000 字节（均 < 20000 F1 阈值），合计 225000 > 200000
    results = [
        ToolResult(tool_call_id=f"r{i}", content=chr(97 + i % 26) * 15000)
        for i in range(15)
    ]
    msg = _make_tool_msg(results)

    out, replaced = offload_and_snip([msg], state, session)

    # 225000 - 200000 = 25000，需要落盘 ceil(25000/15000)=2 条最大的
    assert replaced == 2

    # 聚合字节回落至 ≤ 200000
    remaining_bytes = sum(
        len(tr.content.encode("utf-8")) for tr in out[0].tool_results
    )
    assert remaining_bytes <= 200000

    # 替换按字节倒序：最大的两条被换
    replaced_ids = [
        tr.tool_call_id
        for tr in out[0].tool_results
        if "original size:" in tr.content
    ]
    assert len(replaced_ids) == 2

    # 未被替换的保持原文
    kept = [
        tr
        for tr in out[0].tool_results
        if "original size:" not in tr.content
    ]
    assert len(kept) == 13
    for tr in kept:
        assert len(tr.content.encode("utf-8")) == 15000


def test_offload_decision_freeze(tmp_path):
    """同一 id 跑两次 offload_and_snip，结果一致。"""
    session = _make_session(tmp_path)
    state = ContentReplacementState()
    content = "x" * 60000
    msg = _make_tool_msg([ToolResult(tool_call_id="frozen", content=content)])

    out1, _ = offload_and_snip([msg], state, session)
    out2, _ = offload_and_snip([msg], state, session)

    assert out1[0].tool_results[0].content == out2[0].tool_results[0].content


def test_offload_spill_failure_retryable(tmp_path, monkeypatch):
    """落盘失败时工具结果保持原文（通过 monkeypatch spill_single 模拟）。"""
    from forgecode.compact import layer1 as l1_module

    session = _make_session(tmp_path)
    state = ContentReplacementState()
    content = "x" * 60000

    # 让 spill_single 抛 OSError
    def _fail_spill(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(l1_module, "spill_single", _fail_spill)

    msg = _make_tool_msg([ToolResult(tool_call_id="spill-fail", content=content)])
    out, _ = offload_and_snip([msg], state, session)

    # 保持原文（skip 路径不写账本）
    assert out[0].tool_results[0].content == content
    # 账本中该 id 未被标记为 seen
    assert not state.is_seen("spill-fail")
