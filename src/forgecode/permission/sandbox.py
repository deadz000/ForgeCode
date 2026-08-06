"""路径沙箱：限定文件操作在项目根目录内（N2）+ 系统临时目录白名单（N9）。

/tmp 与 macOS 真实路径 /private/tmp 允许写入项目根之外，供工具脚本与队员中转。
"""

from __future__ import annotations

import os
from pathlib import Path

# 系统临时目录白名单（规范 N9）。用原始路径前缀判断（跨平台：Windows 下
# Path("/tmp/x") 会被当作相对路径，故在 Path 归一化之前检查原字符串）。
_TMP_ALLOWED = ("/tmp/", "/private/tmp/")


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


def _is_tmp_whitelisted(raw_path: str) -> bool:
    """判断原始路径字符串是否位于系统临时目录白名单内（N9）。"""
    normalized = raw_path.replace("\\", "/")
    return normalized.startswith(_TMP_ALLOWED)


def sandbox_ok(root: str, path: str) -> bool:
    """判断路径是否在项目根目录内。空路径视为 root。"""
    if not path:
        return True

    # 系统临时目录白名单放行（在 Path 归一化之前，避免 Windows 相对路径歧义）
    if _is_tmp_whitelisted(path):
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
