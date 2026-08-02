"""内置命令注册：register_builtins(reg) 一次性注入 12 条 spec 命令。"""

from __future__ import annotations

from forgecode.command.builtin_local import (
    handle_memory,
    handle_permission,
    handle_session,
    handle_status,
    make_help_handler,
)
from forgecode.command.builtin_prompt import handle_do, handle_review
from forgecode.command.builtin_ui import (
    handle_clear,
    handle_compact,
    handle_exit,
    handle_plan,
    handle_resume,
)
from forgecode.command.command import Command, Kind
from forgecode.command.registry import Registry


def register_builtins(reg: Registry) -> None:
    """向 reg 注册全部 12 条内置命令（按 name 字典序排列）。"""

    # /help 的 handler 通过工厂捕获 reg 自身
    help_handler = make_help_handler(reg)

    builtins = [
        Command(
            name="clear",
            description="清空对话历史并开启新会话",
            kind=Kind.UI,
            handler=handle_clear,
            aliases=["cls"],
        ),
        Command(
            name="compact",
            description="手动压缩上下文",
            kind=Kind.UI,
            handler=handle_compact,
            aliases=["cmp"],
        ),
        Command(name="do", description="批准计划并开始执行", kind=Kind.PROMPT, handler=handle_do),
        Command(
            name="exit",
            description="退出程序",
            kind=Kind.UI,
            handler=handle_exit,
            aliases=["q", "quit"],
        ),
        Command(
            name="help",
            description="显示可用命令列表",
            kind=Kind.LOCAL,
            handler=help_handler,
            aliases=["h", "?"],
        ),
        Command(
            name="memory",
            description="查看已加载的记忆文件列表",
            kind=Kind.LOCAL,
            handler=handle_memory,
            aliases=["mem"],
        ),
        Command(
            name="permission",
            description="查看当前权限模式",
            kind=Kind.LOCAL,
            handler=handle_permission,
            aliases=["perm"],
        ),
        Command(
            name="plan",
            description="进入计划模式（仅只读工具）",
            kind=Kind.UI,
            handler=handle_plan,
            aliases=["p"],
        ),
        Command(
            name="resume",
            description="恢复历史会话",
            kind=Kind.UI,
            handler=handle_resume,
            aliases=["res"],
        ),
        Command(
            name="review",
            description="触发代码审查",
            kind=Kind.PROMPT,
            handler=handle_review,
            aliases=["rev"],
        ),
        Command(
            name="session",
            description="查看当前会话信息",
            kind=Kind.LOCAL,
            handler=handle_session,
            aliases=["ses"],
        ),
        Command(
            name="status",
            description="查看当前运行状态",
            kind=Kind.LOCAL,
            handler=handle_status,
            aliases=["st"],
        ),
    ]

    for cmd in builtins:
        reg.register(cmd)
