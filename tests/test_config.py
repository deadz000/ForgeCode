"""配置模块测试。"""

import pytest

from forgecode.config.loader import _merge_configs, _parse_providers
from forgecode.config.schema import AppConfig, ProviderConfig


def test_provider_config_defaults():
    cfg = ProviderConfig(
        name="test",
        protocol="openai",
        model="gpt-4o",
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
    )
    assert cfg.thinking is False


def test_app_config():
    providers = [
        ProviderConfig(
            name="p1",
            protocol="anthropic",
            model="m1",
            base_url="b1",
            api_key="k1",
        )
    ]
    cfg = AppConfig(providers=providers, active_provider_name="p1")
    assert len(cfg.providers) == 1
    assert cfg.active_provider_name == "p1"


def test_parse_providers_valid():
    data = {
        "providers": [
            {
                "name": "test",
                "protocol": "openai",
                "model": "gpt-4o",
                "base_url": "https://api.openai.com/v1",
                "api_key": "sk-test",
            }
        ]
    }
    result = _parse_providers(data)
    assert len(result) == 1
    assert result[0].name == "test"
    assert result[0].protocol == "openai"


def test_parse_providers_empty():
    assert _parse_providers({}) == []
    assert _parse_providers({"providers": []}) == []


def test_parse_providers_missing_field():
    data = {"providers": [{"name": "test"}]}
    with pytest.raises(ValueError, match="缺少必填字段"):
        _parse_providers(data)


def test_merge_configs_empty():
    assert _merge_configs(None, None) == []


def test_merge_configs_global_only():
    global_data = {
        "providers": [
            {"name": "g", "protocol": "openai", "model": "m", "base_url": "b", "api_key": "k"},
        ]
    }
    result = _merge_configs(global_data, None)
    assert len(result) == 1
    assert result[0].name == "g"


def test_merge_configs_project_overrides_global():
    global_data = {
        "providers": [
            {
                "name": "same",
                "protocol": "openai",
                "model": "global-model",
                "base_url": "b",
                "api_key": "k",
            },
            {
                "name": "only-global",
                "protocol": "anthropic",
                "model": "m",
                "base_url": "b",
                "api_key": "k",
            },
        ]
    }
    project_data = {
        "providers": [
            {
                "name": "same",
                "protocol": "openai",
                "model": "project-model",
                "base_url": "b2",
                "api_key": "k2",
            },
        ]
    }
    result = _merge_configs(global_data, project_data)
    names = {p.name for p in result}
    assert names == {"same", "only-global"}
    same = next(p for p in result if p.name == "same")
    assert same.model == "project-model"
