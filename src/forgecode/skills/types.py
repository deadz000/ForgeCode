"""Skill 技能包核心数据结构。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Literal


class SkillSource(Enum):
    """Skill 来源，决定三层加载的覆盖顺序。"""

    BUILTIN = "builtin"
    USER = "user"
    PROJECT = "project"

    def __str__(self) -> str:
        return self.value


@dataclass
class SkillMeta:
    """SKILL.md frontmatter 解析后的元数据。"""

    name: str
    description: str
    allowed_tools: list[str] = field(default_factory=list)
    mode: Literal["inline", "fork"] = "inline"
    fork_context: Literal["none", "recent", "full"] = "none"
    model: str | None = None

    def is_fork(self) -> bool:
        return self.mode == "fork"


@dataclass
class ToolSpec:
    """tool.json 中声明的专属工具。"""

    name: str
    description: str
    input_schema: dict
    command: list[str]
    base_dir: Path


@dataclass
class Skill:
    """一个已解析的 Skill 目录。"""

    meta: SkillMeta
    prompt_body: str
    source_dir: Path
    source: SkillSource
    tool_specs: list[ToolSpec] = field(default_factory=list)


@dataclass
class ActiveEntry:
    """已激活 Skill 在 ActiveSkills 中的一条记录。"""

    name: str
    body: str
