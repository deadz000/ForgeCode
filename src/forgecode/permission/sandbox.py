"""路径沙箱：限定文件操作在项目根目录内（N2）。"""

from __future__ import annotations

import os
from pathlib import Path


def resolve_root(root: str) -> str:
    """解析项目根目录为绝对路径。失败抛 FileNotFoundError。"""
    return str(Path(root).expanduser().resolve(strict=True))


def _eval_symlinks_or_ancestor(abs_path: str) -> str:
    """解析符号链接：存在则 resolve；不存在则回退到最近已存在祖先。"""
    p = Path(abs_path)
    if p.exists():
        return str(p.resolve(strict=True))

    # 逐级回退到最近已存在祖先
    ancestor = p.parent
    remaining: list[str] = [p.name]
    while not ancestor.exists() and str(ancestor) != str(ancestor.parent):
        remaining.insert(0, ancestor.name)
        ancestor = ancestor.parent

    resolved_ancestor = str(ancestor.resolve(strict=True))
    result = resolved_ancestor
    for seg in remaining:
        result = os.path.join(result, seg)
    return result


def sandbox_ok(root: str, path: str) -> bool:
    """判断路径是否在项目根目录内。空路径视为 root。"""
    if not path:
        return True

    # 相对路径相对 root 解析为绝对
    p = Path(path)
    if not p.is_absolute():
        p = Path(root) / p

    abs_path = str(p)

    try:
        resolved = _eval_symlinks_or_ancestor(abs_path)
    except Exception:
        return False

    root_sep = root.rstrip(os.sep) + os.sep
    resolved_sep = resolved.rstrip(os.sep) + os.sep

    return resolved == root or resolved_sep.startswith(root_sep)
