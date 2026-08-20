"""ForgeApp TUI 状态展示单测：状态栏/提示文案（A2）+ 流式渲染（A3）+ resize（A4）。"""

from __future__ import annotations

import os
from types import SimpleNamespace

from forgecode.agent.runtime import new_runtime
from forgecode.config.schema import AppConfig, ProviderConfig
from forgecode.conversation.history import Conversation
from forgecode.permission.engine import new_engine
from forgecode.tool import Registry
from forgecode.tui.app import (
    _MD_RENDER_CHUNK,
    _MD_RENDER_INTERVAL,
    _TOOL_LOG_LIMIT,
    ForgeApp,
    _prepare_markdown_render,
)
from tests.test_agent_hook import FakeProvider


def _make_app() -> ForgeApp:
    config = AppConfig(
        providers=[
            ProviderConfig(
                name="fake",
                protocol="fake",
                model="m",
                base_url="",
                api_key="",
            )
        ],
        active_provider_name="fake",
    )
    engine, _ = new_engine(os.getcwd())
    return ForgeApp(
        config=config,
        provider=FakeProvider(),
        conversation=Conversation(),
        registry=Registry(),
        engine=engine,
        runtime=new_runtime("."),
    )


def test_status_text_shows_elapsed_when_idle() -> None:
    """空闲态状态栏显示上次耗时，不包含已删除的 Imagining 死代码分支。"""
    app = _make_app()
    app._agent_running = False
    app._response_elapsed = 3.5
    text = app._render_status_text()
    assert "3.5s" in text
    assert "Imagining" not in text


def test_status_text_placeholder_before_first_turn() -> None:
    """未跑过回合时耗时位显示省略号。"""
    app = _make_app()
    app._response_elapsed = 0
    text = app._render_status_text()
    assert "..." in text
    assert "Imagining" not in text


# ── A3 流式 Markdown 渲染 ────────────────────────


def test_prepare_markdown_closed_fence_unchanged() -> None:
    text = "a\n```py\nprint(1)\n```\nb"
    assert _prepare_markdown_render(text) == text


def test_prepare_markdown_open_fence_truncates() -> None:
    text = "a\n```py\nprint(1)"  # 未闭合
    assert _prepare_markdown_render(text) == "a\n"


def test_prepare_markdown_open_fence_after_closed_block() -> None:
    text = "```\ncode1\n```\n然后 ``` 开了没关"
    # 3 个 ``` → 奇数 → 截断到最后一个 ``` 之前（保留已闭合块）
    assert _prepare_markdown_render(text) == "```\ncode1\n```\n然后 "


def test_prepare_markdown_empty() -> None:
    assert _prepare_markdown_render("") == ""
    assert _prepare_markdown_render("```") == ""


def test_md_render_due_first_call(monkeypatch) -> None:
    """首次调用立即触发渲染（上次时间戳为 0，必然超时）。"""
    app = _make_app()
    assert app._md_render_due(10) is True


def test_md_render_due_small_increment_within_interval(monkeypatch) -> None:
    app = _make_app()
    clock = [1000.0]

    def _now() -> float:
        return clock[0]

    monkeypatch.setattr("forgecode.tui.app.time.monotonic", _now)
    assert app._md_render_due(10) is True  # 首帧
    assert app._md_render_due(20) is False  # 增量 < chunk 且时间未到
    clock[0] += _MD_RENDER_INTERVAL + 0.01  # 超过间隔
    assert app._md_render_due(30) is True


def test_md_render_due_big_increment_immediate(monkeypatch) -> None:
    app = _make_app()
    clock = [1000.0]

    def _now() -> float:
        return clock[0]

    monkeypatch.setattr("forgecode.tui.app.time.monotonic", _now)
    assert app._md_render_due(10) is True
    assert app._md_render_due(10 + _MD_RENDER_CHUNK + 1) is True


# ── A4 终端 resize 适配 ────────────────────────


def test_border_text_uses_current_width() -> None:
    app = _make_app()
    app._width = 80
    assert app._border_text() == "─" * 80
    app._width = 120
    assert app._border_text() == "─" * 120
    app._width = 0
    assert app._border_text() == "─" * 1  # 宽度至少 1


def test_on_resize_updates_width_and_invalidates(monkeypatch) -> None:
    app = _make_app()
    app._width = 80
    monkeypatch.setattr(
        "forgecode.tui.app.shutil.get_terminal_size",
        lambda: SimpleNamespace(columns=100),
    )
    fake_app = SimpleNamespace(invalidated=0)
    fake_app.invalidate = lambda: setattr(fake_app, "invalidated", fake_app.invalidated + 1)  # type: ignore[union-attr]

    app._on_resize(fake_app)  # type: ignore[arg-type]
    assert app._width == 100
    assert fake_app.invalidated == 1


# ── A5 工具调用日志（折叠 + /tool 展开）───────


def _quiet_console(app: ForgeApp) -> ForgeApp:
    """测试环境无控制台：Rich 回退 GBK 编码会因特殊字符崩溃，注入 StringIO。"""
    import io

    from rich.console import Console

    app.console = Console(file=io.StringIO(), force_terminal=False, width=100)
    return app


def test_tool_log_records_and_lists(monkeypatch) -> None:
    from forgecode.agent import Phase, ToolEvent

    app = _quiet_console(_make_app())
    clock = [1000.0]
    monkeypatch.setattr("forgecode.tui.app.time.monotonic", lambda: clock[0])

    app._render_tool_start(ToolEvent(name="read_file", args="{}", phase=Phase.START))
    clock[0] += 1.5
    app._render_tool_end(
        ToolEvent(name="read_file", phase=Phase.END, result="line1\nline2\nline3", is_error=False)
    )

    entries = app.tool_log()
    assert len(entries) == 1
    e = entries[0]
    assert e.index == 1
    assert e.name == "read_file"
    assert e.result == "line1\nline2\nline3"
    assert e.is_error is False
    assert e.elapsed == 1.5  # start 到 end 的墙钟差

    detail = app.tool_log_detail(1)
    assert detail is not None and detail.args == "{}"
    assert app.tool_log_detail(99) is None

    app.tool_log_clear()
    assert app.tool_log() == []


def test_tool_log_keeps_limit() -> None:
    from forgecode.agent import Phase, ToolEvent

    app = _quiet_console(_make_app())
    for i in range(_TOOL_LOG_LIMIT + 5):
        app._render_tool_start(ToolEvent(name="t", args="{}", phase=Phase.START))
        app._render_tool_end(ToolEvent(name="t", phase=Phase.END, result=f"r{i}"))
    assert len(app._tool_log) == _TOOL_LOG_LIMIT
    # 丢弃最旧：最早的 index 已被挤出，最新 index 单调递增
    assert app.tool_log_detail(1) is None
    assert app.tool_log_detail(_TOOL_LOG_LIMIT + 5) is not None
