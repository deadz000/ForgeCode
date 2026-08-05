"""内置命令测试：注册完整性、NopUI 调用不抛、RecordingUI 行为断言。"""

from __future__ import annotations

import pytest

from forgecode.command import NopUI, Registry, register_builtins
from forgecode.command.builtin_local import handle_status
from forgecode.command.builtin_prompt import handle_do
from forgecode.command.builtin_ui import handle_compact
from forgecode.command.builtin_worktree import handle_worktree
from forgecode.command.ui import WorktreeSummary
from forgecode.permission import Mode

# ── 注册完整性 ──


def test_register_builtins_all_registered():
    """注册后 visible() 含 14 条命令，名字完整且按字典序。"""
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
        "worktree",
    ]
    assert len(visible) == 14
    assert names == expected


def test_register_builtins_no_collision():
    """直接调 register_builtins 不抛异常。"""
    reg = Registry()
    register_builtins(reg)
    assert len(reg.visible()) == 14


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
        self._accessor = None

    def println(self, msg: str) -> None:
        self.printed.append(msg)

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def worktree_accessor(self):
        return self._accessor

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
        "worktree",
    ]
    for name in expected_names:
        assert f"/{name}" in output, f"Missing /{name} in help output"


# ── /worktree handler ──


class StubWorktreeAccessor:
    """记录调用并返回固定结果的 WorktreeAccessor 桩。"""

    def __init__(self) -> None:
        self.created: list[str] = []
        self.entered: list[str] = []
        self.exited: list[tuple[str, bool]] = []
        self.removed: list[tuple[str, bool]] = []

    async def create(self, name: str) -> tuple[str, str]:
        self.created.append(name)
        return f"/path/{name}", f"branch-{name}"

    def list(self) -> list[WorktreeSummary]:
        return [
            WorktreeSummary(
                name="alice", path="/p/alice", branch="worktree-alice", active=False, manual=True
            ),
            WorktreeSummary(name="bob", path="/p/bob", branch="worktree-bob", active=True, manual=False),
        ]

    async def enter(self, name: str) -> None:
        self.entered.append(name)

    async def exit(self, action: str, discard: bool) -> bool:
        self.exited.append((action, discard))
        return True

    async def remove(self, name: str, discard: bool) -> None:
        self.removed.append((name, discard))


@pytest.mark.asyncio
async def test_handle_worktree_accessor_none_reports_error():
    ui = RecordingUI()  # worktree_accessor() 返回 None
    ui._current_slash_args = "list"
    await handle_worktree(ui)
    assert ui.errors
    assert "未启用" in ui.errors[0]


@pytest.mark.asyncio
async def test_handle_worktree_create():
    ui = RecordingUI()
    accessor = StubWorktreeAccessor()
    ui._accessor = accessor
    ui._current_slash_args = "create foo"
    await handle_worktree(ui)
    assert accessor.created == ["foo"]
    assert "Worktree 已创建" in ui.printed[0]
    assert "branch-foo" in ui.printed[0]


@pytest.mark.asyncio
async def test_handle_worktree_list():
    ui = RecordingUI()
    accessor = StubWorktreeAccessor()
    ui._accessor = accessor
    ui._current_slash_args = "list"
    await handle_worktree(ui)
    output = "\n".join(ui.printed)
    assert "alice" in output
    assert "worktree-alice" in output
    assert "[manual]" in output
    assert "[active]" in output


@pytest.mark.asyncio
async def test_handle_worktree_enter():
    ui = RecordingUI()
    accessor = StubWorktreeAccessor()
    ui._accessor = accessor
    ui._current_slash_args = "enter bob"
    await handle_worktree(ui)
    assert accessor.entered == ["bob"]


@pytest.mark.asyncio
async def test_handle_worktree_exit_with_discard():
    ui = RecordingUI()
    accessor = StubWorktreeAccessor()
    ui._accessor = accessor
    ui._current_slash_args = "exit --remove --discard"
    await handle_worktree(ui)
    assert accessor.exited == [("remove", True)]


@pytest.mark.asyncio
async def test_handle_worktree_remove():
    ui = RecordingUI()
    accessor = StubWorktreeAccessor()
    ui._accessor = accessor
    ui._current_slash_args = "remove alice --discard"
    await handle_worktree(ui)
    assert accessor.removed == [("alice", True)]


@pytest.mark.asyncio
async def test_handle_worktree_unknown_subcommand():
    ui = RecordingUI()
    accessor = StubWorktreeAccessor()
    ui._accessor = accessor
    ui._current_slash_args = "bogus x"
    await handle_worktree(ui)
    assert ui.errors
