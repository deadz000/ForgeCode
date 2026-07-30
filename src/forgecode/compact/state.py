"""会话级状态对象：替换账本、熔断器、文件追踪、会话上下文。

Python asyncio 单线程事件循环保证串行执行，以下状态对象内部均标注"无需显式锁"，
状态只在事件循环内的 task 间通过 await 切换，不存在真正的线程级并发。
"""

from __future__ import annotations

import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from forgecode.compact.const import MAX_CONSECUTIVE_AUTO_COMPACT_FAILURES

# ── SessionContext ─────────────────────────────────


@dataclass
class SessionContext:
    """会话生命周期信息。session_id 进程启动时一次性生成。"""

    session_id: str
    spill_dir: str  # 固定指向 .forgecode/sessions/<session_id>/tool-results/


def _new_session_id() -> str:
    """生成格式为 <unix_ts>-<short_random> 的会话 id。"""
    try:
        hex_str = secrets.token_hex(4)
    except Exception:
        import logging
        import random

        logging.getLogger(__name__).warning("secrets.token_hex 失败，降级为 random")
        random.Random(time.time()).randbytes(4)
        hex_str = (
            secrets.token_hex(4) if hasattr(secrets, "token_hex") else format(random.getrandbits(32), "08x")
        )
    return f"{int(time.time())}-{hex_str}"


def new_session_context(workspace: str) -> SessionContext:
    """创建会话上下文并建立落盘目录。"""
    session_id = _new_session_id()
    spill_dir = str(Path(workspace) / ".forgecode" / "sessions" / session_id / "tool-results")
    Path(spill_dir).mkdir(parents=True, exist_ok=True)
    return SessionContext(session_id=session_id, spill_dir=spill_dir)


# ── ContentReplacementState ────────────────────────


class ContentReplacementState:
    """会话级的工具结果替换决策账本。

    _seen_ids 记录已经决策过的 tool_use_id，无论决策是替换还是保留原文。
    _replacements 只保存"决定替换"那一支的预览字符串，键是 tool_use_id。
    同一个 tool_use_id 一旦进入 _seen_ids 就再也不会被重新评估，保证 prompt cache 稳定。
    """

    def __init__(self) -> None:
        # 无需显式锁——Python asyncio 单线程事件循环保证串行
        self._seen_ids: set[str] = set()
        self._replacements: dict[str, str] = {}

    def decide_once(
        self,
        tool_use_id: str,
        original: str,
        decide: Callable[[], tuple[str, str]],  # 返回 (decision, preview)
    ) -> str:
        """持锁完成"查账本 → 决策 → 写账本"原子操作。

        若 id 已 Seen：直接返回账本中存量结果（kept 返回原 content，
        replaced 返回 _replacements[id]）。
        若 id 未 Seen：调 decide() 回调（仍持锁）：
        - 回调返回 ("kept", _)：写 _seen_ids，不写 _replacements；返回原 content。
        - 回调返回 ("replaced", preview)：写 _seen_ids + _replacements；返回 preview。
        - 回调返回 ("skip", _)：既不写 _seen_ids 也不写 _replacements；返回原
          content（下一轮重试）。
        """
        if tool_use_id in self._seen_ids:
            return self._replacements.get(tool_use_id, original)

        decision, preview = decide()
        if decision == "kept":
            self._seen_ids.add(tool_use_id)
            return original
        elif decision == "replaced":
            self._seen_ids.add(tool_use_id)
            self._replacements[tool_use_id] = preview
            return preview
        else:  # "skip"
            return original

    def is_seen(self, tool_use_id: str) -> bool:
        """检查 id 是否已被决策过。"""
        return tool_use_id in self._seen_ids


# ── CompactCircuitBreaker ──────────────────────────


class CompactCircuitBreaker:
    """自动摘要熔断器：连续失败 N 次后跳闸，手动/紧急路径永远绕过。"""

    def __init__(self) -> None:
        # 无需显式锁——Python asyncio 单线程事件循环保证串行
        self._consecutive_failures: int = 0

    def record_success(self) -> None:
        """记录一次成功，清零连续失败计数。"""
        self._consecutive_failures = 0

    def record_failure(self) -> None:
        """记录一次失败，累加连续失败计数。"""
        self._consecutive_failures += 1

    def tripped(self) -> bool:
        """熔断器是否已跳闸。"""
        return self._consecutive_failures >= MAX_CONSECUTIVE_AUTO_COMPACT_FAILURES


# ── RecoveryState ──────────────────────────────────


@dataclass
class FileReadRecord:
    """文件读取追踪记录：路径、纯净内容、最后读取时间戳。"""

    path: str
    content: str  # 不带行号前缀的纯净内容
    timestamp: datetime


class RecoveryState:
    """Agent 主循环写、compact 摘要时读的文件追踪状态。

    _files 的键是文件绝对路径，避免相对路径在不同 cwd 下错乱。
    """

    def __init__(self) -> None:
        # 无需显式锁——Python asyncio 单线程事件循环保证串行
        self._files: dict[str, FileReadRecord] = {}

    def record_file(self, path: str, content: str) -> None:
        """记录一次成功的文件读取。"""
        abs_path = str(Path(path).resolve())
        self._files[abs_path] = FileReadRecord(
            path=abs_path,
            content=content,
            timestamp=datetime.now(UTC),
        )

    def snapshot(self) -> list[FileReadRecord]:
        """返回按 timestamp 倒序排序的拷贝列表（不暴露内部 dict）。"""
        records = list(self._files.values())
        records.sort(key=lambda r: r.timestamp, reverse=True)
        return records
