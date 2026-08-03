"""SubAgent 权限升级：ApprovalUpgrader 类型与默认实现。

子 Agent 在工具调用遇到 Ask 决策时，通过该回调把审批请求升级到父 TUI /
直接向用户弹窗。返回 (outcome, ok)：ok=False 时调用方应拒绝本次调用。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from forgecode.agent import ApprovalRequest
from forgecode.permission import Outcome

ApprovalUpgrader = Callable[[ApprovalRequest], Awaitable[tuple[Outcome, bool]]]


def make_approval_prompter(label: str = "") -> ApprovalUpgrader:
    """构造一个直接向用户弹审批的默认升级回调。

    前台 inline 子 Agent 使用：阻塞式 input() 等待用户三选一。
    label 用于标注子 Agent 身份（如 Explore / fork）。
    """

    async def upgrader(req: ApprovalRequest) -> tuple[Outcome, bool]:
        loop = asyncio.get_running_loop()
        outcome = await loop.run_in_executor(None, _prompt_once, req, label)
        return outcome, True

    return upgrader


def _prompt_once(req: ApprovalRequest, label: str) -> Outcome:
    tag = f" [来自 SubAgent {label}]" if label else " [来自 SubAgent]"
    print(f"\n● {req.name}({req.args}){tag}\n  原因：{req.reason}\n")
    print("  1. 允许本次\n  2. 永久允许（写入本地配置）\n  3. 拒绝本次")
    while True:
        try:
            choice = input("  选择 [1/2/3]（默认 1）：").strip()
        except (EOFError, KeyboardInterrupt):
            return Outcome.DENY_ONCE
        if choice in ("", "1"):
            return Outcome.ALLOW_ONCE
        if choice == "2":
            return Outcome.ALLOW_FOREVER
        if choice == "3":
            return Outcome.DENY_ONCE


async def deny_upgrader(req: ApprovalRequest) -> tuple[Outcome, bool]:
    """后台任务的升级回调：直接拒绝，不打扰用户（无阻塞）。"""
    return Outcome.DENY_ONCE, True
