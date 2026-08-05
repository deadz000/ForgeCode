"""本地命令 /worktree：手动管理 Worktree（create/list/enter/exit/remove）。

handler 通过 UI 协议的 worktree_accessor() 访问管理器，不直接导入 worktree 包。
"""

from __future__ import annotations

from forgecode.command.ui import UI


async def handle_worktree(ui: UI) -> None:
    args = getattr(ui, "_current_slash_args", "").strip()
    accessor = ui.worktree_accessor()
    if accessor is None:
        ui.error("Worktree 功能未启用（当前目录不是 git 仓库或管理器构建失败）。")
        return
    if not args:
        _usage(ui)
        return

    parts = args.split(maxsplit=1)
    sub = parts[0].lower()
    rest = parts[1].strip() if len(parts) > 1 else ""

    if sub == "create":
        if not rest or rest.startswith("-"):
            ui.error("用法: /worktree create <slug>")
            return
        path, branch = await accessor.create(rest)
        ui.println(f"Worktree 已创建: {path} (分支 {branch})")

    elif sub == "list":
        items = accessor.list()
        if not items:
            ui.println("无 Worktree。")
            return
        for it in items:
            flags = ""
            if it.manual:
                flags += " [manual]"
            if it.active:
                flags += " [active]"
            ui.println(f"{it.name}  {it.path}  {it.branch}{flags}")

    elif sub == "enter":
        if not rest or rest.startswith("-"):
            ui.error("用法: /worktree enter <slug>")
            return
        await accessor.enter(rest)
        ui.println(f"已进入 {rest}，后续工具调用将基于该 Worktree 目录。")

    elif sub == "exit":
        exit_flags = args.split()
        remove = "--remove" in exit_flags
        discard = "--discard" in exit_flags
        removed = await accessor.exit("remove" if remove else "keep", discard)
        if remove:
            ui.println("Worktree 已删除。" if removed else "Worktree 已退出（保留）。")
        else:
            ui.println("已退出当前 Worktree，回到主目录。")

    elif sub == "remove":
        if not rest or rest.startswith("-"):
            ui.error("用法: /worktree remove <slug> [--discard]")
            return
        sub_parts = rest.split()
        name = sub_parts[0]
        discard = "--discard" in sub_parts
        await accessor.remove(name, discard)
        ui.println(f"Worktree 已删除: {name}")

    else:
        ui.error(f"未知子命令: {sub}")
        _usage(ui)


def _usage(ui: UI) -> None:
    ui.println(
        "用法: /worktree create <slug> | list | enter <slug> | "
        "exit [--remove] [--discard] | remove <slug> [--discard]"
    )
