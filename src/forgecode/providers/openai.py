"""OpenAI Provider：流式对话 + 工具调用。"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
from openai import APIStatusError, AsyncOpenAI

from forgecode.config.schema import ProviderConfig
from forgecode.conversation.history import (
    ROLE_ASSISTANT,
    ROLE_TOOL,
    ROLE_USER,
    ToolCall,
)
from forgecode.providers import BaseProvider, PromptTooLongError, Request, StreamEvent, Usage


class OpenAIProvider(BaseProvider):
    """封装 AsyncOpenAI，实现流式对话和工具调用。"""

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        self.client = AsyncOpenAI(
            base_url=config.base_url,
            api_key=config.api_key,
        )

    def stream(self, req: Request) -> AsyncIterator[StreamEvent]:
        return self._stream_impl(req)

    async def _stream_impl(self, req: Request) -> AsyncIterator[StreamEvent]:
        api_messages = _to_openai_messages(req)

        params: dict = {
            "model": self.config.model,
            "messages": api_messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }

        # 工具定义注入
        if req.tools:
            params["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.input_schema,
                    },
                }
                for t in req.tools
            ]

        for attempt in range(2):
            try:
                stream = await self.client.chat.completions.create(**params)

                # 按 index 累加 tool_calls 参数
                tool_calls_buf: dict[int, dict[str, str]] = {}
                usage_chunk = None

                async for chunk in stream:
                    # 捕获 usage 信息（include_usage 模式下最后 chunk 的 choices 为空）
                    if chunk.usage is not None:
                        usage_chunk = chunk.usage
                    if not chunk.choices:
                        continue

                    delta = chunk.choices[0].delta

                    # 文本增量
                    if delta.content:
                        yield StreamEvent(text=delta.content)

                    # 推理 tokens（o-series）
                    if hasattr(delta, "reasoning_content") and delta.reasoning_content:
                        yield StreamEvent(thinking=delta.reasoning_content)

                    # 工具调用增量
                    if delta.tool_calls:
                        for tc in delta.tool_calls:
                            idx = tc.index
                            if idx not in tool_calls_buf:
                                tool_calls_buf[idx] = {"id": "", "name": "", "args": ""}
                            buf = tool_calls_buf[idx]
                            if tc.id:
                                buf["id"] = tc.id
                            if tc.function and tc.function.name:
                                buf["name"] = tc.function.name
                            if tc.function and tc.function.arguments:
                                buf["args"] += tc.function.arguments

                # 流结束后组装 tool_calls
                if tool_calls_buf:
                    calls: list[ToolCall] = []
                    for idx in sorted(tool_calls_buf.keys()):
                        v = tool_calls_buf[idx]
                        calls.append(
                            ToolCall(
                                id=v["id"],
                                name=v["name"],
                                input=v["args"] or "{}",
                            )
                        )
                    yield StreamEvent(tool_calls=calls)

                # 提取 token 用量（含缓存字段）
                if usage_chunk is not None:
                    cache_read = 0
                    details = getattr(usage_chunk, "prompt_tokens_details", None)
                    if details is not None:
                        cache_read = getattr(details, "cached_tokens", 0) or 0
                    yield StreamEvent(
                        usage=Usage(
                            input_tokens=usage_chunk.prompt_tokens,
                            output_tokens=usage_chunk.completion_tokens,
                            cache_write=0,
                            cache_read=cache_read,
                        )
                    )

                yield StreamEvent(done=True)
                return

            except APIStatusError as e:
                if e.status_code < 500:
                    # 检查是否为 context_length_exceeded
                    code = getattr(e, "code", None)
                    if code == "context_length_exceeded":
                        wrapped = PromptTooLongError("openai context length exceeded")
                        wrapped.__cause__ = e
                        yield StreamEvent(err=wrapped)
                        return
                    yield StreamEvent(err=Exception(f"API 错误 ({e.status_code}): {e.message}"))
                    return
                if attempt == 1:
                    yield StreamEvent(err=Exception(f"服务器错误 ({e.status_code}): {e.message}"))
                    return

            except (httpx.HTTPError, httpx.NetworkError) as e:
                if attempt == 1:
                    yield StreamEvent(err=Exception(f"网络错误: {e}"))
                    return

            except Exception as e:
                yield StreamEvent(err=Exception(f"未知错误: {e}"))
                return


# ── 消息格式转换 ──────────────────────────────────


def _to_openai_messages(req: Request) -> list[dict]:
    """将 Request 转为 OpenAI API 消息格式。

    - 系统消息 = stable + env 拼接为单条（兼容端点对多条 system 支持不一）。
    - reminder 非空时追加一条尾部 user 消息。
    """
    # 构造系统消息：stable 在前（前缀缓存），env 在后
    system_parts: list[str] = []
    if req.system.stable:
        system_parts.append(req.system.stable)
    if req.system.environment:
        system_parts.append(req.system.environment)
    system_text = "\n\n".join(system_parts)

    result: list[dict] = []
    if system_text:
        result.append({"role": "system", "content": system_text})

    for m in req.messages:
        if m.role == ROLE_USER:
            result.append({"role": "user", "content": m.content})
        elif m.role == ROLE_ASSISTANT:
            entry: dict = {"role": "assistant"}
            if m.tool_calls:
                entry["content"] = m.content or None
                entry["tool_calls"] = [
                    {
                        "id": c.id,
                        "type": "function",
                        "function": {
                            "name": c.name,
                            "arguments": c.input,
                        },
                    }
                    for c in m.tool_calls
                ]
            else:
                entry["content"] = m.content
            result.append(entry)
        elif m.role == ROLE_TOOL:
            for r in m.tool_results:
                result.append(
                    {
                        "role": "tool",
                        "tool_call_id": r.tool_call_id,
                        "content": r.content,
                    }
                )

    # reminder 注入：追加尾部 user 消息（OpenAI 容忍连续 user）
    if req.reminder:
        result.append({"role": "user", "content": req.reminder})

    return result
