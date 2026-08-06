"""本地命令 /team：list/info/delete/kill（F59-F62）。

handler 通过 UI 协议的 team_manager() 访问 Manager，不直接导入 team 包。
"""

from __future__ import annotations

from forgecode.command.ui import UI


async def handle_team(ui: UI) -> None:
    args = getattr(ui, "_current_slash_args", "").strip()
    mgr = ui.team_manager()
    if mgr is None:
        ui.error("Team 功能未启用。")
        return
    if not args:
        _usage(ui)
        return

    parts = args.split(maxsplit=1)
    sub = parts[0].lower()
    rest = parts[1].strip() if len(parts) > 1 else ""

    if sub == "list":
        teams = mgr.list_()
        if not teams:
            ui.println("无 Team。")
            return
        for t in teams:
            total = len(t.members) - 1  # 去掉 Lead
            active = sum(1 for m in t.members if m.name != "lead" and m.is_active is not False)
            ui.println(f"{t.sanitized_name}  {str(t.backend)}  {total} 成员  [{active}/{total}] 活跃")

    elif sub == "info":
        if not rest:
            ui.error("用法: /team info <name>")
            return
        t = mgr.get(rest)
        if t is None:
            ui.error(f"团队不存在: {rest}")
            return
        lines = [
            f"Team: {t.sanitized_name}  (backend={t.backend})",
            f"配置: {t.config_path}",
            f"描述: {t.description or '(无)'}",
            f"创建: {t.created_at.isoformat()}",
            "成员:",
        ]
        for m in t.members:
            state = "active" if m.is_active is not False else "idle"
            lines.append(f"  {m.name}  agent_id={m.agent_id}  backend={m.backend_type}  state={state}")
            if m.worktree_path:
                lines.append(f"    worktree: {m.worktree_path}")
            if m.pane_id:
                lines.append(f"    pane: {m.pane_id}")
            if m.session_dir:
                lines.append(f"    session: {m.session_dir}")
        ui.println("\n".join(lines))

    elif sub == "delete":
        force = "--force" in args.split()
        name = rest.replace("--force", "").strip()
        if not name:
            ui.error("用法: /team delete <name> [--force]")
            return
        try:
            await mgr.delete(name, force)
        except Exception as e:
            ui.error(f"删除失败: {e}")
            return
        if getattr(mgr, "active_team_name", None) == name:
            mgr.active_team_name = None
        ui.println(f"已删除 Team: {name}")

    elif sub == "kill":
        if not rest:
            ui.error("用法: /team kill <member>")
            return
        target = rest.split()[0]
        for t in mgr.list_():
            if t.member_by_name(target) is not None:
                ok = await mgr.kill_member(t.sanitized_name, target)
                ui.println(f"已终止队员 {target}" if ok else f"队员 {target} 不存在")
                return
        ui.error(f"未找到队员 {target} 所属的 Team")

    else:
        ui.error(f"未知子命令: {sub}")
        _usage(ui)


def _usage(ui: UI) -> None:
    ui.println("用法: /team list | info <name> | delete <name> [--force] | kill <member>")
