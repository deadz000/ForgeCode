"""TUI 主应用：终端界面渲染、输入处理、命令分发。"""

from __future__ import annotations

import asyncio
import sys

from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.text import Text

from forgecode.config.schema import AppConfig
from forgecode.conversation.history import Conversation
from forgecode.providers import (
    BaseProvider,
    ErrorEvent,
    TextDelta,
    ThinkingDelta,
    ThinkingEnd,
    ThinkingStart,
    create_provider,
)


class ForgeApp:
    """ForgeCode 终端交互应用。"""

    def __init__(
        self,
        config: AppConfig,
        provider: BaseProvider,
        conversation: Conversation,
    ) -> None:
        self.config = config
        self.provider = provider
        self.conversation = conversation
        self.console = Console()
        self._show_thinking: bool = True
        self._exit_flag: bool = False

    def run(self) -> None:
        """启动 TUI 事件循环。"""
        asyncio.run(self._run_async())

    async def _run_async(self) -> None:
        """异步主循环。"""
        self._render_header()

        # 创建 prompt_toolkit session
        history = InMemoryHistory()
        session: PromptSession[str] = PromptSession(history=history)

        while not self._exit_flag:
            try:
                user_input = await session.prompt_async(
                    [("class:prompt", "> ")],
                )
            except KeyboardInterrupt:
                self.console.print("\n[dim]按 /exit 或 Ctrl+C 再次退出[/dim]")
                continue
            except EOFError:
                self.console.print("\n再见！")
                break

            user_input = user_input.strip()
            if not user_input:
                continue

            if user_input.startswith("/"):
                self._handle_command(user_input)
            else:
                await self._send_message(user_input)

    # ── 命令处理 ──────────────────────────────────

    def _handle_command(self, text: str) -> None:
        """解析并执行 / 命令。"""
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
                )
            )
            self.console.print()

        elif cmd == "/clear":
            self.conversation.clear()
            self.console.print("[dim]对话历史已清空。[/dim]\n")
            self._render_header()

        elif cmd == "/providers":
            self.console.print()
            lines: list[str] = []
            for p in self.config.providers:
                marker = " *" if p.name == self.config.active_provider_name else "  "
                lines.append(f"{marker} {p.name}  ({p.protocol}/{p.model})")
            self.console.print(Panel("\n".join(lines), title="供应商列表"))
            self.console.print()

        elif cmd == "/switch":
            if not args:
                self.console.print("[yellow]用法: /switch <供应商名称>[/yellow]")
                return
            name = args.strip()
            matching = [p for p in self.config.providers if p.name == name]
            if not matching:
                self.console.print(f"[red]未找到供应商 '{name}'[/red]")
                return
            new_config = matching[0]
            self.provider = create_provider(new_config)
            self.config.active_provider_name = new_config.name
            self.console.print(f"[green]已切换到 {new_config.name} ({new_config.model})[/green]")
            self._render_header()

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
            self.console.print(f"[yellow]未知命令: {cmd}，输入 /help 查看可用命令[/yellow]")

    # ── 消息发送 ──────────────────────────────────

    async def _send_message(self, text: str) -> None:
        """发送用户消息并流式渲染 AI 回复。"""
        # 显示用户消息
        self.console.print()
        self.console.print(f"[bold]👤 你:[/bold] {text}")
        self.console.print()

        # 记录用户消息
        self.conversation.add("user", text)

        # 开始渲染 AI 回复
        self.console.print("[bold]🤖 AI:[/bold] ", end="")

        thinking_buffer: str = ""
        text_buffer: str = ""

        try:
            async for event in self.provider.chat_stream(self.conversation.messages):  # type: ignore[attr-defined]
                if isinstance(event, ThinkingStart):
                    thinking_buffer = ""
                    if self._show_thinking:
                        self.console.print()
                        self.console.print("[dim]💭 思考过程:[/dim]")
                        self.console.print("─" * 30)

                elif isinstance(event, ThinkingDelta):
                    thinking_buffer += event.text
                    if self._show_thinking:
                        self._stream_text(event.text, color="dim")

                elif isinstance(event, ThinkingEnd):
                    if self._show_thinking:
                        self.console.print()
                        self.console.print("─" * 30)
                        self.console.print()
                        self.console.print("[bold]🤖 回复:[/bold] ", end="")

                elif isinstance(event, TextDelta):
                    text_buffer += event.text
                    self._stream_text(event.text)

                elif isinstance(event, ErrorEvent):
                    self.console.print()
                    if event.retryable:
                        self.console.print(f"[red]⚠ {event.message}[/red]")
                    else:
                        self.console.print(f"[red]✕ {event.message}[/red]")
                    break

        except Exception as e:
            self.console.print()
            self.console.print(f"[red]✕ 对话出错: {e}[/red]")

        self.console.print()

        # 记录 AI 回复
        if text_buffer or thinking_buffer:
            content = text_buffer
            self.conversation.add("assistant", content)

    @staticmethod
    def _stream_text(text: str, color: str = "") -> None:
        """逐字输出文本到终端。"""
        for char in text:
            sys.stdout.write(char)
        sys.stdout.flush()

    # ── 渲染 ──────────────────────────────────────

    def _render_header(self) -> None:
        """渲染顶部状态栏。"""
        model = "?"
        for p in self.config.providers:
            if p.name == self.config.active_provider_name:
                model = p.model
                break
        self.console.print()
        self.console.print(
            Panel(f"[bold]ForgeCode[/bold] · {model}", style="bold blue")
        )
        self.console.print(Rule(style="dim"))
