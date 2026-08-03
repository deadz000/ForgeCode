"""permission.Rule / parse_rule / RuleSet 新语法覆盖。"""

from __future__ import annotations

from forgecode.permission import Decision
from forgecode.permission.matcher import ExactMatcher, GlobMatcher, RegexMatcher
from forgecode.permission.rule import RuleSet, parse_rule


def test_parse_rule_bare_tool():
    """无括号 → 全匹配规则。"""
    r, err = parse_rule("Bash")
    assert err is None
    assert r is not None
    assert r.tool == "Bash"
    assert r.matcher is None
    assert r.allow is True


def test_parse_rule_glob_backward_compat():
    """Bash(git *) 沿用 glob（兼容 ch08）。"""
    r, err = parse_rule("Bash(git *)")
    assert err is None
    assert r is not None
    assert isinstance(r.matcher, GlobMatcher)
    assert r.matcher.match("git status")
    assert not r.matcher.match("git status -s")


def test_parse_rule_exact():
    """Bash(=git status) 精确匹配。"""
    r, err = parse_rule("Bash(=git status)")
    assert err is None
    assert r is not None
    assert isinstance(r.matcher, ExactMatcher)
    assert r.matcher.match("git status")
    assert not r.matcher.match("git status -s")


def test_parse_rule_regex():
    """Bash(~^npm.*) 正则匹配。"""
    r, err = parse_rule("Bash(~^npm (install|test)$)")
    assert err is None
    assert r is not None
    assert isinstance(r.matcher, RegexMatcher)
    assert r.matcher.match("npm install")
    assert not r.matcher.match("npm run dev")


def test_parse_rule_not_regex():
    """Bash(!~^rm) 反向正则。"""
    r, err = parse_rule("Bash(!~^rm)")
    assert err is None
    assert r is not None
    assert r.matcher.match("ls -lh")
    assert not r.matcher.match("rm -rf .")


def test_parse_rule_invalid_regex():
    """正则编译失败 → 返回 (None, err)。"""
    r, err = parse_rule("Bash(~[invalid)")
    assert r is None
    assert err is not None
    assert "invalid regex" in err


def test_parse_rule_bad_syntax():
    """括号不闭合 → 返回 (None, err)。"""
    r, err = parse_rule("Bash(git *")
    assert r is None
    assert err is not None


def test_parse_rule_empty():
    """空串 → (None, err)。"""
    r, err = parse_rule("   ")
    assert r is None
    assert err is not None


def test_rule_set_match_deny_first():
    """先 deny 后 allow。"""
    rs = RuleSet()
    rs.deny.append(parse_rule("Bash(rm *)")[0])
    rs.allow.append(parse_rule("Bash(*)")[0])
    d, hit = rs.match("Bash", "rm foo")
    assert hit
    assert d == Decision.DENY


def test_rule_set_match_allow():
    """未命中 deny 时命中 allow。"""
    rs = RuleSet()
    rs.allow.append(parse_rule("Bash(=git status)")[0])
    d, hit = rs.match("Bash", "git status")
    assert hit
    assert d == Decision.ALLOW


def test_rule_set_match_none():
    """无命中 → (ALLOW, False)。"""
    rs = RuleSet()
    rs.deny.append(parse_rule("Bash(=rm *)")[0])
    d, hit = rs.match("Bash", "ls -lh")
    assert not hit
    assert d == Decision.ALLOW


def test_rule_set_match_full_wildcard():
    """matcher=None 全匹配。"""
    rs = RuleSet()
    r, _ = parse_rule("Write")
    rs.allow.append(r)
    d, hit = rs.match("Write", "anything")
    assert hit
    assert d == Decision.ALLOW


def test_parse_rule_tool_case_sensitive():
    """工具名保持原样，is_command 仅对 Bash 生效。"""
    r, _ = parse_rule("bash(git *)")  # 小写 bash → is_command=False
    assert r is not None
    assert r.tool == "bash"
    assert isinstance(r.matcher, GlobMatcher)
    assert not r.matcher.is_command


def test_escape_glob():
    """转义 glob 元字符。"""
    from forgecode.permission.rule import escape_glob

    assert escape_glob("rm *") == "rm \\*"
    assert escape_glob("a?b[c]") == "a\\?b\\[c\\]"
