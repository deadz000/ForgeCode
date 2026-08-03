"""Catalog：三层来源加载（builtin → user → project）、同名覆盖与查询。"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

from forgecode.permission import Mode
from forgecode.subagent.definition import Definition, Source
from forgecode.subagent.embed import builtin_definitions
from forgecode.subagent.parser import parse_file

# 模块级别名：避免类内方法名 list 遮蔽内建 list 导致注解解析错乱
_DefList = list[Definition]


class Catalog:
    """角色定义索引：同名按来源优先级覆盖（project > user > builtin）。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._by_name: dict[str, Definition] = {}
        self._by_source: dict[Source, list[Definition]] = {}

    def _add_all(self, defs: _DefList, source: Source) -> None:
        """按顺序加入：后加的优先级更高（同名覆盖已存在的）。"""
        with self._lock:
            self._by_source.setdefault(source, []).extend(defs)
            for d in defs:
                self._by_name[d.name] = d  # 后加载的覆盖先加载的

    def resolve(self, name: str) -> Definition | None:
        with self._lock:
            return self._by_name.get(name)

    def list(self) -> _DefList:
        with self._lock:
            return sorted(self._by_name.values(), key=lambda d: d.name)

    def list_by_source(self, src: Source) -> _DefList:
        with self._lock:
            return list(self._by_source.get(src, []))

    def fork_definition(self) -> Definition:
        """Fork 路径用的临时定义。

        disallowed_tools 为空 → 工具集继承父（保留 Agent 工具，靠嵌套阻断拦截）。
        """
        return Definition(
            name="__fork__",
            description="Fork-based subagent",
            model="inherit",
            max_turns=25,
            permission_mode=Mode.DEFAULT,
        )


def load_catalog(root: str | Path) -> Catalog:
    """按 builtin → user → project 顺序加载；解析错误跳过该文件并 stderr 警告。"""
    c = Catalog()
    c._add_all(builtin_definitions(), Source.BUILTIN)
    c._add_all(_load_from_dir(Path.home() / ".forgecode" / "agents", Source.USER), Source.USER)
    c._add_all(_load_from_dir(Path(root) / ".forgecode" / "agents", Source.PROJECT), Source.PROJECT)
    return c


def _load_from_dir(dir_path: Path, source: Source) -> list[Definition]:
    if not dir_path.is_dir():
        return []
    out: list[Definition] = []
    for f in sorted(dir_path.glob("*.md")):
        try:
            out.append(parse_file(str(f), source))
        except Exception as e:
            print(f"subagent {f}: {e}, skipped", file=sys.stderr)
    return out
