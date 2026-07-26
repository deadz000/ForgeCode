"""Provider 模块测试。"""

import pytest

from forgecode.config.schema import ProviderConfig
from forgecode.providers import StreamEvent, create_provider
from forgecode.providers.anthropic import AnthropicProvider
from forgecode.providers.openai import OpenAIProvider


def test_stream_event_defaults():
    se = StreamEvent()
    assert se.text == ""
    assert se.tool_calls == []
    assert not se.done
    assert se.err is None


def test_stream_event_text():
    se = StreamEvent(text="hello")
    assert se.text == "hello"


def test_stream_event_done():
    se = StreamEvent(done=True)
    assert se.done


def test_stream_event_err():
    err = Exception("test error")
    se = StreamEvent(err=err)
    assert se.err is err


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
