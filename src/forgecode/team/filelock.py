"""跨进程文件锁：os.open(O_CREAT|O_EXCL) 抢占 + 随机抖动重试 + stale 清理。

mailbox 与 tasks 共用；in-process 多 asyncio task 与 Pane 跨进程统一由文件锁串行。
"""

from __future__ import annotations

import asyncio
import os
import random
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

LOCK_MAX_RETRIES: int = 10
LOCK_STALE_AFTER: float = 10.0
LOCK_BACKOFF_MIN: float = 0.005
LOCK_BACKOFF_MAX: float = 0.1


class LockAcquireError(Exception):
    """抢锁重试 10 次仍失败。"""


@asynccontextmanager
async def acquire(lock_path: str) -> AsyncIterator[None]:
    """抢占文件锁；返回时持有锁，退出时释放。

    - os.open(O_CREAT|O_EXCL|O_WRONLY, 0o644) 原子抢占
    - EEXIST → 检查 stale（mtime 超 10s 删除重试一次），否则 5-100ms 随机抖动
    - 最多 LOCK_MAX_RETRIES 次；失败抛 LockAcquireError
    """
    p = Path(lock_path)
    for attempt in range(LOCK_MAX_RETRIES):
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            os.close(fd)
            break
        except FileExistsError:
            if _is_stale(p):
                try:
                    p.unlink()
                except FileNotFoundError:
                    pass
                continue
            if attempt == LOCK_MAX_RETRIES - 1:
                raise LockAcquireError(f"无法获取文件锁: {lock_path}") from None
            await asyncio.sleep(random.uniform(LOCK_BACKOFF_MIN, LOCK_BACKOFF_MAX))
    else:
        raise LockAcquireError(f"无法获取文件锁: {lock_path}")

    try:
        yield
    finally:
        try:
            p.unlink()
        except FileNotFoundError:
            pass


def _is_stale(p: Path) -> bool:
    """持锁超过 LOCK_STALE_AFTER 秒视为 stale。"""
    try:
        st = p.stat()
    except OSError:
        return True
    return time.time() - st.st_mtime > LOCK_STALE_AFTER
