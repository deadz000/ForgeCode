"""/resume 会话恢复：列表展示、选择交互、恢复流程。"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta
from typing import Any

from forgecode.compact.state import open_session_context
from forgecode.compact.token import estimate_tokens
from forgecode.conversation.history import ROLE_USER, Conversation, Message
from forgecode.session import SessionInfo, load_session
from forgecode.session.writer import Writer

# 恢复后时间跨度提醒阈值
_RESUME_GAP_THRESHOLD = timedelta(hours=6)

# 恢复时 token 估算的安全边界
_RESUME_SAFETY_MARGIN = 3000
_RESUME_SUMMARY_RESERVE = 20000


def _session_meta(info: SessionInfo) -> tuple[str, str, str]:
    """返回 (title, rel_time, size_str) 会话列表元信息。"""
    # 相对时间
    now = datetime.now()
    delta = now - info.modified_at
    if delta.days > 30:
        rel_time = f"{delta.days // 30} months ago"
    elif delta.days > 0:
        rel_time = f"{delta.days} day{'s' if delta.days > 1 else ''} ago"
    elif delta.seconds >= 3600:
        rel_time = f"{delta.seconds // 3600} hour{'s' if delta.seconds // 3600 > 1 else ''} ago"
    elif delta.seconds >= 60:
        rel_time = f"{delta.seconds // 60} min ago"
    else:
        rel_time = "just now"

    # 文件大小
    if info.size >= 1024 * 1024:
        size_str = f"{info.size / (1024 * 1024):.1f}MB"
    elif info.size >= 1024:
        size_str = f"{info.size / 1024:.1f}KB"
    else:
        size_str = f"{info.size}B"

    title = info.title if info.title else "(空)"
    return title, rel_time, size_str


def format_session_item(info: SessionInfo, index: int) -> str:
    """格式化单条会话列表项（带 rich 标记）。"""
    title, rel_time, size_str = _session_meta(info)
    return f"  {index}. {title}  [dim]· {rel_time} · {info.model} · {size_str}[/dim]"


def plain_session_item(info: SessionInfo) -> str:
    """会话列表项的纯文本（无 rich 标记），供方向键选择器 label 使用。"""
    title, rel_time, size_str = _session_meta(info)
    return f"{title}  · {rel_time} · {info.model} · {size_str}"


async def do_resume_session(
    app: Any,
    info: SessionInfo,
) -> str:
    """执行会话恢复流程，返回状态消息。

    步骤：load → 截断孤立 → (可选压缩) → (可选时间提醒) → 替换 app 状态。
    """
    msgs = load_session(info.dir)

    if not msgs:
        return "会话无有效消息，无法恢复。"

    # 检查时间跨度
    last_ts = _last_message_ts(msgs)
    if last_ts is not None:
        gap = timedelta(seconds=time.time() - last_ts)
        if gap > _RESUME_GAP_THRESHOLD:
            duration = _format_duration(gap)
            reminder = (
                f"[系统提示] 本会话已暂停 {duration}。部分上下文可能已过时，如需最新信息请重新读取相关文件。"
            )
            msgs.append(Message(role=ROLE_USER, content=reminder))

    # 估算 token
    cw = app.runtime.context_window if app.runtime else 200000
    est = estimate_tokens(0, msgs, 0)
    threshold = cw - _RESUME_SUMMARY_RESERVE - _RESUME_SAFETY_MARGIN

    if est >= threshold and cw > _RESUME_SUMMARY_RESERVE + _RESUME_SAFETY_MARGIN:
        # 需要压缩
        app._get_agent()  # 确保 agent 已构造
        from forgecode.compact import ManageInput, TriggerKind, manage_context

        in_ = ManageInput(
            conv=Conversation.from_messages(msgs),
            provider=app.provider,
            model=app.provider.config.model,
            context_window=cw,
            tool_defs=[],
            replacement=app.runtime.replacement,
            recovery=app.runtime.recovery,
            auto_tracking=app.runtime.auto_tracking,
            session=app.runtime.session,
            usage_anchor=0,
            anchor_msg_len=0,
            estimated_token=est,
            trigger=TriggerKind.MANUAL,
        )
        try:
            await manage_context(in_)
            # 压缩后从 conversation 获取消息
            msgs = app.conversation.messages
        except Exception:
            pass  # 压缩失败不阻塞恢复

    # 重建 Conversation
    from forgecode.conversation.history import Conversation as Conv

    new_conv = Conv.from_messages(msgs)

    # 重新打开 Writer
    root = os.getcwd()
    ses_ctx = open_session_context(root, info.id)
    if ses_ctx is None:
        return f"会话目录不存在: {info.dir}"

    try:
        new_writer = Writer.open_existing(info.dir)
    except OSError as e:
        return f"无法打开会话文件: {e}"

    # 设置回调
    new_conv._on_append = lambda msg: new_writer.append(msg, model=app._active_model(), is_first=False)
    new_conv._on_replace = lambda msgs_list: _on_replace_write(new_writer, msgs_list)

    # 替换 app 状态
    old_writer = getattr(app, "_writer", None)
    if old_writer is not None:
        try:
            old_writer.close()
        except Exception:
            pass

    app.conversation = new_conv
    app._writer = new_writer
    if app.runtime is not None:
        app.runtime.session = ses_ctx

    return f"已恢复会话 {info.id}，共 {len(msgs)} 条消息"


def _on_replace_write(writer: Writer, msgs: list[Message]) -> None:
    """on_replace 回调：写 compact 标记 + 追加新消息。"""
    writer.write_compact_marker()
    writer.append_all(msgs)


def _last_message_ts(msgs: list[Message]) -> float | None:
    """从消息列表推断最后一条消息的近似时间戳。"""
    # ts 字段不在 Message 中，返回 None 表示未知
    return None


def _format_duration(delta: timedelta) -> str:
    """格式化时间跨度为可读字符串。"""
    total_hours = delta.total_seconds() / 3600
    if total_hours < 1:
        return f"{int(delta.total_seconds() / 60)} 分钟"
    if total_hours < 24:
        return f"{int(total_hours)} 小时"
    return f"{int(total_hours / 24)} 天"
