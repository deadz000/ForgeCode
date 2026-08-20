"""Slash 命令自动补全：prompt_toolkit Completer 接口。"""

from __future__ import annotations

from prompt_toolkit.completion import Completer, Completion


class SlashCompleter(Completer):
    """当用户输入以 '/' 开头时，显示已注册命令（及参数）的补全候选。

    - 命令名前缀匹配（不匹配别名/描述），hidden=True 的命令不出现。
    - 输入 "/<命令> <参数前缀>" 时，若命令声明了 argument_completer，
      则补全参数候选（如 /worktree create|list|enter...）。
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

        # 已包含空白 → 参数补全
        if " " in text:
            name_part, _, arg_prefix = text.partition(" ")
            cmd = self._reg.lookup(name_part[1:])
            if cmd is None or cmd.argument_completer is None:
                return
            for cand in cmd.argument_completer(arg_prefix):
                yield Completion(
                    cand,
                    start_position=-len(arg_prefix),
                    display=cand,
                    display_meta="参数",
                )
            return

        # 命令名补全（未输入参数）
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
