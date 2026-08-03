"""影响界面命令：/exit /plan /compact /resume /clear"""

from __future__ import annotations

from forgecode.permission import Mode


async def handle_exit(ui) -> None:
    """退出 TUI 进程。"""
    ui.quit()


async def handle_plan(ui) -> None:
    """切换到计划模式。"""
    ui.set_mode(Mode.PLAN)
    ui.println("已切换到 PLAN 模式（仅只读工具），输入需求后产出计划。用 /do 批准执行。")


async def handle_compact(ui) -> None:
    """手动触发上下文压缩。"""
    if not ui.idle():
        ui.error("请等待当前任务完成后再使用 /compact")
        return
    ui.force_compact()


async def handle_resume(ui) -> None:
    """打开历史会话恢复列表。"""
    if not ui.idle():
        ui.error("请等待当前任务完成后再使用 /resume")
        return
    await ui.open_resume_menu()


async def handle_clear(ui) -> None:
    """清空当前会话，开启新 session。"""
    ui.clear_and_new_session()
    ui.clear_active_skills()
    ui.println("已清空当前会话，开启新 session。")
