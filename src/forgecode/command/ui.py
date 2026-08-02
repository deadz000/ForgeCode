"""UI Protocol：handler 操作 TUI 的唯一通道 + NopUI 测试桩。"""

from __future__ import annotations

from typing import Protocol

from forgecode.permission import Mode


class UI(Protocol):
    """命令 handler 通过该协议访问 TUI 能力，不直接持有 TUI 框架类型。"""

    # ── 输出 ──
    def println(self, msg: str) -> None: ...
    def error(self, msg: str) -> None: ...

    # ── 模式 ──
    def get_mode(self) -> Mode: ...  # 注意：名为 get_mode 以避免与 ForgeApp.mode 属性冲突
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

    # ── 影响界面动作 ──
    def quit(self) -> None: ...
    def force_compact(self) -> None: ...
    async def open_resume_menu(self) -> None: ...
    def clear_and_new_session(self) -> None: ...

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

    def quit(self) -> None:
        pass

    def force_compact(self) -> None:
        pass

    async def open_resume_menu(self) -> None:
        pass

    def clear_and_new_session(self) -> None:
        pass

    def idle(self) -> bool:
        return True
