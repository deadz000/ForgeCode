"""TUI 主应用：终端界面渲染、输入处理、命令分发、Agent 集成。"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from typing import Any

from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.shortcuts import prompt as pt_prompt
from prompt_toolkit.styles import Style
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from rich.text import Text

from forgecode.agent import Agent, ApprovalRequest, CompactEvent, CompactPhase, Phase, ToolEvent
from forgecode.command import Kind as CmdKind
from forgecode.command import Registry as CmdRegistry
from forgecode.command import parse as parse_command
from forgecode.command import register_builtins
from forgecode.command.command import Command as CmdCommand
from forgecode.config.schema import AppConfig
from forgecode.conversation.history import Conversation
from forgecode.permission import Mode, Outcome
from forgecode.permission.engine import Engine
from forgecode.prompt import EXECUTE_DIRECTIVE
from forgecode.providers import BaseProvider, create_provider
from forgecode.tool import Registry
from forgecode.tui.complete import SlashCompleter

# ── ASCII 小狗 ────────────────────────────────────

ASCII_DOG = r"""
   /\___/\
  (  o o  )
  (  =^=  )
   (______)"""

VERSION = "0.2.0"

# ── prompt_toolkit 样式 ───────────────────────────

PROMPT_STYLE = Style.from_dict(
    {
        "prompt": "bold #00ff87",
        "placeholder": "#555555",
        "bottom-toolbar": "bg:#1a1a2e #888888",
        "bottom-toolbar.text": "bg:#1a1a2e #cccccc",
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
    ) -> None:
        self.config = config
        self.provider = provider
        self.conversation = conversation
        self.registry = registry
        self.engine = engine
        self.runtime = runtime
        self.console = Console()
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
        # 是否在 Agent 运行中（/resume 互斥）
        self._agent_running: bool = False
        # 命令系统
        self.cmd_registry: CmdRegistry | None = None
        self._slash_completer: SlashCompleter | None = None
        self._current_slash_args: str = ""

        # 构造命令注册中心
        reg = CmdRegistry()
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
            )
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

    def clear_and_new_session(self) -> None:
        """关闭当前会话，创建新 SessionContext/Writer/Conversation 并重置状态。"""
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

    async def run_async(self) -> None:
        """异步主循环。"""
        self._render_banner()

        history = InMemoryHistory()
        session: PromptSession[str] = PromptSession(
            history=history,
            style=PROMPT_STYLE,
            completer=self._slash_completer,
            complete_while_typing=True,
        )

        while not self._exit_flag:
            self.console.print(Rule(style="dim"))

            try:
                user_input = await session.prompt_async(
                    message=[("class:prompt", "❯ ")],
                    placeholder="Send a message...",
                    bottom_toolbar=self._status_bar,
                )
            except KeyboardInterrupt:
                # 流式态 → 取消本轮；空闲态 → 退出
                if self._turn_cancel is not None and not self._turn_cancel.is_set():
                    self._turn_cancel.set()
                    self.console.print()
                    self.console.print("[dim]正在取消...[/dim]")
                    continue
                self.console.print()
                self._exit_flag = True
                continue
            except EOFError:
                self.console.print()
                self.console.print("再见！")
                break

            user_input = user_input.strip()
            if not user_input:
                continue

            if await self.dispatch_slash(user_input):
                continue
            try:
                await self._submit(user_input)
            except asyncio.CancelledError:
                    self.console.print()
                    self.console.print("[dim]已中断[/dim]")

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
            before, after = await agent.run_force_compact(self.conversation, defs)
            self.console.print(f"[dim]已压缩，token 从 {before} 降至 {after}[/dim]")
        except Exception as e:
            self.console.print(f"[red]压缩失败: {e}[/red]")

    async def _handle_resume(self) -> None:
        """处理 /resume 命令：显示会话列表 + 选择恢复。

        注意：idle 守卫已在 dispatch_slash 按 Kind 统一处理。
        """
        if not self._sessions_dir:
            self.console.print("[yellow]会话目录未初始化，无法恢复[/yellow]")
            return

        from forgecode.session import list_sessions
        from forgecode.tui.resume import do_resume_session, format_session_item

        sessions = list_sessions(self._sessions_dir)

        if not sessions:
            self.console.print("[dim]没有可恢复的历史会话[/dim]")
            return

        # 显示会话列表
        self.console.print()
        self.console.print("[bold]📋 历史会话列表[/bold]")
        self.console.print(f"[dim]共 {len(sessions)} 个会话，输入序号恢复，Esc 取消[/dim]")
        self.console.print()

        for i, info in enumerate(sessions, 1):
            self.console.print(format_session_item(info, i))

        self.console.print()

        # 等待用户选择（prompt_toolkit prompt 支持 ESC 立即取消）
        def _read_choice() -> str:
            kb = KeyBindings()

            @kb.add("escape")
            def _on_esc(event: object) -> None:
                event.app.exit(result="__ESC__")  # type: ignore[union-attr]

            @kb.add("enter")
            def _on_enter(event: object) -> None:
                event.app.exit(result=event.app.current_buffer.text)  # type: ignore[union-attr]

            try:
                return pt_prompt(
                    "  选择序号（Esc 取消）: ",
                    key_bindings=kb,
                ).strip()
            except (EOFError, KeyboardInterrupt):
                return "__ESC__"

        try:
            choice = await asyncio.get_running_loop().run_in_executor(None, _read_choice)
        except (EOFError, KeyboardInterrupt):
            self.console.print("[dim]已取消[/dim]")
            return

        if not choice or choice == "__ESC__":
            self.console.print("[dim]已取消[/dim]")
            return

        try:
            idx = int(choice) - 1
            if idx < 0 or idx >= len(sessions):
                self.console.print("[red]无效的序号[/red]")
                return
        except ValueError:
            self.console.print("[red]请输入数字序号[/red]")
            return

        selected = sessions[idx]
        self.console.print(f"[dim]正在恢复会话 {selected.id}...[/dim]")

        try:
            msg = await do_resume_session(self, selected)
            self.console.print(f"[green]{msg}[/green]")
        except Exception as e:
            self.console.print(f"[red]恢复失败: {e}[/red]")

    # ── 提交消息 ──────────────────────────────────

    async def _submit(self, text: str) -> None:
        """用户提交消息 → Agent 接管。"""
        # /do 场景下文本已由命令处理器加入
        if text != EXECUTE_DIRECTIVE:
            self.conversation.add_user(text)

        # 开始计时 + 创建取消事件
        self._response_start = time.time()
        self._response_elapsed = 0
        self._turn_cancel = asyncio.Event()
        self._iter = 0
        self._agent_running = True

        self.console.print()
        self.console.print(f"[bold cyan]👤 你:[/bold cyan] {text}")

        # 启动实时计时器
        timer_task = asyncio.create_task(self._show_imagining())

        # 获取持久 Agent 实例
        agent = self._get_agent()
        cur_text = ""
        in_thinking = False
        thinking_shown_header = False
        first_content = False

        try:
            async for ev in agent.run(self.conversation, self.mode, self._turn_cancel):
                # ── 压缩生命周期事件（优先处理）──
                if ev.compact is not None:
                    self._on_first_content(timer_task, first_content)
                    first_content = True
                    in_thinking = False
                    notice = _format_compact_notice(ev.compact)
                    if notice:
                        self.console.print()
                        self.console.print(f"[dim]{notice}[/dim]")
                    continue

                if ev.thinking:
                    self._on_first_content(timer_task, first_content)
                    first_content = True
                    if not in_thinking:
                        in_thinking = True
                    if self._show_thinking:
                        if not thinking_shown_header:
                            self.console.print("[dim]💭 思考过程:[/dim]")
                            thinking_shown_header = True
                        self._stream_text(ev.thinking)
                    elif not thinking_shown_header:
                        self.console.print("[dim]💭 思考中...（/thinking on 展开）[/dim]")
                        thinking_shown_header = True

                elif ev.text:
                    self._on_first_content(timer_task, first_content)
                    first_content = True
                    if in_thinking:
                        in_thinking = False
                        if self._show_thinking:
                            self.console.print()
                    # 流式打字 + 累积（done 时追加 Markdown 渲染）
                    cur_text += ev.text
                    self._stream_text(ev.text)

                elif ev.usage is not None:
                    self._total_input_tokens += ev.usage.input_tokens
                    self._total_output_tokens += ev.usage.output_tokens

                elif ev.approval is not None:
                    # 人在回路：展示待批准块，等待用户选择
                    await self._handle_approval(ev.approval, timer_task)

                elif ev.tool is not None:
                    self._on_first_content(timer_task, first_content)
                    first_content = True
                    in_thinking = False
                    thinking_shown_header = False
                    if cur_text.strip():
                        self.console.print()
                        cur_text = ""

                    if ev.tool.phase == Phase.START:
                        self._render_tool_start(ev.tool)

                    elif ev.tool.phase == Phase.END:
                        self._render_tool_end(ev.tool)

                elif ev.iter > 0:
                    self._iter = ev.iter

                elif ev.notice:
                    self.console.print()
                    self.console.print(f"[dim]{ev.notice}[/dim]")

                elif ev.done:
                    self._on_first_content(timer_task, first_content)
                    self._response_elapsed = time.time() - self._response_start
                    if cur_text.strip():
                        self.console.print()
                        self.console.print(Markdown(cur_text))

                elif ev.err:
                    self._on_first_content(timer_task, first_content)
                    if cur_text.strip():
                        self.console.print()
                    self.console.print(f"[red]✕ {ev.err}[/red]")

        except asyncio.CancelledError:
            timer_task.cancel()
            if cur_text.strip():
                self.console.print(cur_text)
            self.console.print()
            self.console.print("[dim]已中断[/dim]")
        except Exception as e:
            timer_task.cancel()
            if cur_text.strip():
                self.console.print(cur_text)
            self.console.print(f"[red]✕ 对话出错: {e}[/red]")

        timer_task.cancel()
        self._agent_running = False
        self.console.print()

    # ── 响应计时器 ────────────────────────────────

    async def _show_imagining(self) -> None:
        """实时显示 'Imagining… (Ns)'，秒数递增。"""
        sys.stdout.write("\n🤖 Imagining… (0s)")
        sys.stdout.flush()
        try:
            while True:
                await asyncio.sleep(0.1)
                elapsed = time.time() - self._response_start
                iter_str = f" · 第{self._iter}轮" if self._iter > 0 else ""
                sys.stdout.write(f"\r🤖 Imagining… ({elapsed:.0f}s{iter_str})")
                sys.stdout.flush()
        except asyncio.CancelledError:
            pass

    @staticmethod
    def _on_first_content(timer_task: asyncio.Task, first: bool) -> None:
        """首次收到内容时取消计时器，结束 \\r 状态行。"""
        if not first:
            timer_task.cancel()
            # 换行结束 Imagining 行，后续内容正常输出
            sys.stdout.write("\n")
            sys.stdout.flush()

    # ── 人在回路 ──────────────────────────────────

    async def _handle_approval(self, req: ApprovalRequest, timer_task: asyncio.Task) -> None:
        """展示待批准块，等待用户三选一。"""
        timer_task.cancel()
        self.console.print("\n")
        self.console.print(
            Panel(
                Text(
                    f"● {req.name}({req.args})\n"
                    f"  原因：{req.reason}\n\n"
                    f"  1. 允许本次\n"
                    f"  2. 永久允许（写入本地配置）\n"
                    f"  3. 拒绝本次\n"
                ),
                title="权限确认",
                border_style="yellow",
            )
        )

        # 等待用户选择
        while True:
            try:
                choice = await asyncio.get_running_loop().run_in_executor(
                    None, lambda: input("  选择 [1/2/3]（默认 1）：").strip()
                )
            except (EOFError, KeyboardInterrupt):
                req.respond.set_result(Outcome.DENY_ONCE)
                self.console.print("[dim]已取消[/dim]")
                return

            if choice == "1" or choice == "":
                req.respond.set_result(Outcome.ALLOW_ONCE)
                self.console.print("[dim]允许本次[/dim]")
                return
            elif choice == "2":
                req.respond.set_result(Outcome.ALLOW_FOREVER)
                self.console.print("[dim]永久允许（已写入本地配置）[/dim]")
                return
            elif choice == "3":
                req.respond.set_result(Outcome.DENY_ONCE)
                self.console.print("[dim]拒绝本次[/dim]")
                return

    # ── 工具行渲染 ────────────────────────────────

    def _render_tool_start(self, tool: ToolEvent) -> None:
        """渲染工具调用开始行：● name(args)。"""
        self.console.print()
        self.console.print(f"[bold cyan]●[/bold cyan] [bold]{tool.name}[/bold]({tool.args})")

    def _render_tool_end(self, tool: ToolEvent) -> None:
        """渲染工具结果摘要：缩进的 ⎿ 结果。"""
        style = "red" if tool.is_error else "dim"
        lines = tool.result.split("\n")[:8]
        for line in lines:
            self.console.print(f"  [dim]⎿[/dim] [{style}]{line}[/{style}]")
        if len(tool.result.split("\n")) > 8:
            self.console.print("  [dim]⎿ ...[/dim]")

    # ── 流式输出 ──────────────────────────────────

    @staticmethod
    def _stream_text(text: str) -> None:
        sys.stdout.write(text)
        sys.stdout.flush()

    # ── 渲染 ──────────────────────────────────────

    def _render_banner(self) -> None:
        cwd = os.getcwd()
        home = os.path.expanduser("~")
        if cwd.startswith(home):
            cwd = "~" + cwd[len(home) :]

        self.console.print()
        self.console.print(f"[bold blue]{ASCII_DOG}[/bold blue]")
        self.console.print(f"  [bold]ForgeCode[/bold] [dim]v{VERSION}[/dim]    {cwd}")

        # MCP 连接状态
        mcp_line = self._mcp_summary()
        if mcp_line:
            self.console.print(f"  [dim]{mcp_line}[/dim]")

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

    def _status_bar(self) -> list[tuple[str, str]]:
        model_name = self._active_model()

        # 权限模式标签
        mode_label = self.mode.label()

        # token 用量
        it = self._total_input_tokens
        ot = self._total_output_tokens
        tok_str = f"↑{_fmt_tok(it)} ↓{_fmt_tok(ot)}"

        # 响应耗时 + 轮次
        if self._response_elapsed > 0:
            elapsed = f"{self._response_elapsed:.1f}s"
        elif self._iter > 0:
            elapsed = f"第{self._iter}轮..."
        else:
            elapsed = "..."

        bar = f" {mode_label} │ {model_name} │ {tok_str} │ {elapsed} "
        return [("class:bottom-toolbar.text", bar)]

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
