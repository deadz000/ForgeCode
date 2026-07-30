"""摘要 Prompt 模板：9 部分结构化摘要 + 对话序列化 + 摘要解析。"""

from __future__ import annotations

import logging
import re

from forgecode.conversation.history import Message

logger = logging.getLogger(__name__)

# ── 摘要指令模板 ───────────────────────────────────

SUMMARY_INSTRUCTION: str = """You are summarizing a coding agent conversation. Output in two phases.

<analysis>
在这里写分析草稿，梳理会话脉络、关键决策点和未完成事项。这部分内容不会被保留。
</analysis>

<summary>
## 1 主要请求和意图
记录用户所有的初始请求，以及对话过程中澄清或变更后的意图。

## 2 关键技术概念
列出涉及的技术栈、框架、关键 API 和架构决策。

## 3 文件和代码段
列出被创建、修改、读取或讨论的关键文件路径及对应的操作。

## 4 错误和修复
记录遇到的错误消息、根因分析和修复方式。尽量保留原始错误信息。

## 5 问题解决过程
描述排查思路、尝试过的方案和最终解决路径。

## 6 所有用户消息原文
按时间顺序逐条保留用户的所有原始消息。这是最重要的部分，不能遗漏任何一条。

## 7 待办任务
列出尚未完成的待办事项，标注优先级。

## 8 当前工作（最详细）
详细描述当前正在做什么、停在哪一步、进度如何。这是最详细的一节。

## 9 可能的下一步
基于当前状态，给出接下来可能的行动建议。
</summary>

不要调用任何工具，输出纯文本。只输出一次 <analysis> 和一次 <summary>。"""


# ── 对话序列化 ────────────────────────────────────


def serialize_conversation(msgs: list[Message]) -> str:
    """把对话扁平化成可读文本。

    - user/assistant: role: <content>
    - assistant 工具调用: [call <name> id=<id> args=<json>]
    - tool 消息内每条 result: [result id=<id> is_error=<bool>] <content>
    行间用空行隔开；纯函数，不依赖外部状态。
    """
    buf: list[str] = []
    for m in msgs:
        if m.role == "user":
            buf.append(f"user: {m.content}")
        elif m.role == "assistant":
            if m.tool_calls:
                if m.content:
                    buf.append(f"assistant: {m.content}")
                for c in m.tool_calls:
                    buf.append(f"[call {c.name} id={c.id} args={c.input}]")
            else:
                buf.append(f"assistant: {m.content}")
        elif m.role == "tool":
            for r in m.tool_results:
                err_tag = " is_error=True" if r.is_error else ""
                buf.append(f"[result id={r.tool_call_id}{err_tag}] {r.content}")
        buf.append("")
    return "\n".join(buf)


# ── 摘要构造 ──────────────────────────────────────


def build_summary_prompt(msgs: list[Message]) -> list[Message]:
    """把对话嵌入到固定模板里，返回仅含一条 user 消息的列表。"""
    serialized = serialize_conversation(msgs)
    content = SUMMARY_INSTRUCTION + "\n\n[conversation]\n" + serialized
    return [Message(role="user", content=content)]


# ── 摘要解析 ──────────────────────────────────────


def extract_summary(raw: str) -> str:
    """从模型返回的整段文本里抠出 <summary>...</summary> 之间的正文。

    <analysis> 部分直接丢弃。提取失败时返回原文并 warning。
    """
    matches = re.findall(r"<summary>(.*?)</summary>", raw, re.DOTALL)
    if matches:
        return matches[-1].strip()
    logger.warning("summary tags not found in model output, using raw text")
    return raw
