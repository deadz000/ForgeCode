"""team.registry 单测：注册/解析/反查/覆盖。"""

from __future__ import annotations

from forgecode.team.registry import AgentNameRegistry


def test_register_and_resolve() -> None:
    r = AgentNameRegistry()
    r.register("alice", "agent-1")
    assert r.resolve("alice") == "agent-1"
    assert r.name_of("agent-1") == "alice"


def test_resolve_by_id() -> None:
    r = AgentNameRegistry()
    r.register("alice", "agent-1")
    assert r.resolve("agent-1") == "agent-1"


def test_overwrite_name() -> None:
    r = AgentNameRegistry()
    r.register("alice", "agent-1")
    r.register("alice", "agent-2")
    assert r.resolve("alice") == "agent-2"
    assert r.name_of("agent-1") is None
    assert r.name_of("agent-2") == "alice"


def test_same_id_new_name() -> None:
    r = AgentNameRegistry()
    r.register("alice", "agent-1")
    r.register("bob", "agent-1")
    assert r.resolve("alice") is None
    assert r.resolve("bob") == "agent-1"


def test_unregister() -> None:
    r = AgentNameRegistry()
    r.register("alice", "agent-1")
    r.unregister("alice")
    assert r.resolve("alice") is None
    assert r.name_of("agent-1") is None


def test_unregister_by_agent_id() -> None:
    r = AgentNameRegistry()
    r.register("alice", "agent-1")
    r.unregister_by_agent_id("agent-1")
    assert r.resolve("alice") is None


def test_list() -> None:
    r = AgentNameRegistry()
    r.register("alice", "agent-1")
    r.register("bob", "agent-2")
    assert r.list() == {"alice": "agent-1", "bob": "agent-2"}
