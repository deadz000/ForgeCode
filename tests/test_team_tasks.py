"""team.tasks 单测：CRUD + 依赖关系 + is_ready。"""

from __future__ import annotations

from pathlib import Path

import pytest

from forgecode.team.tasks import Filter, Patch, Store, Task, TaskNotFound


@pytest.fixture
def store(tmp_path: Path) -> Store:
    return Store(str(tmp_path / "tasks.json"))


async def test_create_id_format(store: Store) -> None:
    tid = await store.create(Task(id="", title="t"))
    assert tid.startswith("task_")
    assert len(tid) == len("task_") + 6


async def test_get(store: Store) -> None:
    tid = await store.create(Task(id="", title="t", assignee="alice"))
    t = await store.get(tid)
    assert t.title == "t"
    assert t.assignee == "alice"


async def test_get_missing(store: Store) -> None:
    with pytest.raises(TaskNotFound):
        await store.get("task_000000")


async def test_update_fields(store: Store) -> None:
    tid = await store.create(Task(id="", title="t"))
    await store.update(tid, Patch(title="t2", status="in_progress"))
    t = await store.get(tid)
    assert t.title == "t2"
    assert t.status.value == "in_progress"


async def test_add_blocked_by_bidirectional(store: Store) -> None:
    a = await store.create(Task(id="", title="a"))
    b = await store.create(Task(id="", title="b"))
    await store.update(b, Patch(add_blocked_by=[a]))
    ta = await store.get(a)
    tb = await store.get(b)
    assert a in tb.blocked_by
    assert b in ta.blocks


async def test_remove_blocked_by(store: Store) -> None:
    a = await store.create(Task(id="", title="a"))
    b = await store.create(Task(id="", title="b"))
    await store.update(b, Patch(add_blocked_by=[a]))
    await store.update(b, Patch(remove_blocked_by=[a]))
    tb = await store.get(b)
    ta = await store.get(a)
    assert a not in tb.blocked_by
    assert b not in ta.blocks


async def test_list_filter_and_ready(store: Store) -> None:
    a = await store.create(Task(id="", title="a"))
    b = await store.create(Task(id="", title="b"))
    await store.update(b, Patch(add_blocked_by=[a]))
    await store.update(a, Patch(status="completed"))
    tasks = await store.list_(Filter(status="pending"))
    by_id = {t.id: t for t in tasks}
    # b 的 blocker a 已完成 → is_ready True
    assert by_id[b].is_ready is True
    await store.update(a, Patch(status="in_progress"))
    tasks2 = await store.list_(Filter())
    by_id2 = {t.id: t for t in tasks2}
    assert by_id2[b].is_ready is False


async def test_persistence_across_store(store: Store, tmp_path: Path) -> None:
    tid = await store.create(Task(id="", title="persist"))
    store2 = Store(str(tmp_path / "tasks.json"))
    assert (await store2.get(tid)).title == "persist"
