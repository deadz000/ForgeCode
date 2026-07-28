"""Provider 抽象层：统一流式对话接口 + 协议无关事件类型。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from forgecode.config.schema import ProviderConfig
from forgecode.conversation.history import Message, ToolDefinition

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
    tool_calls: list = field(default_factory=list)
    usage: Usage | None = None
    done: bool = False
    err: Exception | None = None


@dataclass
class Usage:
    """一次 API 调用的 token 用量（含缓存字段）。"""

    input_tokens: int = 0
    output_tokens: int = 0
    # Anthropic: cache_creation_input_tokens；OpenAI: 恒 0
    cache_write: int = 0
    # Anthropic: cache_read_input_tokens；OpenAI: cached_tokens
    cache_read: int = 0


# ── 请求结构 ──────────────────────────────────────


@dataclass
class System:
    """系统提示：分为可缓存稳定块与不可缓存环境块。"""

    stable: str = ""  # 可缓存：装配好的稳定系统提示
    environment: str = ""  # 不缓存：环境信息段


@dataclass
class Request:
    """一次 LLM 请求的完整入参。"""

    # 持久对话历史（不含本轮 reminder）
    messages: list[Message] = field(default_factory=list)
    # 本轮工具集（普通=全量 / 规划=只读）
    tools: list[ToolDefinition] = field(default_factory=list)
    # 稳定系统提示 + 环境段
    system: System = field(default_factory=System)
    # 本轮 system-reminder 内容（已含标签；空=不注入）
    reminder: str = ""


# ── 抽象基类 ──────────────────────────────────────


class BaseProvider(ABC):
    """流式对话 Provider 抽象基类。"""

    def __init__(self, config: ProviderConfig) -> None:
        self.config = config

    @abstractmethod
    def stream(self, req: Request) -> AsyncIterator[StreamEvent]:
        """
        流式对话。

        Request 承载全部入参：
        - messages: 持久对话历史
        - tools: 本轮工具定义集
        - system: 稳定系统提示(stable) + 环境信息(environment)
        - reminder: 本轮补充指令（已含标签；空=不注入）

        事件约定：
        - 文本增量由 StreamEvent.text 逐 token 产出
        - 工具调用在流结束前通过 StreamEvent.tool_calls 一次性产出
        - usage 非空：本轮 token 用量（含缓存写/读），done 之前一次性发出
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
    raise ValueError(f"不支持的协议类型: {config.protocol}，仅支持 anthropic / openai")
