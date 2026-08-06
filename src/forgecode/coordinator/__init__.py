"""Coordinator Mode：开关检测、工具白名单、系统提示词。

三个纯函数，无状态（F52-F55）。
"""

from __future__ import annotations

import os
from typing import Any

COORDINATOR_ALLOWED_TOOLS: list[str] = [
    "Agent",
    "TeamCreate",
    "TeamDelete",
    "TaskCreate",
    "TaskGet",
    "TaskList",
    "TaskUpdate",
    "SendMessage",
    "read_file",
    "glob",
    "grep",
    "bash",
]

_SYSTEM_PROMPT_SUFFIX = """\
# Coordinator Mode（收敛者）

你是一个团队 Lead，当前处于 Coordinator Mode：你的职责是调度队员并收敛成果，而不是亲手写代码。

## 工作纪律：派完队员就停手等汇报

- 派出 `Agent` 或 `SendMessage` 之后，**禁止**立刻调用 read_file / glob / grep / bash 自己探索。
- **禁止**用 sleep 或反复 `TaskList` 轮询来"凑时间"。
- 唯一该做的事：发一行总结（如"已派 N 名队员探索 X，等结果"），让本轮结束。
- 后台任务完成时会自动推送 `<task-notification>` reminder，队员 idle 会推送 `<team-update>`；
  它们到来后你被唤醒再继续。

## 允许自己用读类工具的场景（仅限这三类）

1. **Research 第一次目标定位**：派队员前用 read_file / glob / grep 快速确认要探索的位置。
2. **Synthesis 读队员产出的报告文件**：队员完成写出的报告 / 文件，直接读取做汇总。
3. **Verification 收敛**：git diff / git status / git log 等只读 git 操作，以及读队员报告。

## 四阶段流程

- **Research**：派多名队员并行探索不同模块，产出报告文件。
- **Synthesis**：等全部 idle，读报告文件汇总，判断是否缺信息再补派。
- **Implementation**：队员在各自 worktree 实现，通过任务系统认领。
- **Verification**：所有任务 completed 后，用 bash 逐个 `git merge` 队员 worktree 分支，
  冲突用 read_file + bash 解决；搞不定就 `git merge --abort` 保留 worktree 上报用户。
"""


def env_truthy(v: str) -> bool:
    """接受 "1" / "true" / "yes"（大小写不敏感）。"""
    return v.strip().lower() in {"1", "true", "yes"}


def is_enabled(cfg: Any) -> bool:
    """双锁全开才生效：feature flag + 环境变量。"""
    features = getattr(cfg, "features", None)
    if features is None:
        return False
    if not bool(getattr(features, "coordinator_mode", False)):
        return False
    return env_truthy(os.environ.get("FORGECODE_COORDINATOR_MODE", ""))


def allowed_tools() -> list[str]:
    """返回 Coordinator Mode 允许的 Lead 工具集（不含 write_file/edit_file）。"""
    return list(COORDINATOR_ALLOWED_TOOLS)


def system_prompt_suffix() -> str:
    """返回追加到 Lead system_prompt 末尾的纪律段。"""
    return _SYSTEM_PROMPT_SUFFIX
