"""工具系统单测：注册中心 + 6 个核心工具。"""

import json

import pytest

from forgecode.tool import Registry, new_default_registry

# ── 注册中心 ──────────────────────────────────────


def test_registry_definitions():
    reg = new_default_registry()
    defs = reg.definitions()
    assert len(defs) == 6
    names = [d.name for d in defs]
    assert names == [
        "read_file",
        "write_file",
        "edit_file",
        "bash",
        "glob",
        "grep",
    ]


def test_registry_get():
    reg = new_default_registry()
    assert reg.get("read_file") is not None
    assert reg.get("nonexistent") is None


def test_registry_duplicate():
    reg = Registry()
    from forgecode.tool.read_file import ReadFileTool

    reg.register(ReadFileTool())
    with pytest.raises(ValueError, match="已注册"):
        reg.register(ReadFileTool())


# ── read_file ─────────────────────────────────────


@pytest.mark.asyncio
async def test_read_file_exists():
    reg = new_default_registry()
    result = await reg.execute("read_file", '{"path": "pyproject.toml"}')
    assert not result.is_error
    assert "name" in result.content.lower()
    # 应有行号
    assert "\t" in result.content


@pytest.mark.asyncio
async def test_read_file_not_exists():
    reg = new_default_registry()
    result = await reg.execute("read_file", '{"path": "/nonexistent/file.txt"}')
    assert result.is_error
    assert "不存在" in result.content


@pytest.mark.asyncio
async def test_read_file_missing_param():
    reg = new_default_registry()
    result = await reg.execute("read_file", "{}")
    assert result.is_error


# ── write_file ────────────────────────────────────


@pytest.mark.asyncio
async def test_write_and_read(tmp_path):
    reg = new_default_registry()
    test_file = tmp_path / "test.txt"

    r = await reg.execute(
        "write_file",
        json.dumps({"path": str(test_file), "content": "hello world"}),
    )
    assert not r.is_error
    assert "已写入" in r.content
    assert test_file.read_text() == "hello world"


@pytest.mark.asyncio
async def test_write_nested_dir(tmp_path):
    reg = new_default_registry()
    test_file = tmp_path / "a" / "b" / "c.txt"

    r = await reg.execute(
        "write_file",
        json.dumps({"path": str(test_file), "content": "nested"}),
    )
    assert not r.is_error
    assert test_file.read_text() == "nested"


# ── edit_file ─────────────────────────────────────


@pytest.mark.asyncio
async def test_edit_file_unique_match(tmp_path):
    reg = new_default_registry()
    test_file = tmp_path / "edit.txt"
    test_file.write_text("hello world")

    r = await reg.execute(
        "edit_file",
        json.dumps({"path": str(test_file), "old_string": "hello", "new_string": "hi"}),
    )
    assert not r.is_error
    assert test_file.read_text() == "hi world"


@pytest.mark.asyncio
async def test_edit_file_no_match(tmp_path):
    reg = new_default_registry()
    test_file = tmp_path / "edit.txt"
    test_file.write_text("hello world")

    r = await reg.execute(
        "edit_file",
        json.dumps({"path": str(test_file), "old_string": "xyz", "new_string": "a"}),
    )
    assert r.is_error
    assert "未找到匹配" in r.content


@pytest.mark.asyncio
async def test_edit_file_multiple_match(tmp_path):
    reg = new_default_registry()
    test_file = tmp_path / "edit.txt"
    test_file.write_text("hello hello")

    r = await reg.execute(
        "edit_file",
        json.dumps({"path": str(test_file), "old_string": "hello", "new_string": "hi"}),
    )
    assert r.is_error
    assert "不唯一" in r.content or "2 处" in r.content


# ── bash ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_bash_echo():
    reg = new_default_registry()
    result = await reg.execute("bash", '{"command": "echo hello"}')
    assert not result.is_error
    assert "hello" in result.content
    assert "exit_code: 0" in result.content


@pytest.mark.asyncio
async def test_bash_timeout():
    reg = new_default_registry()
    # 用极短超时来触发超时
    result = await reg.execute("bash", '{"command": "sleep 10"}', timeout=0.5)
    assert result.is_error
    assert "超时" in result.content


# ── glob ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_glob_py_files():
    reg = new_default_registry()
    result = await reg.execute("glob", '{"pattern": "**/*.py", "path": "src"}')
    assert not result.is_error
    assert len(result.content) > 0
    assert ".py" in result.content


@pytest.mark.asyncio
async def test_glob_no_match():
    reg = new_default_registry()
    result = await reg.execute("glob", '{"pattern": "*.xyzzy"}')
    assert not result.is_error
    assert "无匹配" in result.content


# ── grep ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_grep_keyword():
    reg = new_default_registry()
    result = await reg.execute(
        "grep",
        '{"pattern": "forgecode", "path": "src", "glob": "*.py"}',
    )
    assert not result.is_error
    assert "forgecode" in result.content.lower()


@pytest.mark.asyncio
async def test_grep_no_hit():
    reg = new_default_registry()
    result = await reg.execute(
        "grep",
        '{"pattern": "XYZZY_NONEXISTENT_PATTERN", "path": "src"}',
    )
    assert not result.is_error
    assert "无命中" in result.content


@pytest.mark.asyncio
async def test_grep_invalid_regex():
    reg = new_default_registry()
    result = await reg.execute("grep", '{"pattern": "["}')
    assert result.is_error
    assert "正则非法" in result.content


# ── Registry 未知工具 ─────────────────────────────


@pytest.mark.asyncio
async def test_unknown_tool():
    reg = new_default_registry()
    result = await reg.execute("nonexistent", "{}")
    assert result.is_error
    assert "未知工具" in result.content
