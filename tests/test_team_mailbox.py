"""team.mailbox 单测：write/read/mark_read + 并发 + stale 锁。"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

import pytest

from forgecode.team.mailbox import Box
from forgecode.team.mailbox.message import Message, MessageType


@pytest.fixture
def box(tmp_path: Path) -> Box:
    return Box(str(tmp_path))


async def test_write_read_roundtrip(box: Box) -> None:
    await box.write("alice", Message(from_="lead", to="alice", type=MessageType.TEXT, summary="hi", content="hello"))
    msgs = await box.read("alice")
    assert len(msgs) == 1
    m = msgs[0]
    assert m.from_ == "lead"
    assert m.summary == "hi"
    assert m.content == "hello"
    assert m.timestamp > 0
    assert m.read is False


async def test_read_unread_and_mark(box: Box) -> None:
    await box.write("alice", Message(from_="lead", to="alice", type=MessageType.TEXT, summary="one"))
    await box.write("alice", Message(from_="lead", to="alice", type=MessageType.TEXT, summary="two"))
    idx, unread = await box.read_unread("alice")
    assert len(unread) == 2
    await box.mark_read("alice", idx)
    _, unread2 = await box.read_unread("alice")
    assert len(unread2) == 0


async def test_concurrent_writes_no_loss(box: Box) -> None:
    async def _w(i: int) -> None:
        await box.write("alice", Message(from_="lead", to="alice", type=MessageType.TEXT, summary=f"m{i}"))

    await asyncio.gather(*[_w(i) for i in range(10)])
    msgs = await box.read("alice")
    assert len(msgs) == 10
    assert {m.summary for m in msgs} == {f"m{i}" for i in range(10)}


async def test_stale_lock_reclaimed(tmp_path: Path) -> None:
    b = Box(str(tmp_path))
    lock = tmp_path / "alice.lock"
    lock.write_text("stale", encoding="utf-8")
    now = time.time()
    os.utime(lock, (now - 11, now - 11))
    await b.write("alice", Message(from_="lead", to="alice", type=MessageType.TEXT, summary="x"))
    msgs = await b.read("alice")
    assert len(msgs) == 1
