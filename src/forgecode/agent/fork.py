"""Fork 路径辅助：Boilerplate 常量、消息克隆、上下文识别。"""

from __future__ import annotations

import copy

from forgecode.conversation.history import (
    ROLE_ASSISTANT,
    ROLE_TOOL,
    ROLE_USER,
    Message,
    ToolResult,
)

FORK_BOILERPLATE_TAG = "<fork_boilerplate>"

# Fork 子 Agent 首条 user 消息的前缀，约束其行为。
FORK_BOILERPLATE = """<fork_boilerplate>
你是一个 Fork 出来的工作进程。你不是主 Agent。
规则(不可协商):
1. 不能再 Fork(调用 Agent 工具会被拦截)。
2. 不要对话、不要提问、不要请求确认。
3. 直接使用工具:读文件、搜索代码、做修改。
4. 严格限制在你被分配的任务范围内。
5. 最终报告以 "Scope:" 开头,500 字以内。
</fork_boilerplate>

"""


def build_forked_messages(parent_msgs: list[Message], task: str) -> list[Message]:
    """把父对话克隆到 Fork 子对话。

    行为（spec F22）：
      1. 深拷贝 parent_msgs
      2. 末尾 assistant 中未配对的 tool_use 追加 placeholder ToolResult，使消息格式合法
      3. 末尾追加 user 消息 = FORK_BOILERPLATE + task
    """
    msgs = copy.deepcopy(parent_msgs)

    consumed: set[str] = set()
    for m in msgs:
        for r in m.tool_results:
            consumed.add(r.tool_call_id)

    if msgs and msgs[-1].role == ROLE_ASSISTANT:
        dangling = [c for c in msgs[-1].tool_calls if c.id not in consumed]
        if dangling:
            msgs.append(
                Message(
                    role=ROLE_TOOL,
                    tool_results=[
                        ToolResult(
                            tool_call_id=c.id,
                            content="[forked, skipped]",
                            is_error=True,
                        )
                        for c in dangling
                    ],
                )
            )

    msgs.append(Message(role=ROLE_USER, content=FORK_BOILERPLATE + task))
    return msgs


def is_fork_context(msgs: list[Message]) -> bool:
    """扫描消息历史是否含 Fork Boilerplate 标记（嵌套阻断兜底）。"""
    for m in msgs:
        if FORK_BOILERPLATE_TAG in m.content:
            return True
        for r in m.tool_results:
            if FORK_BOILERPLATE_TAG in r.content:
                return True
    return False
