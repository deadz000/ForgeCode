"""ForgeApp hook 集成测试：UserPromptSubmit 拦截、SessionStart/End 分发。"""

from __future__ import annotations

import os

import pytest

from forgecode.agent.runtime import new_runtime
from forgecode.config.schema import AppConfig, ProviderConfig
from forgecode.conversation.history import Conversation
from forgecode.hook.engine import Engine as HookEngine
from forgecode.hook.event import Event as HookEvent
from forgecode.hook.rule import Action, ActionType, PromptAction, Rule, ShellAction
from forgecode.permission.engine import new_engine
from forgecode.tool import Registry
from forgecode.tui.app import ForgeApp
from tests.test_agent_hook import FakeProvider


def _make_app(hook_engine=None) -> ForgeApp:
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
    app = ForgeApp(
        config=config,
        provider=FakeProvider(),
        conversation=Conversation(),
        registry=Registry(),
        engine=engine,
        runtime=new_runtime("."),
        hook_engine=hook_engine,
    )
    return app


def _block_rule() -> Rule:
    return Rule(
        name="warn-delete",
        event=HookEvent.USER_PROMPT_SUBMIT,
        action=Action(
            type=ActionType.SHELL,
            shell=ShellAction(
                command="python -c \"import sys; print('denied by hook', file=sys.stderr); sys.exit(2)\""
            ),
        ),
    )


@pytest.mark.asyncio
async def test_submit_user_prompt_submit_blocked():
    """UserPromptSubmit 拦截 → 消息不写入对话历史。"""
    hk = HookEngine([_block_rule()], ["x.yaml"])
    app = _make_app(hk)
    before = app.conversation.length()

    await app._submit("请帮我 delete 那个文件")

    assert app.conversation.length() == before  # 消息未被消费


@pytest.mark.asyncio
async def test_submit_user_prompt_submit_allow():
    """UserPromptSubmit 放行 → 消息写入对话历史。"""
    hk = HookEngine(
        [
            Rule(
                name="pass",
                event=HookEvent.USER_PROMPT_SUBMIT,
                action=Action(type=ActionType.SHELL, shell=ShellAction(command='python -c "pass"')),
            )
        ],
        ["x.yaml"],
    )
    app = _make_app(hk)

    await app._submit("hello")

    # 消息写入对话历史（放行路径）
    assert app.conversation.messages
    first = app.conversation.messages[0]
    assert first.role == "user"
    assert first.content == "hello"


@pytest.mark.asyncio
async def test_dispatch_session_start_injects_prompt():
    """SessionStart 注入的 prompt 进入 runtime 的 reminder 队列。"""
    hk = HookEngine(
        [
            Rule(
                name="zh",
                event=HookEvent.SESSION_START,
                action=Action(type=ActionType.PROMPT, prompt=PromptAction(text="用 zh-CN 回复")),
            )
        ],
        ["x.yaml"],
    )
    app = _make_app(hk)
    await app._dispatch_session_start()
    assert app.runtime.take_reminders() == ["用 zh-CN 回复"]


@pytest.mark.asyncio
async def test_dispatch_session_end_no_crash_without_engine():
    """无 hook 引擎时 SessionEnd 分发不报错。"""
    app = _make_app(hook_engine=None)
    await app._dispatch_session_end()
    await app._dispatch_session_start()
