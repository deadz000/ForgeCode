"""命令注册中心测试：注册、冲突检测、前缀匹配、visible 排序。"""

from __future__ import annotations

import pytest

from forgecode.command.command import Command, Kind
from forgecode.command.registry import Registry


async def _nop_handler(ui) -> None:
    pass


def _make_cmd(name: str, **kwargs) -> Command:
    defaults = {
        "name": name,
        "description": f"Description for {name}",
        "kind": Kind.LOCAL,
        "handler": _nop_handler,
        "aliases": [],
        "hidden": False,
    }
    defaults.update(kwargs)
    return Command(**defaults)


# ── 注册 ──


def test_register_ok():
    """注册 3 条命令，按 name 和 alias 都能查到。"""
    reg = Registry()
    reg.register(_make_cmd("help"))
    reg.register(_make_cmd("status", aliases=["st"]))
    reg.register(_make_cmd("exit"))

    assert reg.lookup("help") is not None
    assert reg.lookup("Help") is not None  # 大小写不敏感
    assert reg.lookup("st") is not None
    assert reg.lookup("unknown") is None


def test_register_duplicate_name_raises():
    """同名命令注册两次抛出 RuntimeError。"""
    reg = Registry()
    reg.register(_make_cmd("help"))
    with pytest.raises(RuntimeError, match="help"):
        reg.register(_make_cmd("help"))


def test_register_duplicate_alias_raises():
    """别名与已有命令名冲突抛出 RuntimeError。"""
    reg = Registry()
    reg.register(_make_cmd("status"))
    with pytest.raises(RuntimeError, match="status"):
        reg.register(_make_cmd("help", aliases=["status"]))


def test_register_non_lowercase_raises():
    """大写键名应抛出 ValueError。"""
    reg = Registry()
    with pytest.raises(ValueError):
        reg.register(_make_cmd("Status"))


def test_register_empty_name_raises():
    """空名应抛出 ValueError。"""
    reg = Registry()
    with pytest.raises(ValueError):
        reg.register(_make_cmd(""))


# ── visible ──


def test_visible_sorted():
    """visible() 返回按 name 字典序排序。"""
    reg = Registry()
    reg.register(_make_cmd("compact"))
    reg.register(_make_cmd("exit"))
    reg.register(_make_cmd("clear"))
    reg.register(_make_cmd("help"))

    names = [c.name for c in reg.visible()]
    assert names == ["clear", "compact", "exit", "help"]


def test_visible_excludes_hidden():
    """hidden=True 的命令不出现在 visible() 中。"""
    reg = Registry()
    reg.register(_make_cmd("help"))
    reg.register(_make_cmd("internal", hidden=True))
    reg.register(_make_cmd("status"))

    names = [c.name for c in reg.visible()]
    assert "internal" not in names
    assert names == ["help", "status"]


def test_visible_returns_copy():
    """visible() 返回副本，外部修改不影响内部。"""
    reg = Registry()
    reg.register(_make_cmd("help"))
    vis = reg.visible()
    vis.clear()
    assert len(reg.visible()) == 1


# ── prefix_match ──


def test_prefix_match():
    """前缀匹配仅按 name 过滤，不匹配别名/描述。"""
    reg = Registry()
    reg.register(_make_cmd("session"))
    reg.register(_make_cmd("status"))
    reg.register(_make_cmd("help"))
    reg.register(_make_cmd("compact", aliases=["cp"]))

    # /s 前缀 → session, status
    result = reg.prefix_match("/s")
    names = [c.name for c in result]
    assert names == ["session", "status"]

    # /se → 仅 session
    result2 = reg.prefix_match("/se")
    assert [c.name for c in result2] == ["session"]

    # alias 不参与匹配
    result3 = reg.prefix_match("/cp")
    assert result3 == []


def test_prefix_match_case_insensitive():
    """前缀大小写不敏感。"""
    reg = Registry()
    reg.register(_make_cmd("help"))
    reg.register(_make_cmd("session"))

    result = reg.prefix_match("/H")
    names = [c.name for c in result]
    assert "help" in names


def test_prefix_match_empty():
    """空前缀返回全部 visible。"""
    reg = Registry()
    reg.register(_make_cmd("help"))
    reg.register(_make_cmd("status"))
    assert len(reg.prefix_match("")) == 2


def test_prefix_match_no_slash():
    """不以 / 开头也能正确匹配。"""
    reg = Registry()
    reg.register(_make_cmd("help"))
    result = reg.prefix_match("he")
    assert [c.name for c in result] == ["help"]


# ── hidden lookup ──


def test_hidden_still_lookupable():
    """hidden=True 的命令仍可通过 lookup 命中。"""
    reg = Registry()
    reg.register(_make_cmd("internal", hidden=True))
    cmd = reg.lookup("internal")
    assert cmd is not None
    assert cmd.hidden is True
