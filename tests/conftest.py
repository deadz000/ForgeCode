"""共享测试 fixture：临时 git 仓库（供 worktree / agent_worktree 等测试使用）。"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


def _git(repo: Path, *args: str) -> str:
    """在 repo 下同步执行 git，失败抛 RuntimeError。"""
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": ""}
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        env=env,
        stdin=subprocess.DEVNULL,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """一个已初始化并有一次 commit 的临时 git 仓库（main 分支）。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("# repo\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "initial")
    return repo


@pytest.fixture
def git_repo_with_remote(tmp_path: Path, git_repo: Path) -> Path:
    """带 origin remote 且已 push 的临时仓库（供 sweep_stale 未推送判定用）。"""
    bare = tmp_path / "bare.git"
    _git(git_repo, "init", "--bare", str(bare))
    _git(git_repo, "remote", "add", "origin", str(bare))
    _git(git_repo, "push", "-u", "origin", "main")
    return git_repo
