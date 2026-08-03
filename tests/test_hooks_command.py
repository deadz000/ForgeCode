"""/hooks 命令测试：输出格式、空状态、分组与来源。"""

from __future__ import annotations

import pytest

from forgecode.command import NopUI
from forgecode.hook.event import Event as HookEvent
from forgecode.hook.rule import Action, ActionType, PromptAction, Rule, ShellAction
from forgecode.tui.hooks import handle_hooks


class HookUI(NopUI):
    def __init__(self, rules, sources):
        super().__init__()
        self._rules = rules
        self._sources = sources
        self.printed: list[str] = []

    def println(self, msg: str) -> None:
        self.printed.append(msg)

    def hook_rules(self) -> list:
        return self._rules

    def hook_sources(self) -> list[str]:
        return self._sources


@pytest.mark.asyncio
async def test_hooks_no_hooks():
    """无 hook → 'No hooks loaded.'。"""
    ui = HookUI([], [])
    await handle_hooks(ui)
    assert ui.printed == ["No hooks loaded."]


@pytest.mark.asyncio
async def test_hooks_lists_rules_grouped():
    """按 event 分组输出 + flags + 加载来源。"""
    rules = [
        Rule(
            name="a",
            event=HookEvent.SESSION_START,
            action=Action(type=ActionType.SHELL, shell=ShellAction(command="x")),
        ),
        Rule(
            name="b",
            event=HookEvent.SESSION_START,
            action=Action(type=ActionType.PROMPT, prompt=PromptAction(text="y")),
            only_once=True,
        ),
        Rule(
            name="c",
            event=HookEvent.STOP,
            action=Action(type=ActionType.PROMPT, prompt=PromptAction(text="z")),
            asyncio_mode=True,
        ),
    ]
    ui = HookUI(rules, ["/p/.forgecode/hooks.yaml", "/home/.forgecode/hooks.yaml"])
    await handle_hooks(ui)
    out = ui.printed[0]

    assert "SessionStart:" in out
    assert "  a  SessionStart  shell" in out
    assert "  b  SessionStart  prompt [once]" in out
    assert "Stop:" in out
    assert "  c  Stop  prompt [async]" in out
    assert "Loaded from: /p/.forgecode/hooks.yaml, /home/.forgecode/hooks.yaml" in out


@pytest.mark.asyncio
async def test_hooks_sources_none():
    """无来源文件时 Loaded from 显示 (none)。"""
    rule = Rule(
        name="a",
        event=HookEvent.STOP,
        action=Action(type=ActionType.PROMPT, prompt=PromptAction(text="x")),
    )
    ui = HookUI([rule], [])
    await handle_hooks(ui)
    assert "Loaded from: (none)" in ui.printed[0]
