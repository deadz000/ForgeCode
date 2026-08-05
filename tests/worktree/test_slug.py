"""worktree.slug 单测：validate_slug 合法/非法 case + flat_slug（spec F1）。"""

from __future__ import annotations

import pytest

from forgecode.worktree import flat_slug, validate_slug


@pytest.mark.parametrize("name", ["alice", "team/alice", "v1.0", "a_b", "a-b", "A.B-c"])
def test_valid_slugs(name: str) -> None:
    validate_slug(name)  # 不抛即通过


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "a" * 65,
        "..",
        "./x",
        "a//b",
        "/x",
        "a/",
        "a b",
        "a;b",
        "a/b ",
        "团队/alice",
    ],
)
def test_invalid_slugs(bad: str) -> None:
    with pytest.raises(ValueError):
        validate_slug(bad)


def test_flat_slug_single() -> None:
    assert flat_slug("alice") == "alice"


def test_flat_slug_nested() -> None:
    assert flat_slug("team/alice") == "team+alice"
    assert flat_slug("team/feature/alice") == "team+feature+alice"


def test_flat_slug_error_message() -> None:
    with pytest.raises(ValueError, match=".."):
        validate_slug("../etc")
