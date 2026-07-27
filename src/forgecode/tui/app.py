"""TUI 主应用：终端界面渲染、输入处理、命令分发、Agent 集成。"""

from __future__ import annotations

import asyncio
import os
import sys
import time

from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.styles import Style
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from rich.text import Text

from forgecode.agent import Agent, Phase, ToolEvent
from forgecode.config.schema import AppConfig
from forgecode.conversation.history import Conversation
from forgecode.providers import BaseProvider, create_provider
from forgecode.tool import Registry

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
    ) -> None:
        self.config = config
        self.provider = provider
        self.conversation = conversation
        self.registry = registry
        self.console = Console()
        self._show_thinking: bool = False
        self._exit_flag: bool = False
        # token 用量累计
        self._total_input_tokens: int = 0
        self._total_output_tokens: int = 0
        # 当前轮次计时
        self._response_start: float = 0
        self._response_elapsed: float = 0

    # ── 启动 ───────────────────────────────────────

    def run(self) -> None:
        """同步入口。"""
        asyncio.run(self._run_async())

    async def _run_async(self) -> None:
        """异步主循环。"""
        self._render_banner()

        history = InMemoryHistory()
        session: PromptSession[str] = PromptSession(
            history=history, style=PROMPT_STYLE
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

            if user_input.startswith("/"):
                self._handle_command(user_input)
            else:
                try:
                    await self._submit(user_input)
                except asyncio.CancelledError:
                    self.console.print()
                    self.console.print("[dim]已中断[/dim]")

    # ── 命令处理 ──────────────────────────────────

    def _handle_command(self, text: str) -> None:
        parts = text.split(maxsplit=1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        if cmd in ("/exit", "/quit"):
            self.console.print("[dim]再见！[/dim]")
            self._exit_flag = True

        elif cmd == "/help":
            self.console.print()
            self.console.print(
                Panel(
                    Text(
                        "/help        显示帮助信息\n"
                        "/clear       清空对话历史\n"
                        "/exit, /quit 退出程序\n"
                        "/providers   列出已配置的供应商\n"
                        "/switch <n>  切换到指定供应商\n"
                        "/thinking on|off  切换思考展示",
                    ),
                    title="可用命令",
                    border_style="dim",
                )
            )
            self.console.print()

        elif cmd == "/clear":
            self.conversation.clear()
            self.console.print("[dim]对话历史已清空。[/dim]")

        elif cmd == "/providers":
            self.console.print()
            lines: list[str] = []
            for p in self.config.providers:
                marker = (
                    " *" if p.name == self.config.active_provider_name else "  "
                )
                lines.append(f"{marker} {p.name}  ({p.protocol}/{p.model})")
            self.console.print(
                Panel(
                    "\n".join(lines), title="供应商列表", border_style="dim"
                )
            )
            self.console.print()

        elif cmd == "/switch":
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
            self.console.print(
                f"[green]已切换到 {new_config.name} ({new_config.model})[/green]"
            )

        elif cmd == "/thinking":
            arg = args.strip().lower()
            if arg == "on":
                self._show_thinking = True
                self.console.print("[green]思考展示已开启[/green]")
            elif arg == "off":
                self._show_thinking = False
                self.console.print("[yellow]思考展示已关闭[/yellow]")
            else:
                self.console.print("[yellow]用法: /thinking on|off[/yellow]")

        else:
            self.console.print(
                f"[yellow]未知命令: {cmd}，输入 /help 查看可用命令[/yellow]"
            )

    # ── 提交消息 ──────────────────────────────────

    async def _submit(self, text: str) -> None:
        """用户提交消息 → Agent 接管。"""
        self.conversation.add_user(text)

        # 开始计时
        self._response_start = time.time()
        self._response_elapsed = 0

        self.console.print()
        self.console.print(f"[bold cyan]👤 你:[/bold cyan] {text}")

        # 启动实时计时器（首次 token 前显示 "Imagining… (Ns)"）
        timer_task = asyncio.create_task(self._show_imagining())

        # 创建 Agent 并消费事件流
        agent = Agent(self.provider, self.registry)
        cur_text = ""
        in_thinking = False
        thinking_shown_header = False
        first_content = False  # 首个文本/思考/工具事件

        try:
            async for ev in agent.run(self.conversation):
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
                        self.console.print(
                            "[dim]💭 思考中...（/thinking on 展开）[/dim]"
                        )
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

                elif ev.done:
                    self._on_first_content(timer_task, first_content)
                    self._response_elapsed = time.time() - self._response_start
                    if cur_text.strip():
                        self.console.print()  # 结束流式行的光标
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
                sys.stdout.write(f"\r🤖 Imagining… ({elapsed:.0f}s)")
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

    # ── 工具行渲染 ────────────────────────────────

    def _render_tool_start(self, tool: ToolEvent) -> None:
        """渲染工具调用开始行：● name(args)。"""
        self.console.print()
        self.console.print(
            f"[bold cyan]●[/bold cyan] [bold]{tool.name}[/bold]({tool.args})"
        )

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
            cwd = "~" + cwd[len(home):]

        self.console.print()
        self.console.print(f"[bold blue]{ASCII_DOG}[/bold blue]")
        self.console.print(
            f"  [bold]ForgeCode[/bold] [dim]v{VERSION}[/dim]    {cwd}"
        )
        self.console.print()
        self.console.print(
            "[dim]就绪 - 输入消息开始对话，/help 查看命令[/dim]"
        )

    def _status_bar(self) -> list[tuple[str, str]]:
        provider_name = self.config.active_provider_name
        model_name = self._active_model()

        # token 用量
        it = self._total_input_tokens
        ot = self._total_output_tokens
        tok_str = f"↑{_fmt_tok(it)} ↓{_fmt_tok(ot)}"

        # 响应耗时（只在轮次完成时显示）
        if self._response_elapsed > 0:
            elapsed = f"{self._response_elapsed:.1f}s"
        else:
            elapsed = "..."

        bar = (
            f" {provider_name} │ {model_name} │ {tok_str} │ {elapsed} "
        )
        return [("class:bottom-toolbar.text", bar)]

    def _active_model(self) -> str:
        for p in self.config.providers:
            if p.name == self.config.active_provider_name:
                return p.model
        return "?"


# ── 辅助 ──────────────────────────────────────────


def _fmt_tok(n: int) -> str:
    """格式化 token 数为可读形式。"""
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)
