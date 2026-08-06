"""AgentNameRegistry：name ↔ agent_id 双向映射（弱引用，后注册覆盖前）。"""

from __future__ import annotations

import threading


class AgentNameRegistry:
    """线程安全双向映射（spec F35-F38）。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_name: dict[str, str] = {}
        self._by_id: dict[str, str] = {}

    def register(self, name: str, agent_id: str) -> None:
        """注册 name → agent_id。同名覆盖（先清旧映射）；同 id 换名先反注册。"""
        if not name or not agent_id:
            return
        with self._lock:
            old_id = self._by_name.get(name)
            if old_id is not None and old_id != agent_id:
                if self._by_id.get(old_id) == name:
                    del self._by_id[old_id]
            old_name = self._by_id.get(agent_id)
            if old_name is not None and old_name != name:
                if self._by_name.get(old_name) == agent_id:
                    del self._by_name[old_name]
            self._by_name[name] = agent_id
            self._by_id[agent_id] = name

    def unregister(self, name: str) -> None:
        with self._lock:
            agent_id = self._by_name.pop(name, None)
            if agent_id is not None and self._by_id.get(agent_id) == name:
                del self._by_id[agent_id]

    def unregister_by_agent_id(self, agent_id: str) -> None:
        with self._lock:
            name = self._by_id.pop(agent_id, None)
            if name is not None and self._by_name.get(name) == agent_id:
                del self._by_name[name]

    def resolve(self, name_or_id: str) -> str | None:
        """name 优先；按 agent_id 直查时返回该 id 本身。"""
        with self._lock:
            if name_or_id in self._by_name:
                return self._by_name[name_or_id]
            if name_or_id in self._by_id:
                return name_or_id
            return None

    def name_of(self, agent_id: str) -> str | None:
        with self._lock:
            return self._by_id.get(agent_id)

    def list(self) -> dict[str, str]:
        with self._lock:
            return dict(self._by_name)
