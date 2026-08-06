"""coordinator 单测：双锁 4 种组合 + 白名单 + 提示词。"""

from __future__ import annotations

import pytest

from forgecode.coordinator import allowed_tools, env_truthy, is_enabled, system_prompt_suffix
from forgecode.config.schema import FeaturesConfig


class _Cfg:
    def __init__(self, coordinator_mode: bool) -> None:
        self.features = FeaturesConfig(coordinator_mode=coordinator_mode)


def test_env_truthy() -> None:
    assert env_truthy("1") is True
    assert env_truthy("true") is True
    assert env_truthy("TRUE") is True
    assert env_truthy("yes") is True
    assert env_truthy("0") is False
    assert env_truthy("") is False
    assert env_truthy("random") is False


def test_double_lock_combinations(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORGECODE_COORDINATOR_MODE", "0")
    assert is_enabled(_Cfg(False)) is False
    assert is_enabled(_Cfg(True)) is False
    monkeypatch.setenv("FORGECODE_COORDINATOR_MODE", "1")
    assert is_enabled(_Cfg(False)) is False
    assert is_enabled(_Cfg(True)) is True


def test_allowed_tools() -> None:
    tools = allowed_tools()
    assert "bash" in tools
    assert "read_file" in tools
    assert "write_file" not in tools
    assert "edit_file" not in tools
    assert "Agent" in tools
    assert "TeamCreate" in tools
    assert "SendMessage" in tools


def test_system_prompt_suffix() -> None:
    s = system_prompt_suffix()
    assert "派完队员就停手" in s
    assert "Coordinator" in s
    assert "Research" in s
    assert "Verification" in s
