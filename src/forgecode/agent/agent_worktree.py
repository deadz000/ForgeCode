"""Worktree 隔离分支：SubAgent 在独立 Git Worktree 副本中运行（spec F21/F22）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from forgecode.tool.ctx import with_cwd
from forgecode.worktree import Manager, random_agent_name


def build_worktree_notice(parent_cwd: str, wt_path: str) -> str:
    """构造注入子 Agent 任务文本前的 Worktree 上下文说明（spec F22）。"""
    return (
        "<worktree-context>\n"
        "你当前在一个独立的 Git Worktree 副本中工作，与父 Agent 隔离。\n"
        f"- 父目录: {parent_cwd}\n"
        f"- 你的工作目录: {wt_path}\n"
        "- 父 Agent 提到的绝对路径基于父目录，你需要翻译成本地路径（替换前缀）再读写\n"
        "- 编辑文件前，必须先在本地 Worktree 重新 read_file 一次，避免使用过时内容\n"
        "</worktree-context>"
    )


async def _execute_with_worktree(
    manager: Manager,
    definition: Any,
    sub_agent: Any,
    sub_conv: Any,
    prompt: str,
    events: Any,
) -> str:
    """在临时 Worktree 内运行子 Agent：create → 注入 notice → ctx cwd → 跑完 → auto_cleanup。"""
    name = random_agent_name()
    wt = await manager.create(name, "HEAD", manual=False)
    parent_cwd = str(Path.cwd())
    notice = build_worktree_notice(parent_cwd, wt.path)
    task_text = notice + "\n\n" + prompt

    with with_cwd(wt.path):
        final_text: str = await sub_agent.run_to_completion(sub_conv, task_text, events)

    report = await manager.auto_cleanup(name)
    if report.kept:
        final_text += f"\n[Worktree 保留: {report.path} ,分支 {report.branch}]"
    return final_text
