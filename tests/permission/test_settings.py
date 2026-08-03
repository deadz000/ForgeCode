"""to_rule_set 错误日志与跳过逻辑覆盖。"""

from __future__ import annotations

from forgecode.permission.settings import Settings, to_rule_set


def test_to_rule_set_skips_bad_rule_with_stderr(capsys):
    """非法 rule → stderr 含 parse failed，RuleSet 不含该 rule。"""
    from forgecode.permission.settings import PermissionsBlock

    s = Settings(
        permissions=PermissionsBlock(
            allow=["Bash(git *)", "Bash(~[invalid)"],
            deny=[],
        )
    )
    rs = to_rule_set(s)
    assert len(rs.allow) == 1  # 非法规则被跳过
    assert rs.allow[0].tool == "Bash"

    captured = capsys.readouterr()
    assert "parse failed" in captured.err
    assert "Bash(~[invalid)" in captured.err


def test_to_rule_set_valid_rules_no_stderr(capsys):
    """全部合法 → stderr 为空。"""
    from forgecode.permission.settings import PermissionsBlock

    s = Settings(
        permissions=PermissionsBlock(
            allow=["Bash(=git status)"],
            deny=["Bash(!~^rm)"],
        )
    )
    rs = to_rule_set(s)
    assert len(rs.allow) == 1
    assert len(rs.deny) == 1
    assert capsys.readouterr().err == ""


def test_to_rule_set_deny_error_also_stderr(capsys):
    """deny 段非法同样 stderr。"""
    from forgecode.permission.settings import PermissionsBlock

    s = Settings(
        permissions=PermissionsBlock(
            allow=[],
            deny=["Bash(!bad)unclosed"],
        )
    )
    rs = to_rule_set(s)
    assert len(rs.deny) == 0
    assert "parse failed" in capsys.readouterr().err
