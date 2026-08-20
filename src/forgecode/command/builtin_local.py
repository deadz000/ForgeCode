"""纯本地命令：/help /status /memory /permission /session /tool"""

from __future__ import annotations

from forgecode.command.command import Command, Handler, Kind
from forgecode.command.registry import Registry
from forgecode.command.ui import ToolLogEntry

# /tool 列表模式下结果首行预览长度
_TOOL_PREVIEW_LEN = 120

# /help 分组：Kind → 中文组名（is_skill 命令归"技能"组）
_HELP_GROUP_NAMES = {
    Kind.PROMPT: "对话",
    Kind.UI: "界面",
    Kind.LOCAL: "信息",
}
_HELP_GROUP_ORDER = ("对话", "界面", "信息", "技能", "其他")


def make_help_handler(reg: Registry) -> Handler:
    """工厂函数：闭包捕获 reg，生成按分类分组的 /help 输出。"""

    async def _handler(ui) -> None:
        cmds = reg.visible()
        if not cmds:
            ui.println("无可用命令。")
            return
        groups: dict[str, list[Command]] = {}
        for c in cmds:
            gname = "技能" if c.is_skill else _HELP_GROUP_NAMES.get(c.kind, "其他")
            groups.setdefault(gname, []).append(c)
        max_name = max(len(c.name) for c in cmds)
        lines = ["可用命令（输入 /命令 或 Tab 补全）:"]
        for gname in _HELP_GROUP_ORDER:
            if gname not in groups:
                continue
            lines.append("")
            lines.append(f"── {gname} ──")
            for c in groups[gname]:
                lines.append(f"  /{c.name.ljust(max_name)}  {c.description}")
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


async def handle_tool(ui) -> None:
    """查看工具调用日志：/tool（最近列表）/tool <n>（展开详情）/tool last /tool clear。"""
    args = getattr(ui, "_current_slash_args", "").strip()
    if args == "clear":
        ui.tool_log_clear()
        ui.println("工具调用日志已清空。")
        return
    if args in ("last", "latest"):
        entries = ui.tool_log(limit=1)
        if not entries:
            ui.println("尚无工具调用记录。")
            return
        _print_tool_detail(ui, entries[0])
        return
    if args:
        try:
            idx = int(args)
        except ValueError:
            ui.println("用法: /tool [<序号>|last|clear]")
            return
        entry = ui.tool_log_detail(idx)
        if entry is None:
            ui.println(f"没有序号为 {idx} 的工具调用记录。")
            return
        _print_tool_detail(ui, entry)
        return

    entries = ui.tool_log(limit=10)
    if not entries:
        ui.println("尚无工具调用记录。")
        return
    lines = ["工具调用日志（/tool <序号> 展开详情）:"]
    for e in entries:
        marker = "✕" if e.is_error else "●"
        first = (e.result.split("\n")[0] if e.result else "")[:_TOOL_PREVIEW_LEN]
        lines.append(f"  #{e.index} {marker} {e.name}({e.args})  · {e.elapsed:.1f}s")
        if first:
            lines.append(f"      ⎿ {first}")
    ui.println("\n".join(lines))


def _print_tool_detail(ui, entry: ToolLogEntry) -> None:
    """展开打印一次工具调用的完整参数与结果。"""
    ui.println(f"── 工具调用 #{entry.index}: {entry.name} ──")
    ui.println(f"参数: {entry.args}")
    ui.println(f"耗时: {entry.elapsed:.1f}s")
    if entry.result:
        ui.println("结果:")
        ui.println(entry.result)
