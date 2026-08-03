"""内置命令测试：注册完整性、NopUI 调用不抛、RecordingUI 行为断言。"""

from __future__ import annotations

import pytest

from forgecode.command import NopUI, Registry, register_builtins
from forgecode.command.builtin_local import handle_status
from forgecode.command.builtin_prompt import handle_do
from forgecode.command.builtin_ui import handle_compact
from forgecode.permission import Mode

# ── 注册完整性 ──


def test_register_builtins_all_registered():
    """注册后 visible() 含 13 条命令，名字完整且按字典序。"""
    reg = Registry()
    register_builtins(reg)
    visible = reg.visible()
    names = [c.name for c in visible]
    expected = [
        "clear",
        "compact",
        "do",
        "exit",
        "help",
        "hooks",
        "memory",
        "permission",
        "plan",
        "resume",
        "session",
        "skill",
        "status",
    ]
    assert len(visible) == 13
    assert names == expected


def test_register_builtins_no_collision():
    """直接调 register_builtins 不抛异常。"""
    reg = Registry()
    register_builtins(reg)
    assert len(reg.visible()) == 13


# ── NopUI 不抛 ──


@pytest.mark.asyncio
async def test_all_handlers_run_on_nop_ui():
    """所有 12 条命令 handler 在 NopUI 上执行不抛异常。"""
    reg = Registry()
    register_builtins(reg)
    ui = NopUI()
    for cmd in reg.visible():
        await cmd.handler(ui)


# ── RecordingUI 行为断言 ──


class RecordingUI(NopUI):
    """记录 println/error/set_mode/inject_and_send 调用的测试桩。"""

    def __init__(self):
        super().__init__()
        self.printed: list[str] = []
        self.errors: list[str] = []
        self._mode: Mode = Mode.DEFAULT
        self.injected_label: str | None = None
        self.injected_preset: str | None = None
        self._idle: bool = True
        self.compact_called: bool = False

    def println(self, msg: str) -> None:
        self.printed.append(msg)

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def get_mode(self) -> Mode:
        return self._mode

    def set_mode(self, m: Mode) -> None:
        self._mode = m

    def inject_and_send(self, label: str, preset: str) -> None:
        self.injected_label = label
        self.injected_preset = preset

    def idle(self) -> bool:
        return self._idle

    def force_compact(self) -> None:
        self.compact_called = True


@pytest.mark.asyncio
async def test_handle_status_prints_all_keys():
    """handle_status 输出含全部 6 个 key。"""
    ui = RecordingUI()
    await handle_status(ui)
    output = ui.printed[0] if ui.printed else ""
    for key in ["Mode:", "Tokens:", "Tools:", "Memories:", "Model:", "Directory:"]:
        assert key in output, f"Missing key {key} in status output"


@pytest.mark.asyncio
async def test_handle_compact_blocks_when_busy():
    """handle_compact 在 idle()==False 时调 error 不调 force_compact。"""
    ui = RecordingUI()
    ui._idle = False
    await handle_compact(ui)
    assert not ui.compact_called
    assert len(ui.errors) == 1


@pytest.mark.asyncio
async def test_handle_do_sets_mode_and_injects():
    """handle_do 调 set_mode(Mode.DEFAULT) + inject_and_send。"""
    ui = RecordingUI()
    ui._mode = Mode.PLAN  # 初始为 PLAN
    await handle_do(ui)
    assert ui._mode == Mode.DEFAULT
    assert ui.injected_label == "/do"
    assert ui.injected_preset is not None
    assert "执行" in ui.injected_preset


@pytest.mark.asyncio
async def test_help_handler_output():
    """/help 输出含全部 12 个命令名。"""
    reg = Registry()
    register_builtins(reg)
    help_cmd = reg.lookup("help")
    assert help_cmd is not None

    ui = RecordingUI()
    await help_cmd.handler(ui)
    output = ui.printed[0] if ui.printed else ""
    expected_names = [
        "clear",
        "compact",
        "do",
        "exit",
        "help",
        "memory",
        "permission",
        "plan",
        "resume",
        "session",
        "skill",
        "status",
    ]
    for name in expected_names:
        assert f"/{name}" in output, f"Missing /{name} in help output"
