"""工具执行上下文：ContextVar cwd 传递 + 路径解析。

与既有 conv / subagent_depth 的 ContextVar 范式对齐（spec F16）。
工具 schema 不变，ctx 注入不暴露任何新字段。
"""

from __future__ import annotations

import contextvars
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

_ctx_cwd: contextvars.ContextVar[str | None] = contextvars.ContextVar("cwd", default=None)


@contextmanager
def with_cwd(directory: str) -> Iterator[None]:
    """在上下文内设置工具 cwd。directory 为空时不做任何事。"""
    if not directory:
        yield
        return
    token = _ctx_cwd.set(directory)
    try:
        yield
    finally:
        _ctx_cwd.reset(token)


def cwd_from_ctx() -> str | None:
    """取回当前 ctx cwd；未设置时返回 None。"""
    return _ctx_cwd.get()


def resolve_path(p: str) -> str:
    """把路径解析为绝对路径：绝对路径直接返回；相对路径用 ctx cwd（优先）或进程 cwd 拼接。"""
    base = _ctx_cwd.get() or str(Path.cwd())
    if not p:
        return base
    pp = Path(p)
    if pp.is_absolute():
        return str(pp)
    return str(Path(base) / pp)
