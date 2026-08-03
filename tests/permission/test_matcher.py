"""permission.Matcher 单元测试：四种类型 × 边界条件覆盖。"""

from __future__ import annotations

import pytest

from forgecode.permission.matcher import (
    ExactMatcher,
    GlobMatcher,
    NotMatcher,
    RegexMatcher,
    compile_matcher,
    match_command,
    match_path,
)


@pytest.mark.parametrize(
    "pattern, target, is_command, expected, id_",
    [
        # exact
        ("=git status", "git status", False, True, "exact-hit"),
        ("=git status", "git status -s", False, False, "exact-miss-extra"),
        ("=git status", "git status ", False, False, "exact-miss-trailing-space"),
        ("=", "", False, True, "exact-empty-value"),
        ("=", "x", False, False, "exact-empty-miss"),
        # regex
        ("~^npm (install|test)$", "npm install", False, True, "regex-hit"),
        ("~^npm (install|test)$", "npm run dev", False, False, "regex-miss"),
        ("~delete", "please delete file", False, True, "regex-substring"),
        ("~(?i)delete", "please DELETE file", False, True, "regex-case-insensitive"),
        ("~\\d+", "abc123", False, True, "regex-digits"),
        # not（反向）
        ("!foo", "foo", False, False, "not-exact-miss"),
        ("!foo", "bar", False, True, "not-exact-hit"),
        ("!~^rm", "ls -lh", False, True, "not-regex-hit"),
        ("!~^rm", "rm -rf .", False, False, "not-regex-miss"),
        ("!git *", "npm install", False, True, "not-glob-hit"),
        ("!git *", "git status", False, False, "not-glob-miss"),
        ("!=foo", "foo", False, False, "not-exact-miss-2"),
        ("!=foo", "bar", False, True, "not-exact-hit-2"),
        # glob command
        ("git *", "git status", True, True, "glob-cmd-hit"),
        ("git *", "git status -s", True, False, "glob-cmd-miss-word-count"),
        ("git *", "git clone", True, True, "glob-cmd-two-words"),
        ("*status", "git status", True, False, "glob-cmd-wildcard-word-count"),
        ("* status", "git status", True, True, "glob-cmd-wildcard-two-words"),
        # glob path
        ("**/*.py", "src/forgecode/main.py", False, True, "glob-path-doublestar"),
        ("**/*.py", "main.py", False, True, "glob-path-doublestar-root"),
        ("**/*.py", "src/main.txt", False, False, "glob-path-miss"),
        ("*.py", "src/main.py", False, False, "glob-path-single-seg"),
        ("*.py", "main.py", False, True, "glob-path-single-seg-hit"),
    ],
)
def test_matcher_hit_miss(pattern, target, is_command, expected, id_):
    """表驱动：命中/不命中用例。"""
    m = compile_matcher(pattern, is_command=is_command)
    assert m.match(target) is expected, f"pattern={pattern!r} target={target!r} id={id_}"


@pytest.mark.parametrize(
    "pattern, exc",
    [
        ("~[invalid", ValueError),
        ("", ValueError),
    ],
)
def test_matcher_compile_error(pattern, exc):
    """编译失败抛 ValueError。"""
    with pytest.raises(exc):
        compile_matcher(pattern, is_command=False)


def test_compile_exact_type():
    """= 前缀 → ExactMatcher。"""
    m = compile_matcher("=foo", is_command=False)
    assert isinstance(m, ExactMatcher)
    assert str(m) == "=foo"


def test_compile_regex_type():
    """~ 前缀 → RegexMatcher。"""
    m = compile_matcher("~foo", is_command=False)
    assert isinstance(m, RegexMatcher)
    assert str(m) == "~foo"


def test_compile_not_type():
    """! 前缀 → NotMatcher（内层编译）。"""
    m = compile_matcher("!=foo", is_command=False)
    assert isinstance(m, NotMatcher)
    assert isinstance(m.inner, ExactMatcher)


def test_compile_glob_type():
    """无前缀 → GlobMatcher。"""
    m = compile_matcher("foo", is_command=True)
    assert isinstance(m, GlobMatcher)


def test_nested_not_regex():
    """嵌套反向正则：!~^rm。"""
    m = compile_matcher("!~^rm", is_command=False)
    assert m.match("ls -lh") is True
    assert m.match("rm -rf .") is False


def test_not_str_roundtrip():
    """__str__ 保留原始前缀形态。"""
    m = compile_matcher("!=foo", is_command=False)
    assert str(m) == "!=foo"
    m2 = compile_matcher("!~^rm", is_command=False)
    assert str(m2) == "!~^rm"


def test_match_command_empty_pattern_matches_all():
    """空模式匹配一切命令。"""
    assert match_command("", "anything at all") is True


def test_match_path_empty_pattern_matches_all():
    """空模式匹配一切路径。"""
    assert match_path("", "a/b/c.py") is True
