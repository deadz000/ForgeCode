"""Worktree 创建 + 快速恢复 + 创建后设置（A/B/C/D）。

全部创建后设置均为 best-effort：失败仅 stderr 警告，不中断创建主路径。
"""

from __future__ import annotations

import fnmatch
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from forgecode.worktree.git import _resolve_head_sha_from_fs, _run_git
from forgecode.worktree.slug import flat_slug, validate_slug

if TYPE_CHECKING:
    from forgecode.worktree.manager import Manager, Worktree


async def create(manager: Manager, name: str, base_ref: str, manual: bool) -> Worktree:
    """创建 Worktree（spec F6）。已存在目录时走快速恢复，不调 git。"""
    from forgecode.worktree.manager import Worktree

    validate_slug(name)
    flat = flat_slug(name)
    wt_path = manager.worktree_dir / flat
    branch_name = f"worktree-{flat}"

    async with manager.lock:
        if name in manager.active or flat in manager.active:
            raise ValueError(f"worktree 已存在: {name}")

        # 快速恢复：目录已存在 → 纯 fs 读还原，不调 git
        if wt_path.exists():
            head_sha = _resolve_head_sha_from_fs(str(wt_path))
            if head_sha is None:
                raise ValueError(f"worktree 目录已存在但无法解析 HEAD: {wt_path}")
            wt = Worktree(
                name=name,
                path=str(wt_path),
                branch=branch_name,
                based_on=base_ref,
                head_commit=head_sha,
                created=datetime.now(),
                manual=manual,
            )
            manager.active[name] = wt
            manager.active[flat] = wt
            return wt

        # 正常创建：git worktree add -B <branch> <wt_path> <base_ref>
        try:
            await _run_git(
                manager.repo_root,
                "worktree",
                "add",
                "-B",
                branch_name,
                str(wt_path),
                base_ref,
            )
        except Exception:
            shutil.rmtree(wt_path, ignore_errors=True)
            raise

        await _perform_post_creation_setup(manager, wt_path)
        head_sha = await _run_git(str(wt_path), "rev-parse", "HEAD")
        wt = Worktree(
            name=name,
            path=str(wt_path),
            branch=branch_name,
            based_on=base_ref,
            head_commit=head_sha,
            created=datetime.now(),
            manual=manual,
        )
        manager.active[name] = wt
        manager.active[flat] = wt
        return wt


async def _perform_post_creation_setup(manager: Manager, wt_path: Path) -> None:
    """依次执行 A/B/C/D 四类创建后设置；每个子步骤失败仅警告。"""
    try:
        copy_local_configs(manager.repo_root, wt_path)
    except Exception as exc:
        print(f"worktree: setup A: {exc}", file=sys.stderr)
    try:
        await setup_git_hooks(manager.repo_root, wt_path)
    except Exception as exc:
        print(f"worktree: setup B: {exc}", file=sys.stderr)
    try:
        symlink_large_dirs(manager.repo_root, wt_path, manager.symlink_dirs)
    except Exception as exc:
        print(f"worktree: setup C: {exc}", file=sys.stderr)
    try:
        copy_included_ignored(manager.repo_root, wt_path)
    except Exception as exc:
        print(f"worktree: setup D: {exc}", file=sys.stderr)


# ── 设置 A：复制本地配置 ──


def copy_local_configs(repo_root: str, wt_path: Path) -> None:
    """把主仓库 .forgecode/config.yaml / settings.local.yaml 复制到 Worktree 同位置。"""
    for rel in (".forgecode/config.yaml", ".forgecode/settings.local.yaml"):
        src = Path(repo_root) / rel
        dst = wt_path / rel
        if src.exists() and not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)


# ── 设置 B：git hooks ──


async def setup_git_hooks(repo_root: str, wt_path: Path) -> None:
    """检测主仓库 core.hooksPath / .husky/，有则给 Worktree 配置相同 hooksPath。"""
    hooks_path = ""
    if (Path(repo_root) / ".husky").is_dir():
        hooks_path = str(Path(repo_root) / ".husky")
    else:
        try:
            hooks_path = await _run_git(repo_root, "config", "--get", "core.hooksPath")
        except RuntimeError:
            hooks_path = ""
    if hooks_path:
        await _run_git(str(wt_path), "config", "core.hooksPath", hooks_path)


# ── 设置 C：软链大目录 ──


def symlink_large_dirs(repo_root: str, wt_path: Path, symlink_dirs: list[str]) -> None:
    """对每个大目录，若主仓存在且 Worktree 不存在则创建软链。"""
    for d in symlink_dirs:
        src = Path(repo_root) / d
        dst = wt_path / d
        if src.is_dir() and not dst.exists():
            os.symlink(str(src), str(dst), target_is_directory=True)


# ── 设置 D：复制 .worktreeinclude 命中的忽略文件 ──


def copy_included_ignored(repo_root: str, wt_path: Path) -> None:
    """读取项目根 .worktreeinclude 每行 glob 模式，复制命中的被忽略文件。"""
    include_file = Path(repo_root) / ".worktreeinclude"
    if not include_file.exists():
        return
    patterns = [
        line.strip() for line in include_file.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    if not patterns:
        return

    try:
        output = _run_git_blocking(repo_root, "ls-files", "--others", "--ignored", "--exclude-standard")
    except RuntimeError:
        return
    for rel in output.splitlines():
        if not rel:
            continue
        if not any(fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(Path(rel).name, pat) for pat in patterns):
            continue
        src = Path(repo_root) / rel
        dst = wt_path / rel
        if src.is_file() and not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)


def _run_git_blocking(repo_root: str, *args: str) -> str:
    """同步跑 git（用于设置 D 的 ls-files）。失败抛 RuntimeError。"""
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": ""}
    proc = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip())
    return proc.stdout
