"""系统提示工程化：模块化装配、环境采集、补充消息注入。"""

from __future__ import annotations

from forgecode.prompt.environment import Environment, gather_environment
from forgecode.prompt.modules import Module, fixed_modules, optional_modules
from forgecode.prompt.reminder import (
    EXECUTE_DIRECTIVE,
    plan_reminder,
    system_reminder,
)
from forgecode.prompt.skills_block import (
    ActiveSkillEntry,
    SkillCatalogItem,
    render_active_skills_block,
    render_skills_catalog,
)


def assemble_system(mods: list[Module]) -> str:
    """按 priority 升序排列、跳过空 content、以空行连接为完整系统提示。"""
    sorted_mods = sorted(mods, key=lambda m: m.priority)
    non_empty = [m.content for m in sorted_mods if m.content]
    return "\n\n".join(non_empty)


def build_system_prompt(instructions: str = "", memory: str = "", skills_catalog: str = "") -> str:
    """装配完整系统提示 = fixed_modules() + optional_modules(instructions, memory, skills_catalog)。"""
    return assemble_system(fixed_modules() + optional_modules(instructions, memory, skills_catalog))


__all__ = [
    "ActiveSkillEntry",
    "Module",
    "SkillCatalogItem",
    "fixed_modules",
    "optional_modules",
    "assemble_system",
    "build_system_prompt",
    "Environment",
    "gather_environment",
    "render_active_skills_block",
    "render_skills_catalog",
    "system_reminder",
    "plan_reminder",
    "EXECUTE_DIRECTIVE",
]
