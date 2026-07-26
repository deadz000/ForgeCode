"""Provider 抽象层：定义统一流式对话接口。

新增后端只需继承 BaseProvider 并实现 chat_stream()，
然后在 create_provider() 中添加分支即可。
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass

from forgecode.config.schema import ProviderConfig
from forgecode.conversation.history import Message

# ── 流式事件类型 ──────────────────────────────────


@dataclass
class TextDelta:
    """一个文本 token。"""
    text: str


@dataclass
class ThinkingStart:
    """思考块开始。"""
    pass


@dataclass
class ThinkingDelta:
    """一个思考 token。"""
    text: str


@dataclass
class ThinkingEnd:
    """思考块结束。"""
    pass


@dataclass
class ErrorEvent:
    """流式过程中的错误。"""
    message: str
    retryable: bool


# 联合类型
StreamEvent = TextDelta | ThinkingStart | ThinkingDelta | ThinkingEnd | ErrorEvent


# ── 抽象基类 ──────────────────────────────────────


class BaseProvider(ABC):
    """流式对话 Provider 抽象基类。"""

    def __init__(self, config: ProviderConfig) -> None:
        self.config = config

    @abstractmethod
    async def chat_stream(self, messages: list[Message]) -> AsyncIterator[StreamEvent]:
        """
        接收对话历史，返回流式事件序列。

        事件顺序约定：
        - ThinkingStart → ThinkingDelta* → ThinkingEnd → TextDelta* → 流结束
        - 如果 thinking=False 或无思考内容，直接 TextDelta*
        - 出错时 yield ErrorEvent，不抛异常
        """
        ...


# ── 工厂函数 ──────────────────────────────────────


def create_provider(config: ProviderConfig) -> BaseProvider:
    """根据协议类型创建对应的 Provider 实例。"""
    from forgecode.providers.anthropic import AnthropicProvider
    from forgecode.providers.openai import OpenAIProvider

    protocol = config.protocol.lower()
    if protocol == "anthropic":
        return AnthropicProvider(config)
    if protocol == "openai":
        return OpenAIProvider(config)
    raise ValueError(f"不支持的协议类型: {config.protocol}，仅支持 anthropic / openai")
