"""Skill 相关 prompt 块：Catalog 清单与 Active Skills 正文。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SkillCatalogItem:
    name: str
    description: str


@dataclass(frozen=True)
class ActiveSkillEntry:
    name: str
    body: str


def render_skills_catalog(items: list[SkillCatalogItem]) -> str:
    """渲染第一阶段 Available Skills 清单；空列表返回空串。"""
    if not items:
        return ""
    lines = ["## Available Skills", ""]
    for item in items:
        lines.append(f"- {item.name}: {item.description}")
    lines.extend(
        [
            "",
            'Call the LoadSkill tool with {"name": "<skill_name>"} '
            "to activate a skill's full SOP and specialized tools before executing it.",
        ]
    )
    return "\n".join(lines)


def render_active_skills_block(entries: list[ActiveSkillEntry]) -> str:
    """渲染环境上下文中的 Active Skills 块；空列表返回空串。"""
    if not entries:
        return ""
    lines = ["## Active Skills"]
    for entry in entries:
        lines.extend(["", f"### Skill: {entry.name}", "", entry.body])
    return "\n".join(lines)
