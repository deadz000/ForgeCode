"""UI Protocol：handler 操作 TUI 的唯一通道 + NopUI 测试桩。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from forgecode.conversation.history import Message
from forgecode.permission import Mode

if TYPE_CHECKING:
    from forgecode.hook.rule import Rule


@dataclass(frozen=True)
class SkillSummary:
    name: str
    description: str
    source: str
    mode: str


@dataclass(frozen=True)
class WorktreeSummary:
    name: str
    path: str
    branch: str
    active: bool
    manual: bool


class WorktreeAccessor(Protocol):
    """/worktree 命令访问 Worktree 管理器的轻量协议（屏蔽反向依赖）。"""

    async def create(self, name: str) -> tuple[str, str]: ...  # (path, branch)
    def list(self) -> list[WorktreeSummary]: ...
    async def enter(self, name: str) -> None: ...
    async def exit(self, action: str, discard: bool) -> bool: ...  # removed
    async def remove(self, name: str, discard: bool) -> None: ...


class UI(Protocol):
    """命令 handler 通过该协议访问 TUI 能力，不直接持有 TUI 框架类型。"""

    # ── 输出 ──
    def println(self, msg: str) -> None: ...
    def error(self, msg: str) -> None: ...

    # ── 模式 ──
    def get_mode(self) -> Mode: ...
    def set_mode(self, m: Mode) -> None: ...

    # ── 对话注入（KindPrompt 命令使用）──
    def inject_and_send(self, display_label: str, preset_prompt: str) -> None: ...

    # ── 只读查询 ──
    def usage_in(self) -> int: ...
    def usage_out(self) -> int: ...
    def model_name(self) -> str: ...
    def cwd(self) -> str: ...
    def tool_count(self) -> int: ...
    def memory_files(self) -> list[str]: ...
    def session_path(self) -> str: ...
    def session_id(self) -> str: ...

    # ── Skill 查询与操作 ──
    def list_catalog_skills(self) -> list[SkillSummary]: ...
    def list_active_skills(self) -> list[str]: ...
    def clear_active_skills(self) -> None: ...
    async def append_assistant_message(self, text: str) -> None: ...
    def recent_messages(self, n: int) -> list[Message]: ...
    def all_messages(self) -> list[Message]: ...

    # ── Worktree 访问 ──
    def worktree_accessor(self) -> WorktreeAccessor | None: ...

    # ── Hook 查询 ──
    def hook_sources(self) -> list[str]: ...
    def hook_rules(self) -> list[Rule]: ...

    # ── 影响界面动作 ──
    def quit(self) -> None: ...
    def force_compact(self) -> None: ...
    async def open_resume_menu(self) -> None: ...
    async def clear_and_new_session(self) -> None: ...

    # ── 状态查询 ──
    def idle(self) -> bool: ...


class NopUI:
    """测试桩：所有写入方法 no-op、所有查询返回零值/默认值。"""

    def println(self, msg: str) -> None:
        pass

    def error(self, msg: str) -> None:
        pass

    def get_mode(self) -> Mode:
        return Mode.DEFAULT

    def set_mode(self, m: Mode) -> None:
        pass

    def inject_and_send(self, label: str, preset: str) -> None:
        pass

    def usage_in(self) -> int:
        return 0

    def usage_out(self) -> int:
        return 0

    def model_name(self) -> str:
        return ""

    def cwd(self) -> str:
        return ""

    def tool_count(self) -> int:
        return 0

    def memory_files(self) -> list[str]:
        return []

    def session_path(self) -> str:
        return ""

    def session_id(self) -> str:
        return ""

    def list_catalog_skills(self) -> list[SkillSummary]:
        return []

    def list_active_skills(self) -> list[str]:
        return []

    def clear_active_skills(self) -> None:
        pass

    async def append_assistant_message(self, text: str) -> None:
        pass

    def recent_messages(self, n: int) -> list[Message]:
        return []

    def all_messages(self) -> list[Message]:
        return []

    def hook_sources(self) -> list[str]:
        return []

    def hook_rules(self) -> list:
        return []

    def worktree_accessor(self) -> WorktreeAccessor | None:
        return None

    def quit(self) -> None:
        pass

    def force_compact(self) -> None:
        pass

    async def open_resume_menu(self) -> None:
        pass

    async def clear_and_new_session(self) -> None:
        pass

    def idle(self) -> bool:
        return True
