"""SubAgent 工具过滤多层防线（spec F26-F31）。

过滤只发生在子 Agent 构造时，主 Agent 看到的工具列表不变（N1）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Team 协作工具：仅在 Team 队员上下文（teammate=True）可见。
TEAMMATE_EXTRA_TOOLS: list[str] = [
    "TaskCreate",
    "TaskGet",
    "TaskList",
    "TaskUpdate",
    "SendMessage",
]

# Team 管理工具：任何子 Agent 均不可见（teammate=True 也不加回）。
TEAM_MANAGE_TOOLS: list[str] = ["TeamCreate", "TeamDelete"]

# 任何子 Agent 永远不能用的工具名列表。
# 本期最小列表：Agent。后续可扩展 AskUserQuestion / TaskStop 等元工具。
ALL_AGENT_DISALLOWED_TOOLS: list[str] = ["Agent"]

# 非 Team 子 Agent 额外禁用的协作/管理工具（teammate=True 时协作工具加回）。
TEAMMATE_DISALLOWED_TOOLS: list[str] = [
    *TEAM_MANAGE_TOOLS,
    *TEAMMATE_EXTRA_TOOLS,
]

# 自定义（user / project / plugin 来源）Agent 比内置 Agent 多禁用的工具。本期为空。
CUSTOM_AGENT_DISALLOWED_TOOLS: list[str] = []

# 后台 Agent 工具白名单。
# 不含 Agent / TaskList / TaskGet / TaskStop / SendMessage 等任何元工具。
ASYNC_AGENT_ALLOWED_TOOLS: list[str] = [
    "read_file",
    "write_file",
    "edit_file",
    "glob",
    "grep",
    "bash",
    "load_skill",
    "install_skill",
]


@dataclass
class FilterParams:
    """过滤入参：registry 全量工具名 + 来源 + 后台标记 + 定义层白/黑名单。"""

    all: list[str]  # registry 的全部工具名（按注册顺序）
    source: int  # subagent.Source 的整数值
    background: bool
    allowed: list[str] = field(default_factory=list)  # Agent 定义 tools 白名单
    disallowed: list[str] = field(default_factory=list)  # Agent 定义 disallowedTools 黑名单
    teammate: bool = False  # True=Team 队员：协作工具加回可见集


def is_mcp_or_skill(name: str) -> bool:
    """后台白名单的动态分支：MCP 工具按命名约定识别；skill 工具本期不单独区分。"""
    return name.startswith("mcp__")


def apply_agent_tool_filter(p: FilterParams) -> list[str]:
    """按 spec F30 顺序过滤，返回最终 allowed 列表。

    顺序：起点全量 → 去全局禁止 → 去 Team 协作/管理（teammate=True 时协作工具加回，
    在 disallowed 删除之前）→ （非 builtin 去自定义禁止）→
    后台取白名单交集 → 去定义黑名单 → 定义白名单收窄。
    """
    result = [n for n in p.all if n not in ALL_AGENT_DISALLOWED_TOOLS]

    # Team 上下文：先去掉协作/管理工具，再放行协作工具（管理工具永不放行）
    result = [n for n in result if n not in TEAMMATE_DISALLOWED_TOOLS]
    if p.teammate:
        result = result + [n for n in TEAMMATE_EXTRA_TOOLS if n in p.all and n not in result]

    # 非内置来源（user=1/project=2/plugin=3）额外去自定义禁止（本期为空）
    if p.source >= 1:
        result = [n for n in result if n not in CUSTOM_AGENT_DISALLOWED_TOOLS]

    if p.background:
        result = [n for n in result if n in ASYNC_AGENT_ALLOWED_TOOLS or is_mcp_or_skill(n)]

    if p.disallowed:
        result = [n for n in result if n not in p.disallowed]

    if p.allowed:
        result = [n for n in result if n in p.allowed]

    return result
