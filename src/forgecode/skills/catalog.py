"""Catalog：三层路径扫描、同名覆盖与工具依赖校验。"""

from __future__ import annotations

import sys
import threading
from dataclasses import dataclass
from pathlib import Path

from forgecode.skills.embed_builtin import materialize_builtin_skills
from forgecode.skills.parser import parse_skill_dir
from forgecode.skills.types import Skill, SkillSource

_SYSTEM_TOOL_NAMES = {"load_skill", "install_skill"}


@dataclass(frozen=True)
class ValidationIssue:
    skill_name: str
    tool_name: str


class Catalog:
    """已加载 Skill 的按名索引。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._by_name: dict[str, Skill] = {}
        self._order: list[str] = []

    @classmethod
    def load(cls, work_dir: Path) -> Catalog:
        catalog = cls()
        for builtin_dir in materialize_builtin_skills():
            try:
                catalog.register(parse_skill_dir(Path(builtin_dir), SkillSource.BUILTIN))
            except Exception as e:
                print(f"[skills] warn: skip {builtin_dir}: {e}", file=sys.stderr)
        _load_dir_into(catalog, Path.home() / ".forgecode" / "skills", SkillSource.USER)
        _load_dir_into(catalog, work_dir / ".forgecode" / "skills", SkillSource.PROJECT)
        return catalog

    def register(self, skill: Skill) -> None:
        with self._lock:
            if skill.meta.name in self._by_name:
                self._by_name[skill.meta.name] = skill
                return
            self._by_name[skill.meta.name] = skill
            self._order.append(skill.meta.name)
            self._order.sort()

    def remove(self, name: str) -> None:
        with self._lock:
            if name in self._by_name:
                del self._by_name[name]
                self._order = [n for n in self._order if n != name]

    def get(self, name: str) -> Skill | None:
        with self._lock:
            return self._by_name.get(name)

    def list(self) -> list[Skill]:
        with self._lock:
            return [self._by_name[name] for name in self._order]

    def names(self) -> list[str]:
        with self._lock:
            return list(self._order)

    def reload(self, work_dir: Path) -> None:
        fresh = Catalog.load(work_dir)
        with self._lock:
            self._by_name = fresh._by_name
            self._order = fresh._order

    def validate_tools(self, registry) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        with self._lock:
            for name in self._order:
                skill = self._by_name[name]
                for tool in skill.meta.allowed_tools:
                    if tool in _SYSTEM_TOOL_NAMES:
                        continue
                    if registry.get(tool) is None:
                        issues.append(ValidationIssue(skill_name=skill.meta.name, tool_name=tool))
        return issues

    def to_prompt_items(self) -> list:
        from forgecode.skills.adapter import catalog_to_prompt_items

        return catalog_to_prompt_items(self)


def _load_dir_into(catalog: Catalog, base_dir: Path, source: SkillSource) -> None:
    if not base_dir.is_dir():
        return
    for child in sorted(base_dir.iterdir()):
        if not child.is_dir():
            continue
        try:
            catalog.register(parse_skill_dir(child, source))
        except Exception as e:
            print(f"[skills] warn: skip {child}: {e}", file=sys.stderr)
