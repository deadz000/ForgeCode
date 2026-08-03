"""内置 Skill 资源：通过 importlib.resources 读取并落地到 cache 目录。"""

from __future__ import annotations

import os
from importlib.resources import files
from pathlib import Path


def _iter_builtin_skill_dirs():
    base = files("forgecode.skills.builtin")
    for entry in base.iterdir():
        if entry.is_dir() and entry.joinpath("SKILL.md").is_file():
            yield entry


def builtin_cache_root() -> Path:
    xdg = os.environ.get("XDG_CACHE_HOME")
    root = Path(xdg) if xdg else Path.home() / ".cache"
    return root / "forgecode" / "builtin-skills"


def materialize_builtin_skills() -> list[Path]:
    """把三个内置 Skill 复制到 cache 目录，返回目录列表。"""
    dests: list[Path] = []
    for entry in _iter_builtin_skill_dirs():
        target = builtin_cache_root() / entry.name
        target.mkdir(parents=True, exist_ok=True)
        _copy_resource_dir(entry, target)
        dests.append(target)
    return dests


def _copy_resource_dir(src, dst: Path) -> None:
    for child in src.iterdir():
        target = dst / child.name
        if child.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            _copy_resource_dir(child, target)
        else:
            target.write_bytes(child.read_bytes())
