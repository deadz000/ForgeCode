"""会话加载恢复：从 JSONL 重建消息列表，含容错处理。"""

from __future__ import annotations

import json
import logging
import os

from forgecode.conversation.history import (
    ROLE_ASSISTANT,
    ROLE_TOOL,
    ROLE_USER,
    Message,
    ToolCall,
    ToolResult,
)

logger = logging.getLogger(__name__)


def load_session(session_dir: str) -> list[Message]:
    """从 conversation.jsonl 恢复消息列表。

    容错策略：
    - 从最后一个 compact 标记之后开始加载
    - JSON 解析失败的行静默跳过
    - 末尾孤立 tool_calls（assistant 有 tool_calls 但无后续 tool 消息）截断
    """
    jsonl_path = os.path.join(session_dir, "conversation.jsonl")
    if not os.path.isfile(jsonl_path):
        return []

    # 逐行读取，compact 标记后的行从头开始累积
    raw_lines: list[dict] = []

    try:
        with open(jsonl_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning("JSONL 坏行跳过: %.100s...", line[:100])
                    continue

                # 检查 compact 标记
                if data.get("type") == "compact":
                    raw_lines.clear()  # 从 compact 后重新开始
                    continue

                raw_lines.append(data)
    except OSError:
        logger.warning("读取 JSONL 失败: %s", jsonl_path, exc_info=True)
        return []

    # 转换为 Message 对象
    msgs: list[Message] = []
    for data in raw_lines:
        msg = _dict_to_message(data)
        if msg is not None:
            msgs.append(msg)

    # 截断孤立 tool_calls
    msgs = _truncate_orphaned_tool_calls(msgs)

    return msgs


def _truncate_orphaned_tool_calls(msgs: list[Message]) -> list[Message]:
    """如果最后一条是 assistant 且有 tool_calls，则截断掉该条。

    这意味着模型请求了工具但结果未写入 JSONL（崩溃/中断）。
    """
    if not msgs:
        return msgs

    last = msgs[-1]
    if last.role == ROLE_ASSISTANT and last.tool_calls:
        # 检查后面是否有 tool 消息
        # 已经是最后一条 → 截断
        return msgs[:-1]

    return msgs


def _dict_to_message(data: dict) -> Message | None:
    """将 JSONL 中一行 dict 转为 Message 对象。"""
    role = data.get("role", "")
    if role not in (ROLE_USER, ROLE_ASSISTANT, ROLE_TOOL):
        return None

    content = data.get("content", "")
    if not isinstance(content, str):
        content = ""

    tool_calls: list[ToolCall] = []
    raw_calls = data.get("tool_calls")
    if isinstance(raw_calls, list):
        for c in raw_calls:
            if isinstance(c, dict):
                tool_calls.append(
                    ToolCall(
                        id=str(c.get("id", "")),
                        name=str(c.get("name", "")),
                        input=str(c.get("input", "")),
                    )
                )

    tool_results: list[ToolResult] = []
    raw_results = data.get("tool_results")
    if isinstance(raw_results, list):
        for r in raw_results:
            if isinstance(r, dict):
                tool_results.append(
                    ToolResult(
                        tool_call_id=str(r.get("tool_call_id", "")),
                        content=str(r.get("content", "")),
                        is_error=bool(r.get("is_error", False)),
                    )
                )

    return Message(
        role=role,  # type: ignore[arg-type]
        content=content,
        tool_calls=tool_calls,
        tool_results=tool_results,
    )
