"""Git 子进程 helper：_run_git、_has_worktree_changes、_resolve_head_sha_from_fs。

统一环境变量（GIT_TERMINAL_PROMPT=0 / GIT_ASKPASS=""）+ stdin 关闭，
避免 Worktree 创建 / 删除过程中任何交互式 git 提示挂起。
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path


async def _run_git(work_dir: str, *args: str) -> str:
    """在 work_dir 下执行 git 命令，返回 stdout（rstrip 换行）。失败抛 RuntimeError(stderr)。"""
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": ""}
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=work_dir,
        env=env,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_b, stderr_b = await proc.communicate()
    stdout = stdout_b.decode("utf-8", errors="replace").rstrip("\n")
    if proc.returncode != 0:
        stderr = stderr_b.decode("utf-8", errors="replace").rstrip("\n")
        raise RuntimeError(f"git {' '.join(args)} 失败: {stderr}")
    return stdout


async def _has_worktree_changes(wt_path: str, base_commit: str) -> bool:
    """Worktree 是否有未提交修改或本地多于 base 的 commit（fail-closed）。

    任一 git 命令本身出错 → 返回 True（宁可保留）。
    """
    try:
        status = await _run_git(wt_path, "status", "--porcelain")
        if status:
            return True
        count = await _run_git(wt_path, "rev-list", "--count", f"{base_commit}..HEAD")
        return int(count.strip() or "0") > 0
    except Exception:
        return True


def _git_common_dir(gitdir: Path) -> Path:
    """读取 gitdir/commondir 定位共享 refs 所在目录；无则用 gitdir 本身。"""
    cd = gitdir / "commondir"
    if cd.exists():
        raw = cd.read_text(encoding="utf-8").strip()
        if raw:
            p = Path(raw)
            if not p.is_absolute():
                p = gitdir / p
            return p.resolve()
    return gitdir


def _resolve_head_sha_from_fs(wt_path: str) -> str | None:
    """纯文件系统读还原 Worktree 当前 HEAD SHA（快速恢复，不调 git）。

    读取 ``wt_path/.git``（worktree 内是文件）→ ``gitdir: <path>``，
    再读 ``<gitdir>/HEAD`` 与对应 ref 文件；ref 可能在 commondir 下。失败返回 None。
    """
    try:
        git_file = Path(wt_path) / ".git"
        if not git_file.exists():
            return None
        if git_file.is_dir():
            gitdir = git_file  # 普通仓库：.git 是目录
        else:
            content = git_file.read_text(encoding="utf-8").strip()
            if content.startswith("gitdir:"):
                gitdir = Path(content.split(":", 1)[1].strip())
            else:
                gitdir = git_file
        head = (gitdir / "HEAD").read_text(encoding="utf-8").strip()
        if head.startswith("ref:"):
            ref = head[4:].strip()  # refs/heads/xxx
            for base in (gitdir, _git_common_dir(gitdir)):
                ref_file = base / ref
                if ref_file.exists():
                    return ref_file.read_text(encoding="utf-8").strip()
            return None
        if head:  # detached HEAD：直接是 SHA
            return head
        return None
    except (OSError, UnicodeDecodeError):
        return None
