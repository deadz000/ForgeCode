"""三段恢复：最近读过的文件快照 + 当前可用工具列表 + 边界提示消息。

纯函数，不修改外部状态。调用方必须先拍 snapshot 快照再传入，避免渲染期间状态漂移。
"""

from __future__ import annotations

import io
import json

from forgecode.compact.const import (
    ESTIMATE_CHARS_PER_TOKEN,
    RECOVERY_FILE_LIMIT,
    RECOVERY_TOKENS_PER_FILE,
)
from forgecode.compact.state import FileReadRecord
from forgecode.conversation.history import ToolDefinition

# ── 边界提示消息 ───────────────────────────────────

BOUNDARY_NOTICE: str = """\
需要文件原文、错误原文或用户原话时，请使用文件读取工具重新读取对应路径，不要依据摘要内容做猜测。\
"""

# ── 单文件渲染 ────────────────────────────────────


def render_file_block(rec: FileReadRecord) -> str:
    """渲染单个文件快照：路径 / 时间戳 / 内容片段（必要时截断）。"""
    char_limit = int(RECOVERY_TOKENS_PER_FILE * ESTIMATE_CHARS_PER_TOKEN)
    content = rec.content
    truncated = False
    if len(content) > char_limit:
        content = content[:char_limit]
        truncated = True

    buf = io.StringIO()
    buf.write(f"### {rec.path}\n")
    buf.write(f"[读取时间] {rec.timestamp.isoformat()}\n")
    buf.write(content)
    if truncated:
        buf.write("\n(content truncated)")
    buf.write("\n")
    return buf.getvalue()


# ── 工具列表渲染 ──────────────────────────────────


def render_tools_block(defs: list[ToolDefinition]) -> str:
    """渲染工具列表：每行一个工具名 + 描述 + 参数 schema 摘要。"""
    buf = io.StringIO()
    for d in defs:
        schema_str = json.dumps(d.input_schema, separators=(",", ":"), ensure_ascii=False)
        buf.write(f"- {d.name}: {d.description}\n")
        buf.write(f"  schema: {schema_str}\n")
    return buf.getvalue()


# ── 三段拼接 ──────────────────────────────────────


def build_recovery_attachment(
    snapshot: list[FileReadRecord],
    tool_defs: list[ToolDefinition],
) -> str:
    """构造摘要后的恢复三段内容。

    入参 snapshot 必须由调用方在 run_summary 入口一次性拍好，
    本函数不直接持有 RecoveryState，避免渲染期间状态漂移。

    三段：
    1. 最近读过的文件快照（最多 5 个，按时间戳倒序）
    2. 当前可用工具列表
    3. 边界提示消息
    """
    buf = io.StringIO()

    # 1. 文件快照
    buf.write("## 最近读过的文件\n")
    recent = snapshot[:RECOVERY_FILE_LIMIT]
    if not recent:
        buf.write("(无)\n")
    else:
        for rec in recent:
            buf.write(render_file_block(rec))

    # 2. 工具列表
    buf.write("\n## 当前可用工具\n")
    buf.write(render_tools_block(tool_defs))

    # 3. 边界提示
    buf.write("\n## 边界提示\n")
    buf.write(BOUNDARY_NOTICE)
    buf.write("\n")

    return buf.getvalue()
