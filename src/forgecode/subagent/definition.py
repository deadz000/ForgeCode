"""SubAgent 核心数据结构：Definition 与 Source 类型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Literal

from forgecode.permission import Mode

# 允许的模型档位；inherit 表示沿用父 Agent 的模型
ModelTier = Literal["haiku", "sonnet", "opus", "inherit"]


class Source(IntEnum):
    """角色定义来源，决定加载顺序与同名覆盖优先级。"""

    BUILTIN = 0
    USER = 1
    PROJECT = 2
    PLUGIN = 3  # 占位：本期不实现真插件加载

    def __str__(self) -> str:
        return {0: "builtin", 1: "user", 2: "project", 3: "plugin"}.get(int(self), "unknown")


@dataclass
class Definition:
    """一个 Agent 角色的完整定义，从 Markdown + YAML frontmatter 解析（spec F4）。"""

    name: str  # frontmatter.name -> Agent 工具的 subagent_type
    description: str  # frontmatter.description -> 工具描述与 UI 列表
    tools: list[str] = field(default_factory=list)  # 白名单；空表示不收窄
    disallowed_tools: list[str] = field(default_factory=list)  # 黑名单
    model: ModelTier = "inherit"  # 模型档位；inherit 沿用父
    max_turns: int = 0  # 0 表示沿用全局默认（25）
    permission_mode: Mode = Mode.DEFAULT  # 子 Agent 启动权限模式
    dont_ask: bool = False  # 子 Agent 专属：Ask 级工具直接放行
    background: bool = False  # true 时忽略 run_in_background 参数强制后台
    system_prompt: str = ""  # Markdown body（去 frontmatter 后的全文）
    file_path: str = ""  # 定义文件绝对路径（调试用）
    source: Source = Source.BUILTIN

    def is_fork(self) -> bool:
        """Fork 路径用的临时定义以 name="__fork__" 标记。"""
        return self.name == "__fork__"
