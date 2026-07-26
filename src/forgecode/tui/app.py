"""TUI 主应用：终端界面渲染、输入处理、命令分发。"""

from __future__ import annotations

import os
import sys

from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.styles import Style
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

# ── ASCII 小狗 ────────────────────────────────────

ASCII_DOG = r"""
   /\___/\
  (  o o  )
  (  =^=  )
   (______)"""

VERSION = "0.1.0"

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
    ) -> None:
        self.config = config
        self.provider = provider
        self.conversation = conversation
        self.console = Console()
        self._show_thinking: bool = True
        self._exit_flag: bool = False

    # ── 启动 ───────────────────────────────────────

    def run(self) -> None:
        """同步入口。"""
        import asyncio

        asyncio.run(self._run_async())

    async def _run_async(self) -> None:
        """异步主循环。"""
        self._render_banner()

        # 创建 prompt_toolkit session
        history = InMemoryHistory()
        session: PromptSession[str] = PromptSession(history=history, style=PROMPT_STYLE)

        while not self._exit_flag:
            # 输入前打印顶部分割线
            self.console.print(Rule(style="dim"))

            try:
                user_input = await session.prompt_async(
                    message=[("class:prompt", "❯ ")],
                    placeholder="Send a message...",
                    bottom_toolbar=self._status_bar,
                )
            except KeyboardInterrupt:
                self.console.print()
                self.console.print("[dim]按 /exit 或 Ctrl+C 再次退出[/dim]")
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
                marker = " *" if p.name == self.config.active_provider_name else "  "
                lines.append(f"{marker} {p.name}  ({p.protocol}/{p.model})")
            self.console.print(
                Panel("\n".join(lines), title="供应商列表", border_style="dim")
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

    # ── 消息发送 ──────────────────────────────────

    async def _send_message(self, text: str) -> None:
        """发送用户消息并流式渲染 AI 回复。"""
        # 显示用户消息
        self.console.print()
        self.console.print(f"[bold cyan]👤 你:[/bold cyan] {text}")
        self.console.print()

        # 记录用户消息
        self.conversation.add("user", text)

        # 开始渲染 AI 回复
        self.console.print("[bold green]🤖 AI:[/bold green] ", end="")

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
                        self._stream_text(event.text)

                elif isinstance(event, ThinkingEnd):
                    if self._show_thinking:
                        self.console.print()
                        self.console.print("─" * 30)
                        self.console.print()
                        self.console.print("[bold green]🤖 回复:[/bold green] ", end="")

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
        if text_buffer:
            self.conversation.add("assistant", text_buffer)

    @staticmethod
    def _stream_text(text: str) -> None:
        """逐 token 输出文本到终端。"""
        sys.stdout.write(text)
        sys.stdout.flush()

    # ── 渲染 ──────────────────────────────────────

    def _render_banner(self) -> None:
        """渲染启动横幅。"""
        cwd = os.getcwd()
        # 如果路径太长，截断显示
        home = os.path.expanduser("~")
        if cwd.startswith(home):
            cwd = "~" + cwd[len(home):]

        self.console.print()
        self.console.print(f"[bold blue]{ASCII_DOG}[/bold blue]")
        self.console.print(f"  [bold]ForgeCode[/bold] [dim]v{VERSION}[/dim]    {cwd}")
        self.console.print()
        self.console.print(
            "[dim]就绪 - 输入消息开始对话，/help 查看命令[/dim]"
        )

    def _status_bar(self) -> list[tuple[str, str]]:
        """生成底部状态栏：左 provider name | 右 model name。"""
        provider_name = self.config.active_provider_name
        model_name = self._active_model()

        # 计算需要的空格数以右对齐
        total_width = 60  # 近似宽度
        left = f" {provider_name} "
        right = f" {model_name} "
        padding = " " * max(1, total_width - len(left) - len(right))

        bar = left + padding + right
        return [("class:bottom-toolbar.text", bar)]

    def _active_model(self) -> str:
        """获取当前活动 provider 的 model 名称。"""
        for p in self.config.providers:
            if p.name == self.config.active_provider_name:
                return p.model
        return "?"
