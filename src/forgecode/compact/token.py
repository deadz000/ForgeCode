"""Token 估算：锚定真实 usage + 字符增量，纯函数无副作用。"""

from __future__ import annotations

import json
import math

from forgecode.compact.const import ESTIMATE_CHARS_PER_TOKEN
from forgecode.conversation.history import Message
from forgecode.providers import Usage


def usage_anchor(u: Usage) -> int:
    """把 stream 尾事件中的 usage 合并成单一锚点值。

    等价于 u.input_tokens + u.output_tokens + u.cache_read + u.cache_write。
    """
    return u.input_tokens + u.output_tokens + u.cache_read + u.cache_write


def message_chars(msgs: list[Message]) -> int:
    """计算消息列表的 UTF-8 字节总量（用于 token 增量估算）。

    遍历每条消息累加：
    - content 的 UTF-8 字节长度
    - 每个 tool_calls[i].input 序列化后的字节长度
    - 每个 tool_results[i].content 的字节长度
    """
    total = 0
    for m in msgs:
        if m.content:
            total += len(m.content.encode("utf-8"))
        for tc in m.tool_calls:
            inp = tc.input
            if isinstance(inp, str):
                total += len(inp.encode("utf-8"))
            else:
                total += len(json.dumps(inp).encode("utf-8"))
        for tr in m.tool_results:
            if tr.content:
                total += len(tr.content.encode("utf-8"))
    return total


def estimate_tokens(anchor: int, all_msgs: list[Message], anchor_msg_len: int) -> int:
    """锚定最近一次 provider usage + 之后新增消息的字符增量。

    入参语义:
    - anchor: 上一次主对话路径 stream 真实 usage 之和(int);
    - all_msgs: 当前 conv.messages 完整列表;
    - anchor_msg_len: 当 anchor 被记录时 conv.length() 的值;
    - 函数只把 all_msgs[anchor_msg_len:] 这部分的字符累加，避免重复计算历史。
    - 入参 all_msgs 必须是已经经过 layer1 处理的消息列表，否则估算偏高。
    - 返回 anchor + math.ceil(sum(chars(msg)) / ESTIMATE_CHARS_PER_TOKEN)。

    锚点为 0、anchor_msg_len 为 0 时退化为纯字符估算。
    """
    start = max(0, anchor_msg_len)
    tail = all_msgs[start:]
    if not tail:
        return anchor
    return anchor + math.ceil(message_chars(tail) / ESTIMATE_CHARS_PER_TOKEN)
