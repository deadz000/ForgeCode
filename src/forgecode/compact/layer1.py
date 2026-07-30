"""第 1 层预防性压缩：单条与单轮工具结果落盘 + 决策冻结。

纯函数风格，不修改入参；所有状态变更通过 ContentReplacementState 统一管理。
"""

from __future__ import annotations

import copy
import io
from pathlib import Path

from forgecode.compact.const import (
    MESSAGE_AGGREGATE_LIMIT,
    PREVIEW_HEAD_BYTES,
    PREVIEW_HEAD_LINES,
    SINGLE_RESULT_LIMIT,
)
from forgecode.compact.state import ContentReplacementState, SessionContext
from forgecode.conversation.history import Message

# ── 落盘 ───────────────────────────────────────────


def spill_single(session: SessionContext, tool_use_id: str, content: str) -> None:
    """把单条 tool_result 内容写入 spill_dir/<tool_use_id>。

    幂等：文件已存在则不重写、不报错。失败抛 OSError 由上层捕获。
    """
    path = Path(session.spill_dir) / tool_use_id
    if path.exists():
        return
    path.write_bytes(content.encode("utf-8"))


# ── 预览体构造 ─────────────────────────────────────


def _head_preview(content: str) -> str:
    """取工具结果的前 20 行或前 2048 字节中的较短者。"""
    lines = content.splitlines(keepends=True)
    if len(lines) > PREVIEW_HEAD_LINES:
        lines = lines[:PREVIEW_HEAD_LINES]
    head = "".join(lines)
    # 按字节二次裁剪，注意 UTF-8 边界对齐
    encoded = head.encode("utf-8")
    if len(encoded) > PREVIEW_HEAD_BYTES:
        # 从字节边界安全截断
        truncated = encoded[:PREVIEW_HEAD_BYTES]
        # 回退到最后一个完整 UTF-8 字符
        head = truncated.decode("utf-8", errors="ignore")
    return head


def build_preview(original_bytes: int, head: str, spill_path: str) -> str:
    """构造替换体字符串，包含原始字节数、头部预览、落盘路径、重读提示。"""
    buf = io.StringIO()
    buf.write(f"[content offloaded] original size: {original_bytes} bytes\n")
    buf.write(f"[saved to] {spill_path}\n")
    buf.write("[head preview]\n")
    buf.write(head)
    if not head.endswith("\n"):
        buf.write("\n")
    buf.write("完整内容已保存到上述路径，如需查看请用文件读取工具读取该路径，不要凭头部预览猜测全文")
    return buf.getvalue()


# ── 主体 ───────────────────────────────────────────


def offload_and_snip(
    msgs: list[Message],
    state: ContentReplacementState,
    session: SessionContext,
) -> tuple[list[Message], int]:
    """遍历 msgs，针对每条 role=="tool" 的消息做超阈值落盘替换。

    规则：
    1. 已在 state._seen_ids 中的工具结果通过 decide_once 拿到现存决策结果。
    2. 未决策的项进入候选列表，按字节倒序处理：
       a. 单条 > SINGLE_RESULT_LIMIT：spill 后替换。
       b. 剩余聚合字节 > MESSAGE_AGGREGATE_LIMIT：按倒序逐项落盘。
       c. 未落盘的项 kept。
    3. 落盘失败时降级为 skip（不替换、不写账本），下次重试。
    4. 返回 (新的 list[Message], 本轮新替换数量)，不修改入参。
    """
    out = copy.deepcopy(msgs)
    replaced_count = 0

    for msg in out:
        if msg.role != "tool":
            continue
        if not msg.tool_results:
            continue

        results = msg.tool_results

        # 第一遍：探测已决策项，建立未决策候选列表
        candidates: list[tuple[int, int, str]] = []  # (idx, byte_len, content)

        for i, tr in enumerate(results):
            content = tr.content or ""
            byte_len = len(content.encode("utf-8"))

            # 已决策项直接复用账本结果
            if state.is_seen(tr.tool_call_id):
                # decide_once 会返回存量结果（不调回调）
                result_content = state.decide_once(tr.tool_call_id, content, lambda: ("kept", ""))
                tr.content = result_content
                continue

            # 未决策 → 进入候选
            candidates.append((i, byte_len, content))

        if not candidates:
            continue

        # 按字节倒序排序
        candidates.sort(key=lambda x: x[1], reverse=True)

        # 计算当前剩余聚合字节（所有未决策项 + 已 kept 项的总和）
        remaining_bytes = sum(c[1] for c in candidates)

        for idx, byte_len, content in candidates:
            tr = results[idx]

            # 判断是否需要落盘
            should_spill = byte_len > SINGLE_RESULT_LIMIT or remaining_bytes > MESSAGE_AGGREGATE_LIMIT

            if should_spill:

                def _decide():
                    try:
                        spill_single(session, tr.tool_call_id, content)
                    except OSError:
                        return ("skip", "")
                    spill_path = str(Path(session.spill_dir) / tr.tool_call_id)
                    preview = build_preview(byte_len, _head_preview(content), spill_path)
                    return ("replaced", preview)

                new_content = state.decide_once(tr.tool_call_id, content, _decide)
                if new_content != content:  # 确实被替换了（不是 skip）
                    tr.content = new_content
                    replaced_count += 1
                else:
                    tr.content = new_content
                remaining_bytes -= byte_len
            else:

                def _keep():
                    return ("kept", "")

                state.decide_once(tr.tool_call_id, content, _keep)
                # 保持原文

    return out, replaced_count
