"""/hooks 命令 handler：输出已加载 hook 列表。"""

from __future__ import annotations

from forgecode.hook.rule import Rule


async def handle_hooks(ui) -> None:
    """输出当前已加载 hook 的精简列表，按 event 分组。"""
    rules = ui.hook_rules()
    if not rules:
        ui.println("No hooks loaded.")
        return

    # 按 event 分组（保留 yaml 声明顺序）
    groups: dict[str, list[Rule]] = {}
    for r in rules:
        groups.setdefault(r.event.value, []).append(r)

    lines: list[str] = []
    for ev, rs in groups.items():
        lines.append(f"{ev}:")
        for r in rs:
            flags: list[str] = []
            if r.only_once:
                flags.append("[once]")
            if r.asyncio_mode:
                flags.append("[async]")
            flag_str = " " + " ".join(flags) if flags else ""
            lines.append(f"  {r.name}  {ev}  {r.action.type.value}{flag_str}")

    sources = ui.hook_sources()
    lines.append(f"Loaded from: {', '.join(sources) if sources else '(none)'}")
    ui.println("\n".join(lines))
