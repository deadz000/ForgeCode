"""manage_context 主入口：编排两层压缩调用顺序。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

from forgecode.compact.const import AUTO_SAFETY_MARGIN, SUMMARY_RESERVE
from forgecode.compact.layer1 import offload_and_snip
from forgecode.compact.layer2 import auto_compact, force_compact
from forgecode.compact.state import (
    CompactCircuitBreaker,
    ContentReplacementState,
    RecoveryState,
    SessionContext,
)
from forgecode.compact.token import estimate_tokens
from forgecode.conversation.history import Conversation, ToolDefinition
from forgecode.providers import BaseProvider

logger = logging.getLogger(__name__)


class TriggerKind(Enum):
    AUTO = "auto"
    MANUAL = "manual"
    EMERGENCY = "emergency"


@dataclass
class ManageInput:
    conv: Conversation
    provider: BaseProvider
    model: str
    context_window: int
    tool_defs: list[ToolDefinition]  # 与 stream 调用同一份列表引用
    replacement: ContentReplacementState
    recovery: RecoveryState
    auto_tracking: CompactCircuitBreaker
    session: SessionContext
    usage_anchor: int
    anchor_msg_len: int
    estimated_token: int
    trigger: TriggerKind


@dataclass
class ManageOutput:
    before_tokens: int
    after_tokens: int
    offloaded: int = 0  # 本轮 layer1 新落盘的工具结果数


async def manage_context(in_: ManageInput) -> ManageOutput:
    """Agent 每轮请求前必调的唯一入口。

    步骤：
    - MANUAL: 跳过 layer1/阈值/熔断，直接 force_compact
    - EMERGENCY: 先强制 layer1 再 force_compact
    - AUTO: layer1 → 重估 → 阈值判断 → 必要时 layer2
    """
    if in_.trigger == TriggerKind.MANUAL:
        new_msgs, before, after = await force_compact(in_)
        in_.conv.replace_history(new_msgs)
        return ManageOutput(before_tokens=before, after_tokens=after)

    if in_.trigger == TriggerKind.EMERGENCY:
        # 先强制 layer1 把大工具结果挪走
        layer1_out, offloaded = offload_and_snip(in_.conv.messages, in_.replacement, in_.session)
        in_.conv.replace_history(layer1_out)
        # 再 force_compact
        new_msgs, before, after = await force_compact(in_)
        in_.conv.replace_history(new_msgs)
        return ManageOutput(before_tokens=before, after_tokens=after, offloaded=offloaded)

    # ── AUTO 路径 ──
    # a. layer1
    layer1_out, offloaded = offload_and_snip(in_.conv.messages, in_.replacement, in_.session)
    in_.conv.replace_history(layer1_out)

    # b. 用 layer1 之后的消息重新估算
    est_tokens = estimate_tokens(in_.usage_anchor, layer1_out, in_.anchor_msg_len)

    # c. sanity check：context_window 过小跳过 layer2
    if in_.context_window <= SUMMARY_RESERVE + AUTO_SAFETY_MARGIN:
        logger.warning("context_window (%d) 过小，跳过自动 layer2", in_.context_window)
        return ManageOutput(before_tokens=in_.estimated_token, after_tokens=est_tokens, offloaded=offloaded)

    # d. 阈值判断
    threshold = in_.context_window - SUMMARY_RESERVE - AUTO_SAFETY_MARGIN
    if est_tokens < threshold or in_.auto_tracking.tripped():
        return ManageOutput(before_tokens=in_.estimated_token, after_tokens=est_tokens, offloaded=offloaded)

    # e. 触发 layer2
    new_msgs, before, after = await auto_compact(in_)
    in_.conv.replace_history(new_msgs)
    return ManageOutput(before_tokens=before, after_tokens=after, offloaded=offloaded)
