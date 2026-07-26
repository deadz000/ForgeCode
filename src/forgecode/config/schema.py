from dataclasses import dataclass


@dataclass
class ProviderConfig:
    """单个供应商配置。"""

    name: str
    protocol: str  # "anthropic" | "openai"
    model: str
    base_url: str
    api_key: str
    thinking: bool = False


@dataclass
class AppConfig:
    """应用完整配置。"""

    providers: list[ProviderConfig]
    active_provider_name: str
