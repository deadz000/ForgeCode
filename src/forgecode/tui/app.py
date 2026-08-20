"""TUI 主应用：终端界面渲染、输入处理、命令分发、Agent 集成。"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
import time
from typing import Any

from prompt_toolkit.application import Application, get_app
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
from prompt_toolkit.layout import Dimension, Float, FloatContainer, HSplit, Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.menus import CompletionsMenu
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import TextArea
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

from forgecode.agent import Agent, ApprovalRequest, CompactEvent, CompactPhase, Phase, ToolEvent
from forgecode.command import Kind as CmdKind
from forgecode.command import Registry as CmdRegistry
from forgecode.command import parse as parse_command
from forgecode.command import register_builtins
from forgecode.command.command import Command as CmdCommand
from forgecode.command.ui import SkillSummary, ToolLogEntry
from forgecode.config.schema import AppConfig
from forgecode.conversation.history import Conversation
from forgecode.hook import DispatchResult
from forgecode.hook.engine import Engine as HookEngine
from forgecode.hook.event import Event as HookEvent
from forgecode.permission import Mode, Outcome
from forgecode.permission.engine import Engine
from forgecode.prompt import EXECUTE_DIRECTIVE
from forgecode.providers import BaseProvider, create_provider
from forgecode.tool import Registry
from forgecode.tool.ctx import with_cwd
from forgecode.tui.complete import SlashCompleter

# ── FORGECODE pixel banner ──

FORGECODE_ART = r"""
   ███████╗ ██████╗ ██████╗  ██████╗ ███████╗ ██████╗ ██████╗ ██████╗ ███████╗
   ██╔════╝██╔═══██╗██╔══██╗██╔════╝ ██╔════╝██╔════╝██╔═══██╗██╔══██╗██╔════╝
   █████╗  ██║   ██║██████╔╝██║  ███╗█████╗  ██║     ██║   ██║██║  ██║█████╗
   ██╔══╝  ██║   ██║██╔══██╗██║   ██║██╔══╝  ██║     ██║   ██║██║  ██║██╔══╝
   ██║     ╚██████╔╝██║  ██║╚██████╔╝███████╗╚██████╗╚██████╔╝██████╔╝███████╗
   ╚═╝      ╚═════╝ ╚═╝  ╚═╝ ╚═════╝ ╚══════╝ ╚═════╝ ╚═════╝ ╚═════╝ ╚══════╝
"""

VERSION = "0.2.0"

# 空闲态第一次 Ctrl+C 的退出提示
EXIT_HINT = "再按一次 Ctrl+C 退出"

# ── prompt_toolkit 样式 ───────────────────────────

PROMPT_STYLE = Style.from_dict(
    {
        "prompt": "bold #00ff87",
        "placeholder": "#555555",
        # 补全菜单：黑底白字（当前项深蓝底白字高亮）
        "completion-menu": "bg:#000000 fg:#ffffff",
        "completion-menu.completion": "bg:#000000 fg:#ffffff",
        "completion-menu.completion.current": "bg:#005f87 fg:#ffffff",
        "completion-menu.meta": "bg:#000000 fg:#ffffff",
        "completion-menu.meta.current": "bg:#005f87 fg:#ffffff",
        # 输入框/边框/状态栏：黑底白字
        "input": "bg:#000000 fg:#ffffff",
        "input-border": "bg:#000000 fg:#ffffff",
        "bottom-toolbar": "bg:#000000 fg:#ffffff",
        "bottom-toolbar.text": "bg:#000000 fg:#ffffff",
    }
)


class ForgeApp:
    """ForgeCode 终端交互应用。"""

    def __init__(
        self,
        config: AppConfig,
        provider: BaseProvider,
        conversation: Conversation,
        registry: Registry,
        engine: Engine,
        runtime: Any = None,  # SessionRuntime
        *,
        writer: Any = None,  # session.Writer | None
        mem_mgr: Any = None,  # memory.Manager | None
        instruction_text: str = "",
        memory_text: str = "",
        sessions_dir: str = "",
        cmd_registry=None,
        catalog=None,
        executor=None,
        hook_engine: HookEngine | None = None,
        task_mgr=None,
        subagent_catalog=None,
        worktree_mgr=None,
        team_mgr=None,
        coordinator_mode: bool = False,
    ) -> None:
        self.config = config
        self.provider = provider
        self.conversation = conversation
        self.registry = registry
        self.engine = engine
        self.runtime = runtime
        self.hook_engine = hook_engine
        if runtime is not None:
            runtime.hook_engine = hook_engine
        self.console = Console()
        self._width = shutil.get_terminal_size().columns
        self._turn_live: Live | None = None
        # 流式 Markdown 渲染节流状态
        self._last_md_len: int = 0
        self._last_md_at: float = 0.0
        # 工具调用日志（/tool 命令折叠展开）
        self._tool_log: list[ToolLogEntry] = []
        self._tool_seq: int = 0
        self._tool_start_ts: dict[str, float] = {}
        self._tool_pending_args: dict[str, str] = {}
        self._show_thinking: bool = False
        self._exit_flag: bool = False
        # Agent Loop 状态
        self.mode: Mode = engine.start_mode()
        self._turn_cancel: asyncio.Event | None = None
        self._iter: int = 0
        # token 用量累计
        self._total_input_tokens: int = 0
        self._total_output_tokens: int = 0
        # 当前轮次计时
        self._response_start: float = 0
        self._response_elapsed: float = 0
        # 持久 Agent 实例
        self._agent: Agent | None = None
        # 记忆/会话持久化
        self._writer: Any = writer
        self._mem_mgr: Any = mem_mgr
        self._instruction_text: str = instruction_text
        self._memory_text: str = memory_text
        self._sessions_dir: str = sessions_dir
        self.catalog = catalog
        self.executor = executor
        self.task_mgr = task_mgr
        self.subagent_catalog = subagent_catalog
        self.worktree_mgr = worktree_mgr
        self.team_mgr = team_mgr
        self.coordinator_mode = coordinator_mode
        # Lead 邮箱自动唤醒信号（consume_lead_mail 置位）
        self.lead_mail_event: asyncio.Event = asyncio.Event()
        # Lead 邮箱后台消费/唤醒协程（run_async 启动）
        self._consume_lead = None
        self._lead_wait = None
        # 当前 Worktree 会话的 cwd（空表示进程 cwd）；/worktree enter 后设置
        self.active_cwd: str = ""
        if worktree_mgr is not None:
            session = worktree_mgr.current_session
            if session is not None:
                self.active_cwd = session.worktree_path
        # 后台任务通知消费协程（run_async 启动）
        self._consume_task = None
        # 是否在 Agent 运行中（/resume 互斥）
        self._agent_running: bool = False
        # 命令系统
        self.cmd_registry: CmdRegistry | None = None
        self._slash_completer: SlashCompleter | None = None
        self._current_slash_args: str = ""
        # 空闲态 Ctrl+C 计数器（两次退出）
        self._idle_ctrl_c_count: int = 0

        # 构造命令注册中心
        reg = cmd_registry if cmd_registry is not None else CmdRegistry()
        if cmd_registry is None:
            register_builtins(reg)
        # 注册 4 条隐藏命令（全部走注册中心，无遗留分支）
        reg.register(
            CmdCommand(
                name="providers",
                description="列出已配置的供应商",
                kind=CmdKind.LOCAL,
                handler=self._legacy_providers_handler,
                hidden=True,
            )
        )
        reg.register(
            CmdCommand(
                name="mode",
                description="循环切换权限模式",
                kind=CmdKind.LOCAL,
                handler=self._legacy_mode_handler,
                hidden=True,
            )
        )
        reg.register(
            CmdCommand(
                name="switch",
                description="切换到指定供应商",
                kind=CmdKind.LOCAL,
                handler=self._handle_switch,
                hidden=True,
                accepts_args=True,
            )
        )
        reg.register(
            CmdCommand(
                name="thinking",
                description="切换思考展示",
                kind=CmdKind.LOCAL,
                handler=self._handle_thinking,
                hidden=True,
                accepts_args=True,
                argument_completer=lambda prefix: [s for s in ("on", "off") if s.startswith(prefix)],
            )
        )
        self.cmd_registry = reg
        self._slash_completer = SlashCompleter(reg)

    def _get_agent(self) -> Agent:
        """延迟构造 Agent（需要 provider 已选定）。"""
        if self._agent is None:
            self._agent = Agent(
                self.provider,
                self.registry,
                self.engine,
                VERSION,
                runtime=self.runtime,
                memory_manager=self._mem_mgr,
                instruction_text=self._instruction_text,
                memory_text=self._memory_text,
                catalog=self.catalog,
                hook_engine=self.hook_engine,
            )
            # Coordinator Mode：收窄工具集 + 追加纪律提示词（F54）
            if self.coordinator_mode:
                from forgecode.coordinator import allowed_tools, system_prompt_suffix

                self._agent.set_allowed_tools(allowed_tools())
                self._agent.append_system_prompt(system_prompt_suffix())
            # 把 Agent 工具绑定到主 Agent（parent 反推 + 父对话获取）
            agent_tool = self.registry.get("Agent")
            if agent_tool is not None and hasattr(agent_tool, "set_parent"):
                agent_tool.set_parent(self._agent)
                agent_tool.bind_conv_source(lambda: self.conversation)
        return self._agent

    def refresh_memory_text(self) -> None:
        """重新加载记忆索引文本（供记忆更新后刷新注入内容）。"""
        if self._mem_mgr is not None:
            self._memory_text = self._mem_mgr.load_index()
        # 重建 Agent 以使用新的 memory_text
        self._agent = None

    # ── UI Protocol 实现 ────────────────────────────

    def println(self, msg: str) -> None:
        """向用户输出普通消息。"""
        self.console.print(msg)

    def error(self, msg: str) -> None:
        """向用户输出错误消息。"""
        self.console.print(f"[red]{msg}[/red]")

    def get_mode(self) -> Mode:
        """返回当前权限模式。"""
        return self.mode

    def set_mode(self, m: Mode) -> None:
        """设置权限模式。"""
        self.mode = m

    def list_catalog_skills(self) -> list:
        if self.catalog is None:
            return []
        return [
            SkillSummary(
                name=s.meta.name,
                description=s.meta.description,
                source=str(s.source),
                mode=s.meta.mode,
            )
            for s in self.catalog.list()
        ]

    def list_active_skills(self) -> list[str]:
        if self.runtime is None or self.runtime.active_skills is None:
            return []
        return self.runtime.active_skills.names()

    def clear_active_skills(self) -> None:
        if self.runtime is not None and self.runtime.active_skills is not None:
            self.runtime.active_skills.clear()

    # ── Worktree 访问（/worktree 命令）──

    def worktree_accessor(self):
        """返回 WorktreeAdapter；未启用（非 git 仓库）时返回 None。"""
        if self.worktree_mgr is None:
            return None
        from forgecode.tui.worktree_adapter import WorktreeAdapter

        return WorktreeAdapter(self.worktree_mgr, self._set_active_cwd)

    def _set_active_cwd(self, cwd: str) -> None:
        self.active_cwd = cwd

    def _effective_cwd(self) -> str:
        """主 Agent Run 的 ctx cwd：优先 active_cwd，否则进程 cwd。"""
        return self.active_cwd or str(os.getcwd())

    def team_manager(self):
        """返回 Team Manager；未启用时返回 None（/team 命令用）。"""
        return self.team_mgr

    # ── Skill fork 需要（UI Protocol 缺失补齐）──

    async def append_assistant_message(self, text: str) -> None:
        """把 skill fork 结果作为 assistant 消息写回主对话。"""
        self.conversation.add_assistant(text)
        self.console.print(self._render_markdown(text))

    def recent_messages(self, n: int) -> list:
        return self.conversation.messages[-n:]

    def all_messages(self) -> list:
        return self.conversation.messages

    # ── 后台任务通知 ──────────────────────────────

    async def _consume_task_done(self) -> None:
        """消费 task_mgr 的 done 队列，把 <task-notification> 注入 pending_reminders。"""
        if self.task_mgr is None or self.runtime is None:
            return
        from forgecode.tui.tasks import build_task_notification

        q = self.task_mgr.subscribe_done()
        while True:
            task_id = await q.get()
            bt = self.task_mgr.get(task_id)
            if bt is None:
                continue
            notif = build_task_notification(bt)
            self.runtime.append_reminders([notif])

    # ── Lead 邮箱消费与自动唤醒（F41a/F41b）──────────

    async def _consume_lead_mail(self) -> None:
        """每秒轮询 Lead 邮箱，未读消息转 <team-update> reminder + 触发唤醒信号。"""
        if self.team_mgr is None or self.runtime is None:
            return
        from forgecode.tui.tasks import build_team_update_reminder

        while True:
            try:
                await asyncio.sleep(1.0)
                msgs = await self.team_mgr.poll_lead_mailboxes()
                if not msgs:
                    continue
                reminder = build_team_update_reminder(msgs)
                self.runtime.append_reminders([reminder])
                self.lead_mail_event.set()
            except asyncio.CancelledError:
                raise
            except Exception:
                continue

    async def _wait_for_lead_mail(self) -> None:
        """阻塞在 lead_mail_event 上；空闲时自动开新轮处理队员消息。"""
        while True:
            await self.lead_mail_event.wait()
            self.lead_mail_event.clear()
            if not self._agent_running:
                await self._begin_autonomous_turn()

    async def _begin_autonomous_turn(self) -> None:
        """合成 user 消息自动开一轮（Lead 空闲时队员有更新）。"""
        text = "[team-update] 队员发来新消息，请按 Coordinator 流程处理。"
        self.console.print()
        self.console.print(f"[bold cyan]user:[/bold cyan] {text}")
        try:
            await self._submit(text)
        except asyncio.CancelledError:
            pass

    def inject_and_send(self, display_label: str, preset_prompt: str) -> None:
        """向对话注入一条 user 消息并立即触发 Agent 回合。"""
        self.conversation.add_user(preset_prompt)
        self.console.print(f"[dim]{display_label}[/dim]")
        asyncio.create_task(self._submit(preset_prompt))

    def usage_in(self) -> int:
        return self._total_input_tokens

    def usage_out(self) -> int:
        return self._total_output_tokens

    def model_name(self) -> str:
        return self._active_model()

    def cwd(self) -> str:
        return os.getcwd()

    def tool_count(self) -> int:
        return self.registry.count()

    # ── 工具调用日志（/tool 命令折叠展开）──

    def tool_log(self, limit: int = 10) -> list[ToolLogEntry]:
        """返回最近 limit 条工具调用记录（倒序，新在前）。"""
        return list(reversed(self._tool_log[-limit:]))

    def tool_log_detail(self, index: int) -> ToolLogEntry | None:
        """按序号取一条工具调用记录。"""
        for e in self._tool_log:
            if e.index == index:
                return e
        return None

    def tool_log_clear(self) -> None:
        """清空工具调用日志。"""
        self._tool_log.clear()

    def memory_files(self) -> list[str]:
        if self._mem_mgr is None:
            return []
        project, user = self._mem_mgr.list_files()
        return project + user

    def session_path(self) -> str:
        return self._writer.path if self._writer else ""

    def session_id(self) -> str:
        if self.runtime and self.runtime.session:
            return self.runtime.session.session_id
        return ""

    def idle(self) -> bool:
        return not self._agent_running

    def quit(self) -> None:
        self._exit_flag = True

    def force_compact(self) -> None:
        asyncio.create_task(self._handle_compact())

    async def open_resume_menu(self) -> None:
        await self._handle_resume()

    async def clear_and_new_session(self) -> None:
        """关闭当前会话，创建新 SessionContext/Writer/Conversation 并重置状态。"""
        # 派发 SessionEnd（旧会话）
        await self._dispatch_session_end()

        # 关闭旧 writer
        if self._writer is not None:
            try:
                self._writer.close()
            except Exception:
                pass

        # 创建新会话上下文
        from forgecode.compact.state import new_session_context

        workspace = os.getcwd()
        try:
            new_ses_ctx = new_session_context(workspace)
        except Exception as e:
            self.error(f"无法创建新会话: {e}")
            return

        # 打开新 writer
        from forgecode.session.writer import Writer

        try:
            new_writer = Writer(new_ses_ctx.session_dir)
        except OSError as e:
            self.error(f"无法创建新会话文件: {e}")
            return

        self._writer = new_writer

        # 重建 conversation 回调（指向新 writer）
        model_name = self._active_model()
        _first_call = [True]

        def _on_append(msg) -> None:
            new_writer.append(msg, model=model_name, is_first=_first_call[0])
            _first_call[0] = False

        def _on_replace(msgs) -> None:
            new_writer.write_compact_marker()
            new_writer.append_all(msgs)

        self.conversation._on_append = _on_append
        self.conversation._on_replace = _on_replace
        self.conversation.clear()

        # 重置 runtime compact 子状态
        if self.runtime is not None:
            self.runtime.reset_for_new_session(new_ses_ctx)

        # 重置计数
        self._total_input_tokens = 0
        self._total_output_tokens = 0
        self._iter = 0
        self._response_elapsed = 0

        # 派发 SessionStart（新会话）
        await self._dispatch_session_start()

    # ── Hook 查询 ──────────────────────────────────

    def hook_sources(self) -> list[str]:
        """已加载 hook 的来源文件列表。"""
        if self.hook_engine is None:
            return []
        return self.hook_engine.sources

    def hook_rules(self) -> list:
        """已加载的 hook 规则列表。"""
        if self.hook_engine is None:
            return []
        return self.hook_engine.rules

    # ── Hook 会话事件分发 ─────────────────────────

    def _base_payload(self, event: HookEvent) -> dict:
        """构造 hook payload 通用字段。"""
        return {
            "event": event.value,
            "session_id": self.session_id(),
            "cwd": os.getcwd(),
            "mode": self.mode.name.lower(),
        }

    async def _dispatch_hook(self, event: HookEvent, payload: dict) -> DispatchResult:
        """分派 hook 事件；把注入的 prompt 追加到 runtime 的 reminder 队列。"""
        if self.hook_engine is None:
            return DispatchResult()
        result = await self.hook_engine.dispatch(event, payload)
        if result.injected_prompts and self.runtime is not None:
            self.runtime.append_reminders(result.injected_prompts)
        return result

    async def _dispatch_session_start(self) -> None:
        """SessionStart：进程启动 / /clear 新建会话后。"""
        await self._dispatch_hook(HookEvent.SESSION_START, self._base_payload(HookEvent.SESSION_START))

    async def _dispatch_session_end(self) -> None:
        """SessionEnd：进程关闭 / 会话切换离开前。"""
        await self._dispatch_hook(HookEvent.SESSION_END, self._base_payload(HookEvent.SESSION_END))

    async def _dispatch_session_resume(self) -> None:
        """SessionResume：历史会话恢复完成后。"""
        await self._dispatch_hook(HookEvent.SESSION_RESUME, self._base_payload(HookEvent.SESSION_RESUME))

    # ── 遗留命令 handler（hidden=True，仅供 cmd_registry 引用）──

    async def _legacy_providers_handler(self, _ui) -> None:
        """列出已配置的供应商。"""
        lines: list[str] = []
        for p in self.config.providers:
            marker = " *" if p.name == self.config.active_provider_name else "  "
            lines.append(f"{marker} {p.name}  ({p.protocol}/{p.model})")
        self.console.print()
        self.console.print(Panel("\n".join(lines), title="供应商列表", border_style="dim"))
        self.console.print()

    async def _legacy_mode_handler(self, _ui) -> None:
        """循环切换权限模式。"""
        self.mode = Mode((int(self.mode) + 1) % 4)
        self.console.print(f"[dim]已切换到 {self.mode.label()} 模式[/dim]")

    # ── 启动 ───────────────────────────────────────

    def run(self) -> None:
        """同步入口。"""
        asyncio.run(self.run_async())

    def _render_status_text(self) -> str:
        """状态行文本（黑底白字，尾随输入框底部）。"""
        model_name = self._active_model()
        mode_label = self.mode.label()
        it = self._total_input_tokens
        ot = self._total_output_tokens
        tok_str = f"↑{_fmt_tok(it)} ↓{_fmt_tok(ot)}"
        if self._response_elapsed > 0:
            elapsed = f"{self._response_elapsed:.1f}s"
        else:
            elapsed = "..."
        sid = self.session_id()
        sid_str = f"[{sid[:8]}] " if sid else ""
        cwd_str = _shorten_path(self.cwd(), max_len=32)
        mcp_line = self._mcp_summary()
        mcp_str = f" | {mcp_line}" if mcp_line else ""
        coord_str = " | [COORDINATOR]" if self.coordinator_mode else ""
        return (
            f" {sid_str}{mode_label} │ {model_name} │ {cwd_str} │ {tok_str} │ {elapsed} "
            + mcp_str
            + coord_str
            + " "
        )

    def _make_input(self):
        """构造输入读取器：让 Windows 下 Shift+Enter 识别为换行。

        Windows 两种输入模式下 Shift+Enter 与 Enter 默认都无法区分：
        - 经典控制台（ConsoleInputReader）：shift 映射表没有 Enter，都变
          ControlM。按 KEY_EVENT_RECORD 的 VK_RETURN + SHIFT 区分。
        - 虚拟终端模式（Vt100ConsoleInputReader，Windows Terminal）：
          _get_keys 只提取 u_char、丢弃 ControlKeyState。同样按
          VK_RETURN + SHIFT 区分，输出 \n 让 Vt100Parser 解析为 ControlJ。
        """
        if os.name != "nt":
            return None
        try:
            from prompt_toolkit.input.win32 import (
                KEY_EVENT_RECORD,
                ConsoleInputReader,
                EventTypes,
                Vt100ConsoleInputReader,
                Win32Input,
            )
            from prompt_toolkit.key_binding.key_processor import KeyPress
            from prompt_toolkit.keys import Keys

            _shift_pressed = 0x0010
            _vk_return = 0x0D

            class _ClassicShiftEnterReader(ConsoleInputReader):
                """经典模式：Shift+Enter → ControlJ（换行）。"""

                def _event_to_key_presses(self, ev):
                    result = super()._event_to_key_presses(ev)
                    if ev.ControlKeyState & _shift_pressed and ev.VirtualKeyCode == _vk_return:
                        return [KeyPress(Keys.ControlJ, "\n")]
                    return result

            class _VtShiftEnterReader(Vt100ConsoleInputReader):
                """VT 模式：Shift+Enter 的 u_char 由 \\r 改 \\n → ControlJ。"""

                def _get_keys(self, read, input_records):
                    for i in range(read.value):
                        ir = input_records[i]
                        if ir.EventType in EventTypes:
                            ev = getattr(ir.Event, EventTypes[ir.EventType])
                            if isinstance(ev, KEY_EVENT_RECORD) and ev.KeyDown:
                                u_char = ev.uChar.UnicodeChar
                                if (
                                    u_char == "\r"
                                    and ev.ControlKeyState & _shift_pressed
                                    and ev.VirtualKeyCode == _vk_return
                                ):
                                    u_char = "\n"
                                if u_char != "\x00":
                                    yield u_char

            class _ForgeWin32Input(Win32Input):
                def __init__(self):
                    super().__init__()
                    if self._use_virtual_terminal_input:
                        self.console_input_reader = _VtShiftEnterReader()
                    else:
                        self.console_input_reader = _ClassicShiftEnterReader()

            return _ForgeWin32Input()
        except Exception:
            return None

    def _input_accepted(self, buf: Any) -> bool:
        """回车提交：退出输入盒子 Application，返回输入文本。"""
        get_app().exit(result=buf.text)
        return True

    def _build_input_app(self, input: Any = None, output: Any = None) -> Application[str]:
        """输入盒子：上边框 + 输入行 + 下边框 + 状态栏（尾随盒子底部）。

        非全屏，渲染在当前光标处（输出末尾），随输入文本换行而扩大。
        input/output 供测试注入 pipe/Dummy，默认用系统输入。
        """
        top = Window(
            FormattedTextControl(self._border_text),
            height=1,
            style="class:input-border",
            always_hide_cursor=True,
        )
        bottom = Window(
            FormattedTextControl(self._border_text),
            height=1,
            style="class:input-border",
            always_hide_cursor=True,
        )
        status = Window(
            FormattedTextControl(self._render_status_text),
            height=1,
            style="class:status",
            always_hide_cursor=True,
        )
        self._input_textarea = TextArea(
            multiline=True,
            wrap_lines=True,
            dont_extend_height=True,
            completer=self._slash_completer,
            complete_while_typing=True,
            accept_handler=self._input_accepted,
            style="class:input",
            height=Dimension(min=1),
            prompt="> ",
        )
        # CompletionsMenu 作为 float 挂到光标处：complete_while_typing 产生的候选
        # 才有渲染载体（否则菜单从未显示）
        container = FloatContainer(
            HSplit([top, self._input_textarea, bottom, status]),
            floats=[Float(xcursor=True, ycursor=True, content=CompletionsMenu())],
        )

        # 显式 key_bindings：
        #   Tab → 补全弹出 / 导航
        #   Shift-Tab → 循环切换权限模式
        #   Esc → 关闭补全菜单
        #   Ctrl+C → 抛 KeyboardInterrupt
        #   Enter → 提交（multiline 下默认 Enter 是换行，需显式覆盖）
        #   Ctrl+J / Shift+Enter → 换行（\n 在多数终端是 Shift+Enter 产生的序列）
        kb = KeyBindings()

        @kb.add("enter")
        def _on_enter(event: KeyPressEvent) -> None:
            # multiline 模式下 Enter 默认插入换行，这里改为提交
            event.current_buffer.validate_and_handle()

        @kb.add("c-j")
        def _on_newline(event: KeyPressEvent) -> None:
            # \n = Ctrl+J；Shift+Enter 在多数终端发送 \n，视为换行
            event.current_buffer.newline()

        @kb.add("tab")
        def _on_tab(event: KeyPressEvent) -> None:
            buf = event.app.current_buffer
            if buf.complete_state:
                buf.complete_next()
            else:
                buf.start_completion(select_first=False)

        @kb.add("s-tab")
        def _on_stab(event: KeyPressEvent) -> None:
            """Shift-Tab：循环切换权限模式（同 /permission）。"""
            self.mode = Mode((int(self.mode) + 1) % 4)
            # 更新状态栏以反映新模式
            event.app.invalidate()

        @kb.add("escape")
        def _on_esc(event: KeyPressEvent) -> None:
            buf = event.app.current_buffer
            if buf.complete_state:
                buf.cancel_completion()

        @kb.add("c-c")
        def _on_ctrl_c(event: KeyPressEvent) -> None:
            self._ctrl_c_handler(event)

        return Application(
            layout=Layout(container, focused_element=self._input_textarea),
            style=PROMPT_STYLE,
            full_screen=False,
            mouse_support=False,
            min_redraw_interval=0.05,
            key_bindings=kb,
            input=input if input is not None else self._make_input(),
            output=output,
        )

    def _ctrl_c_handler(self, event: KeyPressEvent) -> None:
        """Ctrl+C：Agent 运行中取消本轮；空闲态第一次提示、第二次退出。"""
        if self._agent_running:
            if self._turn_cancel is not None and not self._turn_cancel.is_set():
                self._turn_cancel.set()
            self.console.print()
            self.console.print("[dim]正在取消...[/dim]")
            return
        self._idle_ctrl_c_count += 1
        if self._idle_ctrl_c_count >= 2:
            event.app.exit(exception=KeyboardInterrupt())
            return
        self.console.print()
        self.console.print(f"[dim]{EXIT_HINT}[/dim]")

    def _border_text(self) -> str:
        """输入盒边框：每次渲染惰性取当前终端宽度（resize 自适应，无需回调）。"""
        try:
            self._width = shutil.get_terminal_size().columns
        except Exception:
            pass  # 无法获取尺寸时沿用上次宽度
        return "─" * max(self._width, 1)

    async def run_async(self) -> None:
        """非全屏主循环：输出终端原生滚动，输入框盒子 + 状态栏尾随输出末尾。"""
        self._render_banner()
        await self._dispatch_session_start()
        if self.task_mgr is not None:
            self._consume_task = asyncio.create_task(self._consume_task_done())
        if self.team_mgr is not None:
            self._consume_lead = asyncio.create_task(self._consume_lead_mail())
            self._lead_wait = asyncio.create_task(self._wait_for_lead_mail())

        input_app = self._build_input_app()

        while not self._exit_flag:
            try:
                user_input = await input_app.run_async()
                self._input_textarea.buffer.reset()
            except KeyboardInterrupt:
                # 区分逻辑已全部在 c-c 绑定内处理（流式取消 / 空闲提示+二次退出）。
                # 能到这里说明第二次空闲 Ctrl+C 或流式态取消已确认，直接退出。
                self.console.print()
                self.console.print("[dim]再见！[/dim]")
                self._exit_flag = True
                continue
            except EOFError:
                self.console.print()
                self.console.print("再见！")
                break

            user_input = (user_input or "").strip()
            if not user_input:
                continue
            self._idle_ctrl_c_count = 0  # 正常输入 → 重置 Ctrl+C 计数器

            if await self.dispatch_slash(user_input):
                continue
            try:
                await self._submit(user_input)
            except asyncio.CancelledError:
                self.console.print()
                self.console.print("[dim]已中断[/dim]")
            except KeyboardInterrupt:
                if self._turn_cancel is not None and not self._turn_cancel.is_set():
                    self._turn_cancel.set()
                self.console.print()
                self.console.print("[dim]正在取消...[/dim]")

        await self._dispatch_session_end()
        if self._consume_task is not None:
            self._consume_task.cancel()
        if self._consume_lead is not None:
            self._consume_lead.cancel()
        if self._lead_wait is not None:
            self._lead_wait.cancel()

    # ── 命令分发 ──────────────────────────────────

    async def dispatch_slash(self, text: str) -> bool:
        """基于注册中心的命令分发。返回 True 表示已处理为命令。"""
        name, is_slash = parse_command(text)
        if not is_slash:
            return False

        # 空 name（纯 "/" 或无效输入）→ 未命中提示
        if not name:
            self.console.print("[yellow]未知命令。输入 /help 查看可用命令。[/yellow]")
            return True

        assert self.cmd_registry is not None
        cmd = self.cmd_registry.lookup(name)
        if cmd is None:
            self.console.print(f"[yellow]未知命令: /{name}。输入 /help 查看可用命令。[/yellow]")
            return True

        # 提取尾随 args
        stripped = text.strip()
        parts = stripped.split(maxsplit=1)
        raw_args = parts[1].strip() if len(parts) > 1 else ""

        # 不接受参数的命令收到参数 → 未命中
        if raw_args and not cmd.accepts_args:
            self.console.print(f"[yellow]未知命令: /{name}。输入 /help 查看可用命令。[/yellow]")
            return True

        # Idle 守卫：Kind.UI 和 Kind.PROMPT 命令仅在空闲时可执行
        if cmd.kind in (CmdKind.UI, CmdKind.PROMPT) and not self.idle():
            self.console.print("[yellow]请等待当前任务完成后再使用此命令。[/yellow]")
            return True

        # 注入 args 供 handler 读取
        if cmd.accepts_args:
            self._current_slash_args = raw_args

        try:
            await cmd.handler(self)
        except Exception as exc:
            self.console.print(f"[red]命令执行失败: {exc}[/red]")
        finally:
            if cmd.accepts_args:
                self._current_slash_args = ""

        return True

    # ── 带参数命令的 handler ──────────────────────────

    async def _handle_switch(self, _ui) -> None:
        """切换到指定供应商（/switch <name>）。"""
        args = getattr(self, "_current_slash_args", "")
        if not args:
            self.console.print("[yellow]用法: /switch <名称>[/yellow]")
            return
        name = args.strip()
        matching = [p for p in self.config.providers if p.name == name]
        if not matching:
            self.console.print(f"[red]未找到供应商 '{name}'[/red]")
            return
        new_config = matching[0]
        self.provider = create_provider(new_config)
        self.config.active_provider_name = new_config.name
        self._agent = None
        if self.runtime is not None:
            from forgecode.config.schema import effective_context_window

            self.runtime.context_window = effective_context_window(new_config)
        if self._mem_mgr is not None:
            self._mem_mgr.set_provider(self.provider, new_config.model)
            self._memory_text = self._mem_mgr.load_index()
        self.console.print(f"[green]已切换到 {new_config.name} ({new_config.model})[/green]")

    async def _handle_thinking(self, _ui) -> None:
        """切换思考展示（/thinking on|off）。"""
        args = getattr(self, "_current_slash_args", "")
        arg = args.strip().lower()
        if arg == "on":
            self._show_thinking = True
            self.console.print("[green]思考展示已开启[/green]")
        elif arg == "off":
            self._show_thinking = False
            self.console.print("[yellow]思考展示已关闭[/yellow]")
        else:
            self.console.print("[yellow]用法: /thinking on|off[/yellow]")

    async def _handle_compact(self) -> None:
        """手动 /compact：跳过阈值、无条件触发一次 LLM 摘要。"""
        agent = self._get_agent()
        defs = (
            self.registry.read_only_definitions() if self.mode == Mode.PLAN else self.registry.definitions()
        )
        self.console.print("[dim]正在压缩上下文...[/dim]")
        try:
            before, after = await agent.run_force_compact(self.conversation, defs, self.mode)
            self.console.print(f"[dim]已压缩，token 从 {before} 降至 {after}[/dim]")
        except Exception as e:
            self.console.print(f"[red]压缩失败: {e}[/red]")

    async def _handle_resume(self) -> None:
        """处理 /resume 命令：方向键选择会话恢复（↑/↓ 选择，←/→ 翻页）。

        注意：idle 守卫已在 dispatch_slash 按 Kind 统一处理。
        """
        if not self._sessions_dir:
            self.console.print("[yellow]会话目录未初始化，无法恢复[/yellow]")
            return

        from forgecode.session import list_sessions
        from forgecode.tui.choices import ChoiceOption, ask_choice
        from forgecode.tui.resume import do_resume_session, plain_session_item

        sessions = list_sessions(self._sessions_dir)

        if not sessions:
            self.console.print("[dim]没有可恢复的历史会话[/dim]")
            return

        result = await ask_choice(
            title="📋 历史会话列表",
            subtitle=f"共 {len(sessions)} 个会话",
            options=[ChoiceOption(str(i), plain_session_item(info)) for i, info in enumerate(sessions)],
            page_size=10,
        )
        if result.cancelled:
            self.console.print("[dim]已取消[/dim]")
            return

        selected = sessions[int(result.values[0])]
        self.console.print(f"[dim]正在恢复会话 {selected.id}...[/dim]")

        # 派发 SessionEnd（旧会话）
        await self._dispatch_session_end()

        try:
            msg = await do_resume_session(self, selected)
        except Exception as e:
            self.console.print(f"[red]恢复失败: {e}[/red]")
            return

        if msg.startswith("已恢复"):
            # 恢复完成后派发 SessionResume（新会话）
            await self._dispatch_session_resume()
        self.console.print(f"[green]{msg}[/green]")

    # ── 提交消息 ──────────────────────────────────

    async def _submit(self, text: str) -> None:
        """用户提交消息 → Agent 接管。"""
        # /do 场景下文本已由命令处理器加入
        if text != EXECUTE_DIRECTIVE:
            # UserPromptSubmit hook：可拦截用户输入
            result = await self._dispatch_hook(
                HookEvent.USER_PROMPT_SUBMIT,
                {**self._base_payload(HookEvent.USER_PROMPT_SUBMIT), "prompt": text},
            )
            if result.blocked:
                self.console.print(f"[red][hook {result.blocking_hook_name}] {result.reason}[/red]")
                return  # 不消费输入
            self.conversation.add_user(text)

        # 开始计时 + 创建取消事件
        self._response_start = time.time()
        self._response_elapsed = 0
        self._turn_cancel = asyncio.Event()
        self._iter = 0
        self._agent_running = True
        self._turn_live = None
        self._last_md_len = 0
        self._last_md_at = 0.0

        self.console.print()
        self.console.print(f"[bold cyan]user:[/bold cyan] {text}")
        self.console.print("[dim]Thinking...[/dim]")

        # 获取持久 Agent 实例
        agent = self._get_agent()
        cur_text = ""
        in_thinking = False
        thinking_shown_header = False

        # 主 Agent Run 前注入 ctx cwd（active_cwd 为空 = 进程 cwd）
        cwd_cm = with_cwd(self._effective_cwd())
        cwd_cm.__enter__()
        try:
            async for ev in agent.run(self.conversation, self.mode, self._turn_cancel):
                # ── 压缩生命周期事件（优先处理）──
                if ev.compact is not None:
                    in_thinking = False
                    notice = _format_compact_notice(ev.compact)
                    if notice:
                        self.console.print()
                        self.console.print(f"[dim]{notice}[/dim]")
                    continue

                if ev.thinking:
                    if not in_thinking:
                        in_thinking = True
                    if self._show_thinking:
                        if not thinking_shown_header:
                            self.console.print("[dim]Thinking:[/dim]")
                            thinking_shown_header = True
                        self._stream_text(ev.thinking)
                    elif not thinking_shown_header:
                        self.console.print("[dim]（/thinking on 可展开思考过程）[/dim]")
                        thinking_shown_header = True

                elif ev.text:
                    if in_thinking:
                        in_thinking = False
                        if self._show_thinking:
                            self.console.print()
                    # 流式打字（Live 区域原地刷新，结束后渲染覆盖，不产生重复文本）
                    cur_text += ev.text
                    self._live_update(cur_text)

                elif ev.usage is not None:
                    self._total_input_tokens += ev.usage.input_tokens
                    self._total_output_tokens += ev.usage.output_tokens

                elif ev.approval is not None:
                    # 人在回路：先固化正文渲染，再展示待批准选择题
                    self._finalize_live(cur_text)
                    await self._handle_approval(ev.approval)

                elif ev.tool is not None:
                    in_thinking = False
                    thinking_shown_header = False
                    self._finalize_live(cur_text)
                    cur_text = ""

                    if ev.tool.phase == Phase.START:
                        self._render_tool_start(ev.tool)

                    elif ev.tool.phase == Phase.END:
                        self._render_tool_end(ev.tool)

                elif ev.iter > 0:
                    # 轮次变化时输出阶段提示（ev.iter 每轮递增一次）
                    if ev.iter != self._iter:
                        self._iter = ev.iter
                        self.console.print(f"[dim]▶ 第{ev.iter}轮[/dim]")

                elif ev.notice:
                    self._finalize_live(cur_text)
                    self.console.print()
                    self.console.print(f"[dim]{ev.notice}[/dim]")

                elif ev.done:
                    self._response_elapsed = time.time() - self._response_start
                    self._finalize_live(cur_text)

                elif ev.err:
                    self._finalize_live(cur_text)
                    self.console.print(f"[red]✕ {ev.err}[/red]")

        except asyncio.CancelledError:
            self.console.print()
            self.console.print("[dim]已中断[/dim]")
        except KeyboardInterrupt:
            # 流式态 Ctrl+C：取消本轮（run_async 的 except 处理空闲态）
            if self._turn_cancel is not None and not self._turn_cancel.is_set():
                self._turn_cancel.set()
            self.console.print()
            self.console.print("[dim]正在取消...[/dim]")
        except Exception as e:
            self.console.print(f"[red]✕ 对话出错: {e}[/red]")
        finally:
            cwd_cm.__exit__(None, None, None)
            # 无论正常/异常/取消，完整清理——残留的 agent_running/turn_cancel
            # 会导致后续 Ctrl+C 误判为流式态
            self._agent_running = False
            self._turn_cancel = None
            self._finalize_live(cur_text)
            self.console.print()

    # ── 人在回路 ──────────────────────────────────

    async def _handle_approval(self, req: ApprovalRequest) -> None:
        """展示待批准选择题，等待用户方向键选择（单选）。"""
        self.console.print("\n")
        from forgecode.tui.choices import ChoiceOption, ask_choice

        result = await ask_choice(
            title=f"● {req.name}({req.args})",
            subtitle=f"原因：{req.reason}",
            options=[
                ChoiceOption("allow_once", "允许本次"),
                ChoiceOption("allow_forever", "永久允许（写入本地配置）"),
                ChoiceOption("deny_once", "拒绝本次"),
            ],
        )

        if result.cancelled:
            req.respond.set_result(Outcome.DENY_ONCE)
            self.console.print("[dim]已取消[/dim]")
            return
        value = result.values[0]
        if value == "allow_once":
            req.respond.set_result(Outcome.ALLOW_ONCE)
            self.console.print("[dim]允许本次[/dim]")
        elif value == "allow_forever":
            req.respond.set_result(Outcome.ALLOW_FOREVER)
            self.console.print("[dim]永久允许（已写入本地配置）[/dim]")
        else:
            req.respond.set_result(Outcome.DENY_ONCE)
            self.console.print("[dim]拒绝本次[/dim]")

    # ── 工具行渲染（默认折叠，/tool 展开）──────────

    def _render_tool_start(self, tool: ToolEvent) -> None:
        """渲染工具调用开始行：● name(args)。"""
        self._tool_start_ts[tool.name] = time.monotonic()
        self._tool_pending_args[tool.name] = tool.args
        self.console.print()
        self.console.print(f"[bold cyan]●[/bold cyan] [bold]{tool.name}[/bold]({tool.args})")

    def _render_tool_end(self, tool: ToolEvent) -> None:
        """渲染工具结果折叠行：首行摘要 + 耗时 + 展开提示（/tool <序号>）。"""
        start_ts = self._tool_start_ts.get(tool.name)
        elapsed = time.monotonic() - start_ts if start_ts is not None else 0.0
        self._tool_seq += 1
        entry = ToolLogEntry(
            index=self._tool_seq,
            name=tool.name,
            args=self._tool_pending_args.get(tool.name, ""),
            result=tool.result,
            is_error=tool.is_error,
            elapsed=elapsed,
        )
        self._tool_log.append(entry)
        if len(self._tool_log) > _TOOL_LOG_LIMIT:
            del self._tool_log[: len(self._tool_log) - _TOOL_LOG_LIMIT]

        style = "red" if tool.is_error else "dim"
        first = (tool.result.split("\n")[0] if tool.result else "")[:_TOOL_LINE_PREVIEW]
        tail = f"· {elapsed:.1f}s · /tool {entry.index} 展开"
        self.console.print(f"  [dim]⎿[/dim] [{style}]{first}[/{style}]  [dim]{tail}[/dim]")

    # ── 流式输出 ──────────────────────────────────

    @staticmethod
    def _stream_text(text: str) -> None:
        sys.stdout.write(text)
        sys.stdout.flush()

    @staticmethod
    def _render_markdown(text: str) -> Markdown:
        """统一的 Markdown 渲染：显式启用 pygments 语法高亮。

        已安装 pygments，代码块默认高亮。code_theme 可换：
        monokai / solarized-dark / vim / gruvbox-dark 等。
        """
        return Markdown(text, code_theme="monokai", hyperlinks=True)

    # ── 正文区 Live 覆盖 ──────────────────────────

    def _live_update(self, text: str) -> None:
        """把流式正文更新到 Live 区域（原地刷新，不产生重复文本）。

        流式期间即用 Markdown 渲染（带节流与未闭合代码块兜底），
        避免结束时突然从纯文本跳变为排版。
        """
        if self._turn_live is None:
            self._turn_live = Live(
                console=self.console,
                refresh_per_second=15,
                transient=False,
            )
            self._turn_live.start()
        if self._md_render_due(len(text)):
            self._turn_live.update(self._render_markdown(_prepare_markdown_render(text)))
        else:
            self._turn_live.update(Text(text))

    def _md_render_due(self, text_len: int) -> bool:
        """节流判定：增量足够大或距上次渲染足够久时重渲染 Markdown。"""
        now = time.monotonic()
        if text_len - self._last_md_len >= _MD_RENDER_CHUNK or now - self._last_md_at >= _MD_RENDER_INTERVAL:
            self._last_md_len = text_len
            self._last_md_at = now
            return True
        return False

    def _finalize_live(self, cur_text: str) -> None:
        """结束正文区：用 Markdown 渲染原地替换流式源码并固定到屏幕。

        非 transient 模式，stop 时 Live 内容保留在屏幕上，
        因此最终只有一份渲染后的文本。
        """
        live = self._turn_live
        self._turn_live = None
        if live is None:
            return
        try:
            if cur_text.strip():
                live.update(self._render_markdown(cur_text))
            live.stop()
        except Exception:
            if cur_text.strip():
                self.console.print(self._render_markdown(cur_text))

    # ── 渲染 ──────────────────────────────────────

    def _render_banner(self) -> None:
        cwd = os.getcwd()
        home = os.path.expanduser("~")
        if cwd.startswith(home):
            cwd = "~" + cwd[len(home) :]

        self.console.print()
        self.console.print(f"[bold]{FORGECODE_ART}[/bold]")
        self.console.print(f"  [bold]⚒[/bold]   [bold]ForgeCode[/bold] [dim]v{VERSION}[/dim]    {cwd}")

        # MCP 连接状态（移至底部状态栏）
        # mcp_line = self._mcp_summary()
        # if mcp_line:
        #     self.console.print(f'  [dim]{mcp_line}[/dim]')

        self.console.print()
        self.console.print("[dim]就绪 - 输入消息开始对话，/help 查看命令[/dim]")

    def _mcp_summary(self) -> str:
        """统计 registry 中 mcp__ 前缀的工具，返回一行摘要。"""
        servers: set[str] = set()
        tool_count = 0
        for tdef in self.registry.definitions():
            if tdef.name.startswith("mcp__"):
                tool_count += 1
                # mcp__<server>__<tool> → 取 server 名
                parts = tdef.name.split("__", 2)
                if len(parts) >= 2:
                    servers.add(parts[1])
        if not servers:
            return ""
        return f"Connected to {len(servers)} MCP server(s), {tool_count} tool(s) registered"

    def _active_model(self) -> str:
        for p in self.config.providers:
            if p.name == self.config.active_provider_name:
                return p.model
        return "?"


# ── 压缩事件格式化 ─────────────────────────────────


def _format_compact_notice(ev: CompactEvent) -> str:
    """按 phase 返回统一的压缩提示文案。"""
    if ev.phase == CompactPhase.BEFORE_AUTO:
        return "正在压缩上下文..."
    elif ev.phase == CompactPhase.BEFORE_EMERGENCY:
        return "上下文撞墙，自动压缩中..."
    elif ev.phase in (CompactPhase.AFTER_AUTO, CompactPhase.AFTER_EMERGENCY):
        if ev.err is not None:
            return f"压缩失败：{ev.err}"
        return f"已压缩，token 从 {ev.before} 降至 {ev.after}"
    return ""


# ── 辅助 ──────────────────────────────────────────


def _fmt_tok(n: int) -> str:
    """格式化 token 数为可读形式。"""
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)


def _shorten_path(path: str, max_len: int = 32) -> str:
    """缩写路径：home 用 ~ 替换；过长时保留头尾。"""
    home = os.path.expanduser("~")
    if path.startswith(home):
        path = "~" + path[len(home) :]
    if len(path) <= max_len:
        return path
    head_len = max_len // 2 - 1
    tail_len = max_len - head_len - 3
    return path[:head_len] + "..." + path[-tail_len:]


# ── 流式 Markdown 渲染节流 ────────────────────────

_MD_RENDER_CHUNK: int = 512  # 增量超过该字符数才重渲染 Markdown
_MD_RENDER_INTERVAL: float = 0.3  # 距上次渲染超过该秒数才重渲染

# ── 工具调用日志（/tool）──

_TOOL_LOG_LIMIT: int = 200  # 日志条数上限（超出丢弃最旧）
_TOOL_LINE_PREVIEW: int = 120  # 折叠行结果首行预览长度


def _prepare_markdown_render(text: str) -> str:
    """未闭合 ``` 代码块截断：只渲染已闭合部分，避免渲染器把后续内容吞进代码块。

    返回的字符串在闭合后自然恢复完整渲染；空串表示当前没有可渲染的闭合内容。
    """
    if text.count("```") % 2 == 0:
        return text
    pos = text.rfind("```")
    return text[:pos]
