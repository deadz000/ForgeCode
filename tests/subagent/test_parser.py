"""subagent.parser 单测：frontmatter 解析与字段降级。"""

from __future__ import annotations

import pytest

from forgecode.permission import Mode
from forgecode.subagent.definition import Source
from forgecode.subagent.parser import parse_definition

GOOD = """---
name: explorer
description: 只读探索
disallowedTools:
  - write_file
  - edit_file
model: haiku
maxTurns: 10
permissionMode: plan
---

你是探索者。
""".encode()


def test_parse_full_frontmatter() -> None:
    d = parse_definition(GOOD, "test.md", Source.PROJECT)
    assert d.name == "explorer"
    assert d.description == "只读探索"
    assert d.disallowed_tools == ["write_file", "edit_file"]
    assert d.model == "haiku"
    assert d.max_turns == 10
    assert d.permission_mode is Mode.PLAN
    assert d.dont_ask is False
    assert d.system_prompt == "你是探索者。"
    assert d.file_path == "test.md"
    assert d.source is Source.PROJECT


def test_minimal_frontmatter() -> None:
    data = """---
name: mini
description: 最简
---
body
""".encode()
    d = parse_definition(data, "mini.md", Source.BUILTIN)
    assert d.name == "mini"
    assert d.model == "inherit"
    assert d.max_turns == 0
    assert d.permission_mode is Mode.DEFAULT
    assert d.tools == []


def test_dont_ask() -> None:
    data = """---
name: auto
description: 自动放行
permissionMode: dontAsk
---
""".encode()
    d = parse_definition(data, "auto.md", Source.USER)
    assert d.dont_ask is True
    assert d.permission_mode is Mode.DEFAULT


@pytest.mark.parametrize("bad_model", ["gpt-4", "claude-3", "weird"])
def test_invalid_model_fallback(capsys: pytest.CaptureFixture[str], bad_model: str) -> None:
    data = f"---\nname: m\ndescription: d\nmodel: {bad_model}\n---\n".encode()
    d = parse_definition(data, "m.md", Source.USER)
    assert d.model == "inherit"
    captured = capsys.readouterr()
    assert "unknown model" in captured.err


def test_missing_name_raises() -> None:
    with pytest.raises(ValueError):
        parse_definition(b"---\ndescription: d\n---\n", "x.md", Source.USER)


def test_missing_description_raises() -> None:
    with pytest.raises(ValueError):
        parse_definition(b"---\nname: x\n---\n", "x.md", Source.USER)


def test_unclosed_frontmatter_raises() -> None:
    with pytest.raises(ValueError):
        parse_definition(b"---\nname: x\ndescription: d\n", "x.md", Source.USER)


def test_unknown_permission_mode_fallback(capsys: pytest.CaptureFixture[str]) -> None:
    data = b"---\nname: x\ndescription: d\npermissionMode: weirdMode\n---\n"
    d = parse_definition(data, "x.md", Source.USER)
    assert d.permission_mode is Mode.DEFAULT
    captured = capsys.readouterr()
    assert "unknown permissionMode" in captured.err


def test_bom_stripped() -> None:
    data = b"\xef\xbb\xbf---\nname: x\ndescription: d\n---\nbody"
    d = parse_definition(data, "x.md", Source.USER)
    assert d.name == "x"
    assert d.system_prompt == "body"
