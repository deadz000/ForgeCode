"""Provider 模块测试。"""

import pytest

from forgecode.config.schema import ProviderConfig
from forgecode.providers import (
    ErrorEvent,
    TextDelta,
    ThinkingDelta,
    ThinkingEnd,
    ThinkingStart,
    create_provider,
)
from forgecode.providers.anthropic import AnthropicProvider
from forgecode.providers.openai import OpenAIProvider


def test_stream_event_types():
    td = TextDelta(text="hello")
    assert td.text == "hello"

    ts = ThinkingStart()
    assert ts is not None

    td2 = ThinkingDelta(text="thinking...")
    assert td2.text == "thinking..."

    te = ThinkingEnd()
    assert te is not None

    ee = ErrorEvent(message="err", retryable=True)
    assert ee.message == "err"
    assert ee.retryable is True


def test_create_anthropic_provider():
    cfg = ProviderConfig(
        name="test", protocol="anthropic", model="claude-sonnet-5",
        base_url="https://api.anthropic.com", api_key="sk-test",
    )
    p = create_provider(cfg)
    assert isinstance(p, AnthropicProvider)
    assert p.config.model == "claude-sonnet-5"


def test_create_openai_provider():
    cfg = ProviderConfig(
        name="test", protocol="openai", model="gpt-4o",
        base_url="https://api.openai.com/v1", api_key="sk-test",
    )
    p = create_provider(cfg)
    assert isinstance(p, OpenAIProvider)
    assert p.config.model == "gpt-4o"


def test_create_provider_unsupported():
    cfg = ProviderConfig(
        name="test", protocol="unknown", model="m",
        base_url="b", api_key="k",
    )
    with pytest.raises(ValueError, match="不支持的协议类型"):
        create_provider(cfg)
