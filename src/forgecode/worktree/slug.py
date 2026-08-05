"""Worktree slug 校验与扁平化。

Slug 是用户给 Worktree 起的名字，支持 ``/`` 做嵌套分隔；
文件系统目录与分支名使用 ``flat_slug``（``/`` → ``+``）避免 Git D/F 冲突。
"""

from __future__ import annotations

import re

# 单段允许的字符集：字母 / 数字 / 点 / 下划线 / 连字符
_SLUG_SEGMENT = re.compile(r"^[a-zA-Z0-9._-]+$")


def validate_slug(name: str) -> None:
    """校验 Worktree 名字（spec F1）。失败抛 ValueError 并携带具体原因。

    规则：
    - name 非空，总长度 ≤ 64
    - 按 ``/`` 切段，每段匹配 ``^[a-zA-Z0-9._-]+$`` 且不能是 ``.`` 或 ``..``
    - 不允许连续 ``//``、首末 ``/``
    """
    if not name:
        raise ValueError("worktree 名称不能为空")
    if len(name) > 64:
        raise ValueError(f"worktree 名称过长（{len(name)} 字符 > 64）")
    if name.startswith("/") or name.endswith("/"):
        raise ValueError("worktree 名称不能以 / 开头或结尾")
    if "//" in name:
        raise ValueError("worktree 名称不能包含连续的 //")
    for seg in name.split("/"):
        if seg in (".", ".."):
            raise ValueError(f"非法段名 {seg!r}: 不能是 . 或 ..")
        if not _SLUG_SEGMENT.fullmatch(seg):
            raise ValueError(f"非法段名 {seg!r}: 只允许字母、数字、点、下划线、连字符")


def flat_slug(name: str) -> str:
    """把嵌套 slug 的 ``/`` 替换为 ``+``，用于目录名与分支名。"""
    return name.replace("/", "+")
