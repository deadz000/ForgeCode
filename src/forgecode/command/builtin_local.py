"""纯本地命令：/help /status /memory /permission /session"""

from __future__ import annotations

from forgecode.command.command import Handler
from forgecode.command.registry import Registry


def make_help_handler(reg: Registry) -> Handler:
    """工厂函数：闭包捕获 reg，生成 /help 的 handler。"""

    async def _handler(ui) -> None:
        cmds = reg.visible()
        if not cmds:
            ui.println("无可用命令。")
            return
        max_name = max(len(c.name) for c in cmds)
        lines: list[str] = []
        for c in cmds:
            lines.append(f"/{c.name.ljust(max_name)}  {c.description}")
        ui.println("\n".join(lines))

    return _handler


async def handle_status(ui) -> None:
    """输出当前运行状态（6 行 key:value）。"""
    key_width = max(len(k) for k in ["Mode:", "Tokens:", "Tools:", "Memories:", "Model:", "Directory:"])
    lines = [
        "ForgeCode Status",
        "",
        f"  {'Mode:'.ljust(key_width)} {str(ui.get_mode())}",
        f"  {'Tokens:'.ljust(key_width)} {ui.usage_in()} in / {ui.usage_out()} out",
        f"  {'Tools:'.ljust(key_width)} {ui.tool_count()} enabled",
        f"  {'Memories:'.ljust(key_width)} {len(ui.memory_files())} files",
        f"  {'Model:'.ljust(key_width)} {ui.model_name() or '(未选择)'}",
        f"  {'Directory:'.ljust(key_width)} {ui.cwd()}",
    ]
    ui.println("\n".join(lines))


async def handle_memory(ui) -> None:
    """输出当前已加载的记忆文件名列表。"""
    files = ui.memory_files()
    if not files:
        ui.println("无已加载的记忆文件。")
        return
    ui.println("\n".join(f"  {f}" for f in files))


async def handle_permission(ui) -> None:
    """输出当前权限模式名称。"""
    ui.println(f"当前权限模式: {str(ui.get_mode())}")


async def handle_session(ui) -> None:
    """输出当前会话标识信息。"""
    ui.println(f"Session: {ui.session_id()}\nPath:    {ui.session_path()}")
