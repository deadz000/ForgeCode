"""worktree.git 单测：_run_git / _has_worktree_changes / _resolve_head_sha_from_fs。"""

from __future__ import annotations

import pytest

from forgecode.worktree.git import _has_worktree_changes, _resolve_head_sha_from_fs, _run_git


@pytest.mark.asyncio
async def test_run_git_basic(git_repo) -> None:
    out = await _run_git(str(git_repo), "rev-parse", "--abbrev-ref", "HEAD")
    assert out == "main"


@pytest.mark.asyncio
async def test_run_git_error_raises(git_repo) -> None:
    with pytest.raises(RuntimeError):
        await _run_git(str(git_repo), "rev-parse", "no-such-ref")


@pytest.mark.asyncio
async def test_has_changes_no_change(git_repo) -> None:
    head = await _run_git(str(git_repo), "rev-parse", "HEAD")
    assert await _has_worktree_changes(str(git_repo), head) is False


@pytest.mark.asyncio
async def test_has_changes_dirty_file(git_repo) -> None:
    (git_repo / "dirty.txt").write_text("x", encoding="utf-8")
    head = await _run_git(str(git_repo), "rev-parse", "HEAD")
    assert await _has_worktree_changes(str(git_repo), head) is True


@pytest.mark.asyncio
async def test_has_changes_new_commit(git_repo) -> None:
    head = await _run_git(str(git_repo), "rev-parse", "HEAD")
    (git_repo / "new.txt").write_text("y", encoding="utf-8")
    await _run_git(str(git_repo), "add", ".")
    await _run_git(git_repo, "commit", "-m", "second")
    assert await _has_worktree_changes(str(git_repo), head) is True


@pytest.mark.asyncio
async def test_has_changes_fail_closed(git_repo) -> None:
    # base_commit 非法 → rev-list 出错 → fail-closed 返回 True
    assert await _has_worktree_changes(str(git_repo), "deadbeef") is True


@pytest.mark.asyncio
async def test_resolve_head_sha_from_fs(git_repo) -> None:
    wt = git_repo / "wt"
    await _run_git(str(git_repo), "worktree", "add", "-B", "wt-branch", str(wt), "HEAD")
    head = await _run_git(str(git_repo), "rev-parse", "HEAD")
    assert _resolve_head_sha_from_fs(str(wt)) == head


def test_resolve_head_sha_not_worktree(git_repo) -> None:
    assert _resolve_head_sha_from_fs(str(git_repo)) is not None  # 普通仓库也能解析
    assert _resolve_head_sha_from_fs(str(git_repo / "nonexistent")) is None
