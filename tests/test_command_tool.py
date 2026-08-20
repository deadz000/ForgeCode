"""/tool 命令 handler 单测：列表、展开详情、last、clear、错误序号。"""

from __future__ import annotations

import pytest

from forgecode.command.builtin_local import handle_tool
from forgecode.command.ui import ToolLogEntry


class FakeToolUI:
    """实现 UI 协议的工具日志部分 + 记录 println 输出。"""

    def __init__(self, entries: list[ToolLogEntry]) -> None:
        self._entries = list(entries)
        self.outputs: list[str] = []
        self.cleared = 0
        self._current_slash_args = ""

    def println(self, msg: str) -> None:
        self.outputs.append(msg)

    def error(self, msg: str) -> None:
        self.outputs.append(f"ERR: {msg}")

    def tool_log(self, limit: int = 10) -> list[ToolLogEntry]:
        return list(reversed(self._entries[-limit:]))

    def tool_log_detail(self, index: int) -> ToolLogEntry | None:
        for e in self._entries:
            if e.index == index:
                return e
        return None

    def tool_log_clear(self) -> None:
        self._entries.clear()
        self.cleared += 1


def _entries() -> list[ToolLogEntry]:
    return [
        ToolLogEntry(
            index=1,
            name="read_file",
            args='{"path":"a.py"}',
            result="line1\nline2",
            is_error=False,
            elapsed=0.2,
        ),
        ToolLogEntry(
            index=2, name="bash", args='{"command":"pytest"}', result="boom", is_error=True, elapsed=3.4
        ),
    ]


@pytest.mark.asyncio
async def test_tool_list_shows_summaries():
    ui = FakeToolUI(_entries())
    await handle_tool(ui)
    text = "\n".join(ui.outputs)
    assert "工具调用日志" in text
    assert "#2" in text and "bash" in text and "3.4s" in text
    assert "#1" in text and "read_file" in text


@pytest.mark.asyncio
async def test_tool_detail_expands_full_result():
    ui = FakeToolUI(_entries())
    ui._current_slash_args = "1"
    await handle_tool(ui)
    text = "\n".join(ui.outputs)
    assert "read_file" in text
    assert "line2" in text  # 完整结果（不止首行）
    assert '{"path":"a.py"}' in text


@pytest.mark.asyncio
async def test_tool_last():
    ui = FakeToolUI(_entries())
    ui._current_slash_args = "last"
    await handle_tool(ui)
    text = "\n".join(ui.outputs)
    assert "bash" in text  # 最近一条是 index=2


@pytest.mark.asyncio
async def test_tool_clear():
    ui = FakeToolUI(_entries())
    ui._current_slash_args = "clear"
    await handle_tool(ui)
    assert ui.cleared == 1
    assert "已清空" in "\n".join(ui.outputs)


@pytest.mark.asyncio
async def test_tool_missing_index():
    ui = FakeToolUI(_entries())
    ui._current_slash_args = "42"
    await handle_tool(ui)
    assert "没有序号为 42" in "\n".join(ui.outputs)


@pytest.mark.asyncio
async def test_tool_invalid_args():
    ui = FakeToolUI(_entries())
    ui._current_slash_args = "abc"
    await handle_tool(ui)
    assert "用法" in "\n".join(ui.outputs)


@pytest.mark.asyncio
async def test_tool_empty_log():
    ui = FakeToolUI([])
    await handle_tool(ui)
    assert "尚无工具调用记录" in "\n".join(ui.outputs)
