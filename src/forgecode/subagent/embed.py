"""内置角色加载：importlib.resources 读取随包发布的 builtin/*.md。"""

from __future__ import annotations

from importlib.resources import files

from forgecode.subagent.definition import Definition, Source
from forgecode.subagent.parser import parse_definition


def builtin_definitions() -> list[Definition]:
    """读取全部内置角色定义，按 name 升序返回。

    内置定义是代码的一部分：解析失败直接 raise（N4 fail-fast）。
    """
    pkg = files("forgecode.subagent.builtin")
    out: list[Definition] = []
    for entry in pkg.iterdir():
        if not entry.name.endswith(".md"):
            continue
        data = entry.read_bytes()
        out.append(parse_definition(data, f"builtin:{entry.name}", Source.BUILTIN))
    out.sort(key=lambda d: d.name)
    return out
