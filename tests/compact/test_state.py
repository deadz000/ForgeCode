"""状态对象单元测试：SessionContext / ContentReplacementState / CircuitBreaker / RecoveryState。"""

from __future__ import annotations

from forgecode.compact.const import MAX_CONSECUTIVE_AUTO_COMPACT_FAILURES
from forgecode.compact.state import (
    CompactCircuitBreaker,
    ContentReplacementState,
    RecoveryState,
    new_session_context,
)


def test_new_session_context_creates_dir(tmp_workspace):
    """会话上下文创建后落盘目录存在。"""
    ctx = new_session_context(tmp_workspace)
    assert ctx.session_id
    assert "-" in ctx.session_id  # <unix_ts>-<hex>
    assert "tool-results" in ctx.spill_dir
    import os

    assert os.path.isdir(ctx.spill_dir)


def test_new_session_context_id_unique(tmp_workspace):
    """连续两次创建得到不同的 session_id。"""
    ctx1 = new_session_context(tmp_workspace)
    ctx2 = new_session_context(tmp_workspace)
    assert ctx1.session_id != ctx2.session_id


def test_decide_once_freeze_kept():
    """kept 后再次 decide_once 返回原 content，账本不翻转。"""
    state = ContentReplacementState()
    result1 = state.decide_once("id1", "original", lambda: ("kept", ""))
    assert result1 == "original"

    # 第二次不调回调，直接返回存量结果
    called = False

    def _cb():
        nonlocal called
        called = True
        return ("replaced", "xxx")

    result2 = state.decide_once("id1", "original", _cb)
    assert result2 == "original"  # 保持 kept
    assert not called


def test_decide_once_freeze_replaced():
    """replaced 后再次 decide_once 返回同一份 preview。"""
    state = ContentReplacementState()
    preview = "preview_content"
    result1 = state.decide_once("id1", "original", lambda: ("replaced", preview))
    assert result1 == preview

    called = False

    def _cb():
        nonlocal called
        called = True
        return ("kept", "")

    result2 = state.decide_once("id1", "original", _cb)
    assert result2 == preview  # 复用 preview
    assert not called


def test_decide_once_skip_does_not_mark():
    """skip 后不记入账本，下次可重新评估。"""
    state = ContentReplacementState()
    result1 = state.decide_once("id1", "original", lambda: ("skip", ""))
    assert result1 == "original"

    called = False

    def _cb():
        nonlocal called
        called = True
        return ("replaced", "new_preview")

    result2 = state.decide_once("id1", "original", _cb)
    assert result2 == "new_preview"
    assert called


def test_auto_tracking_basic():
    """熔断器计数与跳闸逻辑。"""
    at = CompactCircuitBreaker()
    assert not at.tripped()

    for _ in range(MAX_CONSECUTIVE_AUTO_COMPACT_FAILURES - 1):
        at.record_failure()
    assert not at.tripped()

    at.record_failure()
    assert at.tripped()

    at.record_success()
    assert not at.tripped()


def test_recovery_state_snapshot_order():
    """snapshot 按时间戳倒序。"""
    import time

    rs = RecoveryState()
    rs.record_file("/tmp/a.txt", "content a")
    time.sleep(0.01)  # 微小延时确保时间戳不同
    rs.record_file("/tmp/b.txt", "content b")
    time.sleep(0.01)
    rs.record_file("/tmp/c.txt", "content c")

    snap = rs.snapshot()
    assert len(snap) == 3
    assert snap[0].path.endswith("c.txt")
    assert snap[1].path.endswith("b.txt")
    assert snap[2].path.endswith("a.txt")
