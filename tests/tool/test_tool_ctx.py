"""tool.ctx 单测：with_cwd / cwd_from_ctx / resolve_path + 6 个核心工具 ctx cwd（spec F16/F17）。"""

from __future__ import annotations

import json

import pytest

from forgecode.tool.bash import BashTool
from forgecode.tool.ctx import cwd_from_ctx, resolve_path, with_cwd
from forgecode.tool.edit_file import EditFileTool
from forgecode.tool.glob_tool import GlobTool
from forgecode.tool.grep_tool import GrepTool
from forgecode.tool.read_file import ReadFileTool
from forgecode.tool.write_file import WriteFileTool

# ── ctx 基础 ──


def test_with_cwd_sets_and_resets(tmp_path) -> None:
    assert cwd_from_ctx() is None
    with with_cwd(str(tmp_path)):
        assert cwd_from_ctx() == str(tmp_path)
    assert cwd_from_ctx() is None


def test_with_cwd_empty_noop(tmp_path) -> None:
    with with_cwd(""):
        assert cwd_from_ctx() is None


def test_resolve_absolute(tmp_path) -> None:
    assert resolve_path(str(tmp_path)) == str(tmp_path)


def test_resolve_relative_uses_ctx(tmp_path) -> None:
    with with_cwd(str(tmp_path)):
        assert resolve_path("a.txt") == str(tmp_path / "a.txt")


def test_resolve_relative_falls_back_to_process_cwd(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert resolve_path("a.txt") == str(tmp_path / "a.txt")


def test_resolve_empty_returns_base(tmp_path) -> None:
    with with_cwd(str(tmp_path)):
        assert resolve_path("") == str(tmp_path)


# ── 6 个核心工具 ctx cwd ──


@pytest.mark.asyncio
async def test_read_file_ctx_cwd(tmp_path) -> None:
    (tmp_path / "a.txt").write_text("hello ctx", encoding="utf-8")
    with with_cwd(str(tmp_path)):
        result = await ReadFileTool().execute(json.dumps({"path": "a.txt"}))
    assert not result.is_error
    assert "hello ctx" in result.content


@pytest.mark.asyncio
async def test_write_file_ctx_cwd(tmp_path) -> None:
    with with_cwd(str(tmp_path)):
        result = await WriteFileTool().execute(json.dumps({"path": "b.txt", "content": "x"}))
    assert not result.is_error
    assert (tmp_path / "b.txt").read_text(encoding="utf-8") == "x"


@pytest.mark.asyncio
async def test_edit_file_ctx_cwd(tmp_path) -> None:
    (tmp_path / "e.txt").write_text("aaa", encoding="utf-8")
    with with_cwd(str(tmp_path)):
        result = await EditFileTool().execute(
            json.dumps({"path": "e.txt", "old_string": "aaa", "new_string": "bbb"})
        )
    assert not result.is_error
    assert (tmp_path / "e.txt").read_text(encoding="utf-8") == "bbb"


@pytest.mark.asyncio
async def test_glob_ctx_cwd(tmp_path) -> None:
    (tmp_path / "x.txt").write_text("x", encoding="utf-8")
    with with_cwd(str(tmp_path)):
        result = await GlobTool().execute(json.dumps({"pattern": "*.txt"}))
    assert not result.is_error
    assert "x.txt" in result.content


@pytest.mark.asyncio
async def test_grep_ctx_cwd(tmp_path) -> None:
    (tmp_path / "g.txt").write_text("needle here", encoding="utf-8")
    with with_cwd(str(tmp_path)):
        result = await GrepTool().execute(json.dumps({"pattern": "needle"}))
    assert not result.is_error
    assert "g.txt" in result.content


@pytest.mark.asyncio
async def test_bash_ctx_cwd(tmp_path) -> None:
    """bash 子进程 cwd 使用 ctx cwd。"""
    with with_cwd(str(tmp_path)):
        result = await BashTool().execute('{"command": "python -c \\"import os;print(os.getcwd())\\""}')
    assert not result.is_error
    assert str(tmp_path) in result.content
