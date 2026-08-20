"""ForgeApp TUI 状态展示单测：状态栏/提示文案（A2 计时反馈改造）。"""

from __future__ import annotations

import os

from forgecode.agent.runtime import new_runtime
from forgecode.config.schema import AppConfig, ProviderConfig
from forgecode.conversation.history import Conversation
from forgecode.permission.engine import new_engine
from forgecode.tool import Registry
from forgecode.tui.app import ForgeApp
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
