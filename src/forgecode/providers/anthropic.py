"""Anthropic Claude Provider：流式对话 + 工具调用 + 缓存断点。"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx
from anthropic import APIStatusError, AsyncAnthropic

from forgecode.config.schema import ProviderConfig
from forgecode.conversation.history import (
    ROLE_ASSISTANT,
    ROLE_TOOL,
    ROLE_USER,
    Message,
    ToolCall,
)
from forgecode.providers import (
    BaseProvider,
    PromptTooLongError,
    Request,
    StreamEvent,
    Usage,
    ensure_object_schema,
)


class AnthropicProvider(BaseProvider):
    """封装 AsyncAnthropic，实现流式对话、extended thinking、缓存断点和工具调用。"""

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        self.client = AsyncAnthropic(
            base_url=config.base_url,
            api_key=config.api_key,
            timeout=60.0,  # 60s 无响应即报错，避免 API 不通时无限挂起
        )

    def stream(self, req: Request) -> AsyncIterator[StreamEvent]:
        return self._stream_impl(req)

    async def _stream_impl(self, req: Request) -> AsyncIterator[StreamEvent]:
        # ── 构造 system（两块：stable 打断点，env 不打断点）──
        system_blocks: list[dict] = []
        if req.system.stable:
            system_blocks.append(
                {
                    "type": "text",
                    "text": req.system.stable,
                    "cache_control": {"type": "ephemeral"},
                }
            )
        if req.system.environment:
            system_blocks.append(
                {
                    "type": "text",
                    "text": req.system.environment,
                }
            )

        # ── 转换消息 ──
        api_messages = _to_anthropic_messages(req.messages)

        # ── 织入 reminder ──
        if req.reminder:
            _append_reminder_anthropic(api_messages, req.reminder)

        has_tool_history = any(m.role == ROLE_TOOL or m.tool_calls for m in req.messages)

        params: dict = {
            "model": self.config.model,
            "max_tokens": 4096,
            "messages": api_messages,
            "system": system_blocks,
        }

        # 工具定义注入
        if req.tools:
            params["tools"] = [
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": ensure_object_schema(t.input_schema),
                }
                for t in req.tools
            ]

        # 含工具历史的请求不启用 thinking（避免 400）
        if self.config.thinking and not has_tool_history:
            params["thinking"] = {"type": "enabled", "budget_tokens": 2048}

        for attempt in range(2):
            try:
                async with self.client.messages.stream(**params) as stream:
                    async for event in stream:
                        if event.type == "content_block_delta":
                            if event.delta.type == "text_delta":
                                yield StreamEvent(text=event.delta.text)
                            elif event.delta.type == "thinking_delta":
                                yield StreamEvent(thinking=event.delta.thinking)
                            # input_json_delta → 跳过（SDK 内部累加）

                    # 流结束后取工具调用 + token 用量
                    final_message = await stream.get_final_message()
                    calls: list[ToolCall] = []
                    for block in final_message.content:
                        if block.type == "tool_use":
                            calls.append(
                                ToolCall(
                                    id=block.id,
                                    name=block.name,
                                    input=json.dumps(block.input),
                                )
                            )
                    if calls:
                        yield StreamEvent(tool_calls=calls)

                    # 提取 token 用量（含缓存字段）
                    if final_message.usage is not None:
                        yield StreamEvent(
                            usage=Usage(
                                input_tokens=final_message.usage.input_tokens,
                                output_tokens=final_message.usage.output_tokens,
                                cache_write=getattr(
                                    final_message.usage,
                                    "cache_creation_input_tokens",
                                    0,
                                )
                                or 0,
                                cache_read=getattr(
                                    final_message.usage,
                                    "cache_read_input_tokens",
                                    0,
                                )
                                or 0,
                            )
                        )

                    yield StreamEvent(done=True)
                return

            except APIStatusError as e:
                if e.status_code < 500:
                    # 检查是否为 PTL 错误
                    msg = str(e.message).lower() if hasattr(e, "message") else str(e).lower()
                    if "prompt is too long" in msg or "context_length" in msg:
                        wrapped = PromptTooLongError("anthropic prompt too long")
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


def _to_anthropic_messages(msgs: list[Message]) -> list[dict]:
    """将内部 Message 列表转为 Anthropic API 格式。"""
    result: list[dict] = []
    for m in msgs:
        if m.role == ROLE_USER:
            result.append({"role": "user", "content": m.content})
        elif m.role == ROLE_ASSISTANT:
            if m.tool_calls:
                # assistant 回合含工具调用：content 用数组
                content_blocks: list[dict] = []
                if m.content:
                    content_blocks.append({"type": "text", "text": m.content})
                for c in m.tool_calls:
                    content_blocks.append(
                        {
                            "type": "tool_use",
                            "id": c.id,
                            "name": c.name,
                            "input": json.loads(c.input),
                        }
                    )
                result.append({"role": "assistant", "content": content_blocks})
            else:
                result.append({"role": "assistant", "content": m.content})
        elif m.role == ROLE_TOOL:
            # 工具结果打包进一条 user 消息的 content 数组
            blocks: list[dict] = []
            for r in m.tool_results:
                blocks.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": r.tool_call_id,
                        "content": r.content,
                        "is_error": r.is_error,
                    }
                )
            result.append({"role": "user", "content": blocks})
    return result


def _append_reminder_anthropic(messages: list[dict], reminder: str) -> None:
    """将 reminder 织入最后一条消息的 content 块。

    - 末条为 user（content 为 list 或 str）→ 追加文本块。
    - 末条非 user（极端情形）→ 新起一条 user 消息。
    """
    if not messages:
        messages.append({"role": "user", "content": reminder})
        return

    last = messages[-1]
    if last.get("role") != "user":
        messages.append({"role": "user", "content": reminder})
        return

    content = last["content"]
    if isinstance(content, str):
        last["content"] = [
            {"type": "text", "text": content},
            {"type": "text", "text": reminder},
        ]
    elif isinstance(content, list):
        content.append({"type": "text", "text": reminder})
