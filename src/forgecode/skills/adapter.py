"""skills 包到 prompt 包的数据桥接。"""

from __future__ import annotations

from forgecode.prompt.skills_block import ActiveSkillEntry, SkillCatalogItem


def catalog_to_prompt_items(catalog) -> list[SkillCatalogItem]:
    return [SkillCatalogItem(s.meta.name, s.meta.description) for s in catalog.list()]


def active_to_prompt_entries(active) -> list[ActiveSkillEntry]:
    return [ActiveSkillEntry(e.name, e.body) for e in active.snapshot()]
