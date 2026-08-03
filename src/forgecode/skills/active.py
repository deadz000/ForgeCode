"""ActiveSkills：跨轮保存已激活 Skill 的 SOP 正文。"""

from __future__ import annotations

import threading

from forgecode.skills.types import ActiveEntry


class ActiveSkills:
    """按激活顺序保存 Skill，重复激活时原位覆盖。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: list[ActiveEntry] = []
        self._index: dict[str, int] = {}

    def activate(self, name: str, body: str) -> None:
        with self._lock:
            if name in self._index:
                self._entries[self._index[name]] = ActiveEntry(name=name, body=body)
            else:
                self._index[name] = len(self._entries)
                self._entries.append(ActiveEntry(name=name, body=body))

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._index.clear()

    def snapshot(self) -> list[ActiveEntry]:
        with self._lock:
            return [ActiveEntry(e.name, e.body) for e in self._entries]

    def names(self) -> list[str]:
        return [e.name for e in self.snapshot()]

    def to_prompt_entries(self) -> list:
        from forgecode.prompt.skills_block import ActiveSkillEntry

        return [ActiveSkillEntry(e.name, e.body) for e in self.snapshot()]
