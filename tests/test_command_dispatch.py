"""parse 输入解析测试：表驱动覆盖各种输入形态。"""

from __future__ import annotations

import pytest

from forgecode.command.dispatch import parse


@pytest.mark.parametrize(
    "input_text, expected_name, expected_is_slash",
    [
        ("", "", False),
        ("   ", "", False),
        ("hello", "", False),
        ("hello world", "", False),
        ("/", "", True),
        ("/help", "help", True),
        ("  /HELP  ", "help", True),
        ("/help xx", "help", True),  # 尾随参数 → 保留命令名，args 校验交给 dispatch_slash
        ("/help  ", "help", True),
        ("/ /help", "", True),  # 空格在 name 之前 → 强制 miss
        ("//double", "", True),  # "//double" → 双斜杠不被识别为有效命令
    ],
)
def test_parse(input_text, expected_name, expected_is_slash):
    """表驱动测试 parse 的各种输入形态。"""
    name, is_slash = parse(input_text)
    assert name == expected_name, f"input={input_text!r}: expected name={expected_name!r}, got {name!r}"
    assert is_slash == expected_is_slash, (
        f"input={input_text!r}: expected is_slash={expected_is_slash}, got {is_slash}"
    )


def test_parse_case_insensitive():
    """命令名转为小写。"""
    name, is_slash = parse("/Help")
    assert is_slash is True
    assert name == "help"


def test_parse_trailing_space_only():
    """仅尾随空白的 /help → 正常解析。"""
    name, is_slash = parse("/help   ")
    assert is_slash is True
    assert name == "help"
