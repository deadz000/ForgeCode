"""Anthropic Claude Provider 实现。"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
from anthropic import APIStatusError, AsyncAnthropic

from forgecode.config.schema import ProviderConfig
from forgecode.conversation.history import Message
from forgecode.providers import (
    BaseProvider,
    ErrorEvent,
    StreamEvent,
    TextDelta,
    ThinkingDelta,
    ThinkingEnd,
    ThinkingStart,
)


class AnthropicProvider(BaseProvider):
    """封装 AsyncAnthropic，实现流式对话和 extended thinking。"""

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        self.client = AsyncAnthropic(
            base_url=config.base_url,
            api_key=config.api_key,
        )

    async def chat_stream(self, messages: list[Message]) -> AsyncIterator[StreamEvent]:  # type: ignore[override,misc]
        # 转换消息格式
        api_messages = [{"role": m.role, "content": m.content} for m in messages]

        # 构建请求参数
        kwargs: dict = {
            "model": self.config.model,
            "max_tokens": 4096,
            "messages": api_messages,
        }
        if self.config.thinking:
            kwargs["thinking"] = {"type": "enabled", "budget_tokens": 2048}

        # 流式调用，带重试
        for attempt in range(2):  # 首次 + 1 次重试
            try:
                async with self.client.messages.stream(**kwargs) as stream:
                    thinking_started = False
                    thinking_ended = False

                    async for event in stream:
                        if event.type == "thinking":
                            if not thinking_started:
                                thinking_started = True
                                yield ThinkingStart()
                            yield ThinkingDelta(text=event.thinking)

                        elif event.type == "text":
                            if thinking_started and not thinking_ended:
                                thinking_ended = True
                                yield ThinkingEnd()
                            yield TextDelta(text=event.text)

                    # 如果整轮都在思考但没产生文本（极少见）
                    if thinking_started and not thinking_ended:
                        yield ThinkingEnd()

                return  # 成功，退出重试循环

            except APIStatusError as e:
                if e.status_code < 500:
                    # 4xx 不重试
                    msg = f"API 错误 ({e.status_code}): {e.message}"
                    yield ErrorEvent(message=msg, retryable=False)
                    return
                # 5xx：重试
                if attempt == 1:
                    msg = f"服务器错误 ({e.status_code}): {e.message}"
                    yield ErrorEvent(message=msg, retryable=True)
                    return

            except (httpx.HTTPError, httpx.NetworkError) as e:
                if attempt == 1:
                    yield ErrorEvent(message=f"网络错误: {e}", retryable=True)
                    return

            except Exception as e:
                yield ErrorEvent(message=f"未知错误: {e}", retryable=False)
                return
