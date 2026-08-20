"""SlashCompleter 单测：命令名前缀补全 + 参数补全（A6）。"""

from __future__ import annotations

from prompt_toolkit.document import Document

from forgecode.command import Registry, register_builtins
from forgecode.command.command import Command, Kind
from forgecode.tui.complete import SlashCompleter


def _collect(completer: SlashCompleter, text: str) -> list[str]:
    doc = Document(text=text, cursor_position=len(text))
    return [c.text for c in completer.get_completions(doc, None)]


def _builtin_completer() -> SlashCompleter:
    reg = Registry()
    register_builtins(reg)
    return SlashCompleter(reg)


def test_command_name_completion():
    comp = _builtin_completer()
    assert _collect(comp, "/wor") == ["/worktree"]
    assert _collect(comp, "/help") == ["/help"]
    assert _collect(comp, "/")  # 空前缀：全部可见命令


def test_argument_completion_after_space():
    comp = _builtin_completer()
    # /worktree <tab> → 子命令候选（前缀过滤）
    assert _collect(comp, "/worktree ") == ["create", "list", "enter", "exit", "remove"]
    assert _collect(comp, "/worktree l") == ["list"]
    assert _collect(comp, "/team ") == ["list", "info", "delete", "kill"]
    assert _collect(comp, "/tool ") == ["last", "clear"]


def test_argument_completion_only_for_declared():
    comp = _builtin_completer()
    # /clear 无参数补全器 → 无候选
    assert _collect(comp, "/clear ") == []
    # 未知命令 → 无候选
    assert _collect(comp, "/nosuch ") == []


def test_argument_completion_not_on_multiline():
    comp = _builtin_completer()
    assert _collect(comp, "/worktree\nl") == []


def test_hidden_command_argument_completion():
    reg = Registry()
    reg.register(
        Command(
            name="thinking",
            description="t",
            kind=Kind.LOCAL,
            handler=lambda ui: None,
            hidden=True,
            accepts_args=True,
            argument_completer=lambda prefix: [s for s in ("on", "off") if s.startswith(prefix)],
        )
    )
    comp = SlashCompleter(reg)
    # hidden 命令不出现在命令名补全，但参数补全可命中
    assert _collect(comp, "/thi") == []
    assert _collect(comp, "/thinking ") == ["on", "off"]
    assert _collect(comp, "/thinking o") == ["on", "off"]
