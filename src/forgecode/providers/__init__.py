"""Provider 抽象层：统一流式对话接口 + 协议无关事件类型。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from forgecode.config.schema import ProviderConfig
from forgecode.conversation.history import Message, ToolCall, ToolDefinition

# ── 流式事件 ──────────────────────────────────────


@dataclass
class StreamEvent:
    """流式事件（协议无关）。

    字段语义：
    - text 非空：文本增量（逐 token 产出）
    - thinking 非空：思考增量（逐 token 产出）
    - tool_calls 非空：本轮模型请求的工具调用列表（done 之前发出）
    - usage 非 None：本轮 token 用量（在 done 之前填充）
    - done=True：本轮流结束
    - err 非 None：出错（不中断会话，由上层处理）
    """

    text: str = ""
    thinking: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: TokenUsage | None = None
    done: bool = False
    err: Exception | None = None


@dataclass
class TokenUsage:
    """一次 API 调用的 token 用量。"""

    input_tokens: int = 0
    output_tokens: int = 0


# ── 抽象基类 ──────────────────────────────────────


class BaseProvider(ABC):
    """流式对话 Provider 抽象基类。"""

    def __init__(self, config: ProviderConfig) -> None:
        self.config = config

    @abstractmethod
    def stream(
        self,
        msgs: list[Message],
        tools: list[ToolDefinition],
    ) -> AsyncIterator[StreamEvent]:
        """
        流式对话。tools 为空列表表示不带工具，续答时仍传入（单轮由上层控制）。

        事件约定：
        - 文本增量由 StreamEvent.text 逐 token 产出
        - 工具调用在流结束前通过 StreamEvent.tool_calls 一次性产出
        - 流正常结束时产出 StreamEvent(done=True)
        - 出错时产出 StreamEvent(err=...)，不抛异常
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
    raise ValueError(
        f"不支持的协议类型: {config.protocol}，仅支持 anthropic / openai"
    )
