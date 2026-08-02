"""Slash 命令自动补全：prompt_toolkit Completer 接口。"""

from __future__ import annotations

from prompt_toolkit.completion import Completer, Completion


class SlashCompleter(Completer):
    """当用户输入以 '/' 开头时，显示已注册命令的补全候选。

    仅按命令名前缀匹配（不匹配别名/描述）。hidden=True 的命令不出现在候选列表中。
    """

    def __init__(self, cmd_registry) -> None:
        self._reg = cmd_registry  # command.Registry

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor

        # 仅当首字符为 "/" 时激活
        if not text.startswith("/"):
            return

        # 多行输入不激活
        if "\n" in text:
            return

        # 如果已包含空白（用户输入了参数），不补全
        body = text[1:]
        if " " in body:
            return

        candidates = self._reg.prefix_match(text)
        for cmd in candidates:
            yield Completion(
                f"/{cmd.name}",
                start_position=-len(text),
                display=cmd.name,
                display_meta=cmd.description,
            )
