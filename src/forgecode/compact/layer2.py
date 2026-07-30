"""第 2 层 LLM 摘要：结构化摘要 + 恢复段 + 近期原文边界裁剪 + PTL 自重试 + 熔断计数。"""

from __future__ import annotations

import logging
import math

from forgecode.compact.const import (
    PTL_DROP_PERCENTAGE,
    PTL_RETRY_LIMIT,
    RECENT_KEEP_MESSAGES,
    RECENT_KEEP_TOKENS,
)
from forgecode.compact.recovery import build_recovery_attachment
from forgecode.compact.summary_prompt import build_summary_prompt, extract_summary
from forgecode.compact.token import estimate_tokens, message_chars
from forgecode.conversation.history import Message
from forgecode.providers import PromptTooLongError, Request

logger = logging.getLogger(__name__)

# ── 近期原文选择 ───────────────────────────────────


def pick_recent_tail(msgs: list[Message]) -> list[Message]:
    """从 msgs 尾部累加，两个下界都满足后停止。

    - 累计估算 token ≥ RECENT_KEEP_TOKENS
    - 累计消息数 ≥ RECENT_KEEP_MESSAGES
    再做 tool_use/tool_result 配对修正。
    """
    if not msgs:
        return []

    acc_tokens = 0
    acc_count = 0
    start_idx = len(msgs)

    for i in range(len(msgs) - 1, -1, -1):
        acc_tokens += math.ceil(message_chars([msgs[i]]) / 3.5)
        acc_count += 1
        start_idx = i
        if acc_tokens >= RECENT_KEEP_TOKENS and acc_count >= RECENT_KEEP_MESSAGES:
            break

    # 配对修正：若截断点夹在 tool_use / tool_result 中间，前推到 tool_use 之前
    while start_idx < len(msgs) and msgs[start_idx].role == "tool":
        # 前推到上一个带 tool_calls 的 assistant 消息
        j = start_idx - 1
        while j >= 0 and msgs[j].role == "tool":
            j -= 1
        if j >= 0 and msgs[j].role == "assistant" and msgs[j].tool_calls:
            start_idx = j
        else:
            break

    return msgs[start_idx:]


# ── 按用户轮次分组 ────────────────────────────────


def group_by_user_turn(msgs: list[Message]) -> list[list[Message]]:
    """按"用户提交 → 一组 assistant/tool 往返"分组。

    每遇到 role=="user" 开新组；第一条不是 user 时单独塞进第 0 组。
    """
    if not msgs:
        return []

    groups: list[list[Message]] = []
    current: list[Message] = []

    for m in msgs:
        if m.role == "user" and current:
            groups.append(current)
            current = []
        current.append(m)

    if current:
        groups.append(current)

    return groups


# ── 衔接修正 ──────────────────────────────────────


def _join_after_summary(summary_msg: Message, recent: list[Message]) -> list[Message]:
    """拼接摘要+恢复段与近期原文，保证 Anthropic user/assistant 交替约束。"""
    if not recent:
        return [summary_msg]

    result: list[Message] = [summary_msg]

    if recent[0].role == "user":
        # 插入 assistant 衔接占位
        result.append(Message(role="assistant", content="（已加载上下文摘要与恢复信息。请继续。）"))
    elif recent[0].role == "tool":
        # 防御性修正：前移到第一条非 tool 消息
        skip = 0
        while skip < len(recent) and recent[skip].role == "tool":
            skip += 1
        if skip < len(recent):
            recent = recent[skip:]

    result.extend(recent)
    return result


# ── 单次摘要请求 ─────────────────────────────────


async def summarize_once(in_, msgs: list[Message]) -> str:
    """发一次摘要请求。tools 为空，不使用系统提示。"""
    prompt_msgs = build_summary_prompt(msgs)
    req = Request(messages=prompt_msgs, tools=[])

    text_buf: list[str] = []
    async for ev in in_.provider.stream(req):
        if ev.err is not None:
            raise ev.err
        if ev.text:
            text_buf.append(ev.text)
        # 摘要请求的 usage 不回写 SessionRuntime.usage_anchor

    return extract_summary("".join(text_buf))


# ── PTL 自重试 ───────────────────────────────────


async def ptl_retry(in_, msgs: list[Message], first_err: Exception) -> str:
    """摘要请求自重试：按消息组丢弃策略，直到成功或耗尽。

    - 前 PTL_RETRY_LIMIT 次重试：每次丢最旧 1 组
    - 之后：每次按 PTL_DROP_PERCENTAGE 丢（至少 1 组）
    - 全部丢光仍失败：抛最后一次异常
    """
    groups = group_by_user_turn(msgs)
    retry_count = 0

    while True:
        if not groups:
            raise first_err

        if 0 < retry_count <= PTL_RETRY_LIMIT:
            # 丢最旧 1 组
            groups = groups[1:]
        elif retry_count > PTL_RETRY_LIMIT:
            # 按比例丢
            drop = max(1, math.ceil(len(groups) * PTL_DROP_PERCENTAGE))
            groups = groups[drop:]

        if not groups:
            raise first_err

        flat: list[Message] = [m for g in groups for m in g]
        try:
            return await summarize_once(in_, flat)
        except PromptTooLongError as e:
            first_err = e
            retry_count += 1
            continue
        # 非 PTL 异常直接上抛


# ── 摘要 + 恢复 + 拼接 ───────────────────────────


async def run_summary(in_) -> list[Message]:
    """执行一次完整摘要：摘要请求 → 解析 → 恢复段 → 近期原文 → 拼接。

    返回新的消息列表，不修改入参。
    """
    old_msgs = in_.conv.messages

    # 入口拍快照
    recovery_snapshot = in_.recovery.snapshot()

    # 摘要请求（含 PTL 自重试）
    try:
        summary_text = await summarize_once(in_, old_msgs)
    except PromptTooLongError as e:
        summary_text = await ptl_retry(in_, old_msgs, e)

    # 恢复段
    recovery_text = build_recovery_attachment(recovery_snapshot, in_.tool_defs)

    # 合并摘要与恢复
    combined = "## 历史会话摘要\n" + summary_text + "\n\n" + recovery_text
    summary_msg = Message(role="user", content=combined)

    # 近期原文
    recent_tail = pick_recent_tail(old_msgs)

    return _join_after_summary(summary_msg, recent_tail)


# ── auto_compact / force_compact ──────────────────


async def auto_compact(in_) -> tuple[list[Message], int, int]:
    """自动摘要：熔断器未触发时执行，成功后清零，失败累加。"""
    before_tok = in_.estimated_token
    try:
        new_msgs = await run_summary(in_)
    except Exception:
        in_.auto_tracking.record_failure()
        raise
    in_.auto_tracking.record_success()
    after_tok = estimate_tokens(0, new_msgs, 0)
    return (new_msgs, before_tok, after_tok)


async def force_compact(in_) -> tuple[list[Message], int, int]:
    """手动/紧急摘要：跳过熔断器，失败不计入熔断。"""
    before_tok = in_.estimated_token
    new_msgs = await run_summary(in_)
    after_tok = estimate_tokens(0, new_msgs, 0)
    return (new_msgs, before_tok, after_tok)
