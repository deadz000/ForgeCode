"""permission.sandbox 单测：项目根约束 + /tmp 系统临时目录白名单（N9）。"""

from __future__ import annotations

from pathlib import Path

from forgecode.permission.sandbox import sandbox_ok


def test_inside_root(tmp_path: Path) -> None:
    root = tmp_path
    assert sandbox_ok(str(root), str(root / "a" / "b.py")) is True
    assert sandbox_ok(str(root), "rel.py") is True
    assert sandbox_ok(str(root), "") is True


def test_outside_root(tmp_path: Path) -> None:
    root = tmp_path
    outside = tmp_path.parent / "outside" / "x.py"
    assert sandbox_ok(str(root), str(outside)) is False


def test_tmp_whitelisted(tmp_path: Path) -> None:
    root = tmp_path
    assert sandbox_ok(str(root), "/tmp/foo.txt") is True
    assert sandbox_ok(str(root), "/private/tmp/bar.txt") is True


def test_system_paths_denied(tmp_path: Path) -> None:
    root = tmp_path
    assert sandbox_ok(str(root), "/etc/passwd") is False
    assert sandbox_ok(str(root), "/usr/bin/rm") is False
