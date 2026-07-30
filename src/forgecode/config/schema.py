from dataclasses import dataclass

from forgecode.config.protocol_defaults import (
    DEFAULT_ANTHROPIC_CONTEXT_WINDOW,
    DEFAULT_OPENAI_CONTEXT_WINDOW,
)


@dataclass
class ProviderConfig:
    """单个供应商配置。"""

    name: str
    protocol: str  # "anthropic" | "openai"
    model: str
    base_url: str
    api_key: str
    thinking: bool = False
    # 上下文窗口 token 数，0 表示走协议默认
    context_window: int = 0


def effective_context_window(p: ProviderConfig) -> int:
    """返回 provider 的有效上下文窗口值。

    配置 > 0 返回配置值；否则按 protocol 给默认值。
    """
    if p.context_window > 0:
        return p.context_window
    if p.protocol == "anthropic":
        return DEFAULT_ANTHROPIC_CONTEXT_WINDOW
    if p.protocol == "openai":
        return DEFAULT_OPENAI_CONTEXT_WINDOW
    # 未知 protocol 保守默认
    return DEFAULT_ANTHROPIC_CONTEXT_WINDOW


@dataclass
class AppConfig:
    """应用完整配置。"""

    providers: list[ProviderConfig]
    active_provider_name: str
