"""提示词命令：/do /review + REVIEW_DIRECTIVE 常量"""

from __future__ import annotations

from forgecode.permission import Mode
from forgecode.prompt import EXECUTE_DIRECTIVE

REVIEW_DIRECTIVE = "请审查当前上下文中的代码变更/已读取的文件，指出潜在 bug、可读性问题和可简化处。"


async def handle_do(ui) -> None:
    """切回默认模式、注入 /do 执行指令、触发 LLM 回合。"""
    ui.set_mode(Mode.DEFAULT)
    ui.inject_and_send("/do", EXECUTE_DIRECTIVE)


async def handle_review(ui) -> None:
    """注入代码审查指令、触发 LLM 回合。"""
    ui.inject_and_send("/review", REVIEW_DIRECTIVE)
