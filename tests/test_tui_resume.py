"""tui.resume 单测：会话列表项格式化（A9 纯文本版本）。"""

from __future__ import annotations

from datetime import datetime, timedelta

from forgecode.session.list import SessionInfo
from forgecode.tui.resume import format_session_item, plain_session_item


def _info(**overrides) -> SessionInfo:
    base = dict(
        id="s1",
        dir="/tmp/sessions/s1",
        title="修复登录 bug",
        modified_at=datetime.now() - timedelta(hours=2),
        model="claude-3.5",
        size=2048,
    )
    base.update(overrides)
    return SessionInfo(**base)


def test_format_session_item_keeps_rich_markup():
    item = format_session_item(_info(), 1)
    assert item.startswith("  1. 修复登录 bug")
    assert "[dim]" in item  # rich 标记保留


def test_plain_session_item_no_rich_markup():
    item = plain_session_item(_info())
    assert "[dim]" not in item
    assert "修复登录 bug" in item
    assert "2 hours ago" in item
    assert "claude-3.5" in item
    assert "2.0KB" in item


def test_plain_session_item_empty_title():
    item = plain_session_item(_info(title=""))
    assert "(空)" in item


def test_plain_session_item_size_formats():
    item = plain_session_item(_info(size=3 * 1024 * 1024))
    assert "3.0MB" in item
