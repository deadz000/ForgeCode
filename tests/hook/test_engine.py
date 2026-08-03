"""hook.Engine 测试：各事件 dispatch、拦截、reminder、once 覆盖。"""

from __future__ import annotations

import asyncio

import pytest

from forgecode.hook.engine import Engine
from forgecode.hook.event import Event
from forgecode.hook.rule import (
    Action,
    ActionType,
    PromptAction,
    Rule,
    ShellAction,
)

PAYLOAD = {"event": "Stop", "session_id": "s1", "cwd": "/tmp", "mode": "default"}


def _prompt_rule(name: str, event: Event, text: str, **kw) -> Rule:
    return Rule(
        name=name,
        event=event,
        action=Action(type=ActionType.PROMPT, prompt=PromptAction(text=text)),
        **kw,
    )


def _shell_rule(name: str, event: Event, command: str, **kw) -> Rule:
    return Rule(
        name=name,
        event=event,
        action=Action(type=ActionType.SHELL, shell=ShellAction(command=command)),
        **kw,
    )


@pytest.mark.asyncio
async def test_dispatch_order():
    """多 rule 同事件按声明序执行，prompt 依序累加。"""
    rules = [
        _prompt_rule("a", Event.STOP, "A"),
        _prompt_rule("b", Event.STOP, "B"),
        _prompt_rule("c", Event.SESSION_START, "ignored"),
    ]
    eng = Engine(rules, ["x.yaml"])
    res = await eng.dispatch(Event.STOP, PAYLOAD)
    assert res.injected_prompts == ["A", "B"]


@pytest.mark.asyncio
async def test_dispatch_blocking_stops_after_block():
    """拦截类事件下首个 blocked 的 rule 中断后续。"""
    rules = [
        _shell_rule(
            "blocker",
            Event.PRE_TOOL_USE,
            "python -c \"import sys; print('no', file=sys.stderr); sys.exit(2)\"",
        ),
        _prompt_rule("after", Event.PRE_TOOL_USE, "should-not-run"),
    ]
    eng = Engine(rules, ["x.yaml"])
    payload = {"event": "PreToolUse", "tool_name": "write_file", "tool_input": {}}
    res = await eng.dispatch(Event.PRE_TOOL_USE, payload)
    assert res.blocked
    assert res.blocking_hook_name == "blocker"
    assert "no" in res.reason
    assert res.injected_prompts == []  # 后续 prompt 未执行


@pytest.mark.asyncio
async def test_dispatch_nonblocking_event_ignores_block():
    """非拦截类事件下 exit 2 不传递 blocked。"""
    rules = [_shell_rule("s", Event.STOP, "python -c \"import sys; sys.exit(2)\"")]
    eng = Engine(rules, ["x.yaml"])
    res = await eng.dispatch(Event.STOP, PAYLOAD)
    assert not res.blocked


@pytest.mark.asyncio
async def test_dispatch_prompt_accumulated():
    """prompt rule 的 prompt 累加到 injected_prompts。"""
    rules = [_prompt_rule("p", Event.SESSION_START, "用 zh-CN 回复")]
    eng = Engine(rules, ["x.yaml"])
    res = await eng.dispatch(Event.SESSION_START, PAYLOAD)
    assert res.injected_prompts == ["用 zh-CN 回复"]


@pytest.mark.asyncio
async def test_only_once():
    """only_once 首次执行后第二次 dispatch 跳过。"""
    rules = [
        _shell_rule("once", Event.STOP, "python -c \"pass\"", only_once=True),
        _prompt_rule("always", Event.STOP, "ALWAYS"),
    ]
    eng = Engine(rules, ["x.yaml"])
    res1 = await eng.dispatch(Event.STOP, PAYLOAD)
    assert res1.injected_prompts == ["ALWAYS"]
    res2 = await eng.dispatch(Event.STOP, PAYLOAD)
    # only_once 的 shell 不再执行（无副作用可观察），prompt 仍注入
    assert res2.injected_prompts == ["ALWAYS"]


@pytest.mark.asyncio
async def test_only_once_prompt_skipped_second_time():
    """only_once + prompt：第二次不再注入该 prompt。"""
    rules = [_prompt_rule("once", Event.STOP, "ONCE", only_once=True)]
    eng = Engine(rules, ["x.yaml"])
    res1 = await eng.dispatch(Event.STOP, PAYLOAD)
    assert res1.injected_prompts == ["ONCE"]
    res2 = await eng.dispatch(Event.STOP, PAYLOAD)
    assert res2.injected_prompts == []


@pytest.mark.asyncio
async def test_reset_for_new_session_clears_once():
    """reset_for_new_session 后 only_once 重置。"""
    rules = [_prompt_rule("once", Event.STOP, "ONCE", only_once=True)]
    eng = Engine(rules, ["x.yaml"])
    await eng.dispatch(Event.STOP, PAYLOAD)
    res = await eng.dispatch(Event.STOP, PAYLOAD)
    assert res.injected_prompts == []
    eng.reset_for_new_session()
    res = await eng.dispatch(Event.STOP, PAYLOAD)
    assert res.injected_prompts == ["ONCE"]


@pytest.mark.asyncio
async def test_async_rule_does_not_block(tmp_path):
    """async rule 起后台 task、立即返回，不进入 blocked 判定。"""
    marker = tmp_path / "ran.txt"
    cmd = (
        f"python -c \"import pathlib; pathlib.Path(r'{marker}').write_text('done')\""
    )
    rules = [_shell_rule("async", Event.PRE_TOOL_USE, cmd, asyncio_mode=True)]
    eng = Engine(rules, ["x.yaml"])
    payload = {"event": "PreToolUse", "tool_name": "write_file", "tool_input": {}}
    res = await eng.dispatch(Event.PRE_TOOL_USE, payload)
    assert not res.blocked
    # 等待后台 task 完成
    for _ in range(50):
        if marker.exists():
            break
        await asyncio.sleep(0.1)
    assert marker.exists()


@pytest.mark.asyncio
async def test_event_mismatch_skipped():
    """event 不匹配的 rule 不执行。"""
    rules = [_prompt_rule("a", Event.STOP, "A")]
    eng = Engine(rules, ["x.yaml"])
    res = await eng.dispatch(Event.SESSION_START, PAYLOAD)
    assert res.injected_prompts == []
