"""forgecode.compact：上下文管理模块。

两层防御架构：
- 第 1 层：超阈值工具结果落盘替换（纯字符串处理）
- 第 2 层：LLM 结构化摘要 + 恢复段 + 近期原文

对外暴露：
- manage_context：编排入口
- TriggerKind：触发类型枚举
- ContentReplacementState / CompactCircuitBreaker / RecoveryState / SessionContext：状态对象
- new_session_context：会话上下文工厂
"""

from forgecode.compact.compact import ManageInput, ManageOutput, TriggerKind, manage_context
from forgecode.compact.state import (
    CompactCircuitBreaker,
    ContentReplacementState,
    RecoveryState,
    SessionContext,
    new_session_context,
)

__all__ = [
    "ManageInput",
    "ManageOutput",
    "TriggerKind",
    "manage_context",
    "CompactCircuitBreaker",
    "ContentReplacementState",
    "RecoveryState",
    "SessionContext",
    "new_session_context",
]
