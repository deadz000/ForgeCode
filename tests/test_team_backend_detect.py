"""team.backend.detect 单测。"""

from __future__ import annotations

import shutil

import pytest

from forgecode.team.backend.detect import detect
from forgecode.team.types import BackendType


def test_tmux_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TMUX", "/tmp/tmux.sock")
    monkeypatch.delenv("TERM_PROGRAM", raising=False)
    assert detect() is BackendType.TMUX


def test_iterm2(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.setenv("TERM_PROGRAM", "iTerm.app")
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/local/bin/it2" if name == "it2" else None)
    assert detect() is BackendType.ITERM2


def test_iterm2_without_it2(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.setenv("TERM_PROGRAM", "iTerm.app")
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert detect() is BackendType.IN_PROCESS


def test_tmux_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.delenv("TERM_PROGRAM", raising=False)
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/tmux" if name == "tmux" else None)
    assert detect() is BackendType.TMUX


def test_fallback_in_process(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.delenv("TERM_PROGRAM", raising=False)
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert detect() is BackendType.IN_PROCESS
