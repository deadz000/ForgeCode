"""命令注册中心：注册、冲突检测、查找、前缀匹配。"""

from __future__ import annotations

from forgecode.command.command import Command


class Registry:
    """集中登记命令，提供按名查找和前缀匹配能力。"""

    def __init__(self) -> None:
        self._by_name: dict[str, Command] = {}
        self._visible: list[Command] = []

    def register(self, cmd: Command) -> None:
        """注册一条命令。

        对 cmd.name 和 cmd.aliases 做冲突检测：任一键已存在则立即 raise RuntimeError。
        非 hidden 的命令追加到 _visible 并保持字典序。
        """
        keys = [cmd.name] + list(cmd.aliases)

        # 校验：全部非空且全小写
        for key in keys:
            if not key:
                raise ValueError(f"命令键不能为空: {cmd!r}")
            if any(c.isupper() for c in key):
                raise ValueError(f"命令键必须全小写: {key!r}")

        # 冲突检测
        for key in keys:
            if key in self._by_name:
                raise RuntimeError(f"command conflict: {key}")

        # 注册
        for key in keys:
            self._by_name[key] = cmd

        if not cmd.hidden:
            self._visible.append(cmd)
            self._visible.sort(key=lambda c: c.name)

    def lookup(self, name: str) -> Command | None:
        """按名查找（大小写不敏感）。"""
        return self._by_name.get(name.lower())

    def visible(self) -> list[Command]:
        """返回已排序可见命令的副本（不含 hidden=True 的命令）。"""
        return list(self._visible)

    def prefix_match(self, prefix: str) -> list[Command]:
        """前缀匹配（仅匹配 name，不匹配别名/描述）。

        prefix 可含 "/" 前缀，内部会 strip 并小写化。
        空 prefix 时返回全部 visible 命令。
        """
        p = prefix.lstrip("/").lower()
        if not p:
            return list(self._visible)
        return [c for c in self._visible if c.name.startswith(p)]
