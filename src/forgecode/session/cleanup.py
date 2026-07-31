"""会话过期清理：删除超期会话目录。"""

from __future__ import annotations

import logging
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

from forgecode.compact.state import parse_session_time

logger = logging.getLogger(__name__)


def clean_expired(sessions_dir: str, max_age: timedelta) -> None:
    """删除超过 max_age 的会话目录。

    只处理新格式 ID 的目录（能解析出时间戳），旧格式跳过。
    单个删除失败记录日志并继续。
    """
    sessions_path = Path(sessions_dir)
    if not sessions_path.is_dir():
        return

    now = datetime.now(UTC)

    for child in sessions_path.iterdir():
        if not child.is_dir():
            continue

        # 尝试解析时间戳
        parsed = parse_session_time(child.name)
        if parsed is None:
            # 旧格式 ID 跳过，避免误删
            continue

        # 补全时区信息（parse_session_time 返回 naive datetime）
        parsed_aware = parsed.replace(tzinfo=UTC)

        if now - parsed_aware > max_age:
            try:
                shutil.rmtree(str(child), ignore_errors=False)
                logger.info("已清理过期会话: %s", child.name)
            except OSError:
                logger.warning("清理会话目录失败: %s", child, exc_info=True)
