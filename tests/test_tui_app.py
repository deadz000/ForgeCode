"""ForgeApp TUI 状态展示单测：状态栏/提示文案（A2 计时反馈改造）+ 流式渲染（A3）。"""

from __future__ import annotations

import os

from forgecode.agent.runtime import new_runtime
from forgecode.config.schema import AppConfig, ProviderConfig
from forgecode.conversation.history import Conversation
from forgecode.permission.engine import new_engine
from forgecode.tool import Registry
from forgecode.tui.app import (
    _MD_RENDER_CHUNK,
    _MD_RENDER_INTERVAL,
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
