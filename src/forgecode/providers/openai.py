"""OpenAI Provider 实现。"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
from openai import APIStatusError, AsyncOpenAI

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


class OpenAIProvider(BaseProvider):
    """封装 AsyncOpenAI，实现流式对话。"""

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        self.client = AsyncOpenAI(
            base_url=config.base_url,
            api_key=config.api_key,
        )

    async def chat_stream(self, messages: list[Message]) -> AsyncIterator[StreamEvent]:  # type: ignore[override,misc]
        # 转换消息格式
        api_messages: list[dict[str, str]] = [
            {"role": m.role, "content": m.content} for m in messages
        ]

        # 流式调用，带重试
        for attempt in range(2):
            try:
                stream = await self.client.chat.completions.create(  # type: ignore[call-overload]
                    model=self.config.model,
                    messages=api_messages,
                    stream=True,
                    stream_options={"include_usage": True},
                )
                thinking_started = False
                thinking_ended = False

                async for chunk in stream:
                    if not chunk.choices:
                        continue

                    delta = chunk.choices[0].delta

                    # 处理 reasoning tokens（o-series 模型）
                    if hasattr(delta, "reasoning_content") and delta.reasoning_content:
                        if not thinking_started:
                            thinking_started = True
                            yield ThinkingStart()
                        yield ThinkingDelta(text=delta.reasoning_content)

                    # 处理普通文本
                    if delta.content:
                        if thinking_started and not thinking_ended:
                            thinking_ended = True
                            yield ThinkingEnd()
                        yield TextDelta(text=delta.content)

                if thinking_started and not thinking_ended:
                    yield ThinkingEnd()

                return  # 成功

            except APIStatusError as e:
                if e.status_code < 500:
                    msg = f"API 错误 ({e.status_code}): {e.message}"
                    yield ErrorEvent(message=msg, retryable=False)
                    return
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
