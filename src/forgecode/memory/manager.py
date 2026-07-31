"""记忆管理器：编排项目级和用户级笔记的加载和更新。"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from forgecode.memory.prompts import MEMORY_UPDATE_SYSTEM_PROMPT
from forgecode.memory.store import Store
from forgecode.memory.types import UpdateAction
from forgecode.providers import BaseProvider, Request, System

logger = logging.getLogger(__name__)

# 索引注入最大字节数
MAX_INDEX_INJECT_BYTES = 25 * 1024


class Manager:
    """编排项目级和用户级笔记的加载和异步更新。"""

    def __init__(
        self,
        project_dir: str,
        user_dir: str,
        provider: BaseProvider | None = None,
        model: str = "",
    ) -> None:
        self._project_store = Store(project_dir)
        self._user_store = Store(user_dir)
        self._provider = provider
        self._model = model
        self._lock = asyncio.Lock()

    def load_index(self) -> str:
        """合并两级索引（项目级在前、用户级在后），截断到 25KB。

        截断时优先保留项目级内容（从头部截取）。
        """
        project_index = self._project_store.load_index()
        user_index = self._user_store.load_index()

        parts: list[str] = []
        if project_index.strip():
            parts.append(project_index.strip())
        if user_index.strip():
            parts.append(user_index.strip())

        merged = "\n\n".join(parts)

        # 截断到 25KB
        if len(merged.encode("utf-8")) > MAX_INDEX_INJECT_BYTES:
            # 按字节截断
            encoded = merged.encode("utf-8")
            truncated = encoded[: MAX_INDEX_INJECT_BYTES - 30]  # 留给标注
            merged = truncated.decode("utf-8", errors="replace") + "\n(index truncated)"

        return merged

    def set_provider(self, provider: BaseProvider, model: str) -> None:
        """延迟设置 provider（启动时 provider 未选定）。"""
        self._provider = provider
        self._model = model

    async def update_async(self, recent_msgs: list[Any]) -> None:
        """异步执行记忆更新。

        Args:
            recent_msgs: 最近一轮对话的消息列表（从最后一条 user 到当前 assistant）。
        """
        if self._provider is None:
            logger.debug("记忆更新跳过：provider 未设置")
            return

        async with self._lock:
            try:
                await self._do_update(recent_msgs)
            except Exception:
                logger.exception("记忆更新失败")

    async def _do_update(self, recent_msgs: list[Any]) -> None:
        """执行一次记忆更新（锁内）。"""
        # 组装请求
        existing_index = self.load_index()

        # 构建 user 消息：最近对话 + 现有索引
        conv_text = _format_messages(recent_msgs)
        user_content = (
            f"## 最近的对话\n\n{conv_text}\n\n"
            f"## 现有记忆索引\n\n{existing_index if existing_index else '(暂无)'}\n\n"
            "请分析以上对话，判断是否有值得长期记住的信息，并返回操作列表。"
        )

        from forgecode.conversation.history import ROLE_USER, Message

        msgs = [Message(role=ROLE_USER, content=user_content)]

        req = Request(
            messages=msgs,
            tools=[],  # 记忆更新不传工具
            system=System(stable=MEMORY_UPDATE_SYSTEM_PROMPT, environment=""),
            reminder="",
        )

        # 流式收集回复
        full_text = ""
        assert self._provider is not None
        async for se in self._provider.stream(req):
            if se.err is not None:
                logger.warning("记忆更新 LLM 错误: %s", se.err)
                return
            if se.text:
                full_text += se.text
            if se.done:
                break

        if not full_text.strip():
            return

        # 解析 JSON 数组
        actions = _parse_actions(full_text)
        if not actions:
            return

        # 分发到两级 Store
        project_actions: list[UpdateAction] = []
        user_actions: list[UpdateAction] = []
        for a in actions:
            if a.level == "project":
                project_actions.append(a)
            elif a.level == "user":
                user_actions.append(a)

        if project_actions:
            self._project_store.apply(project_actions)
        if user_actions:
            self._user_store.apply(user_actions)

        # 更新后重新加载索引注入（下次 run 生效）
        logger.info("记忆更新完成: project=%d, user=%d", len(project_actions), len(user_actions))


def _format_messages(msgs: list[Any]) -> str:
    """将消息列表格式化为可读文本。"""
    lines: list[str] = []
    for m in msgs:
        role = getattr(m, "role", "unknown")
        content = getattr(m, "content", "")
        tool_calls = getattr(m, "tool_calls", [])
        tool_results = getattr(m, "tool_results", [])

        label = {"user": "用户", "assistant": "助手", "tool": "工具"}.get(role, role)
        parts = [f"[{label}]"]
        if content:
            parts.append(content)
        if tool_calls:
            parts.append(f"(调用了工具: {', '.join(getattr(c, 'name', '?') for c in tool_calls)})")
        if tool_results:
            # 工具结果截断展示
            for r in tool_results:
                c = getattr(r, "content", "")
                if len(c) > 200:
                    c = c[:197] + "..."
                parts.append(f"(结果: {c})")
        lines.append(" ".join(parts))
    return "\n".join(lines)


def _parse_actions(text: str) -> list[UpdateAction]:
    """从 LLM 回复中解析 UpdateAction 列表。

    兼容 JSON 代码块包裹和裸 JSON。
    """
    # 尝试提取 ```json ... ``` 代码块
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        # 去掉首行 ```json 和尾行 ```
        if len(lines) >= 3:
            lines = lines[1:-1]
            text = "\n".join(lines)
        elif len(lines) >= 2:
            lines = lines[1:]
            text = "\n".join(lines)

    # 尝试找到 JSON 数组的起止
    try:
        start = text.index("[")
        end = text.rindex("]") + 1
        text = text[start:end]
    except ValueError:
        logger.warning("记忆更新回复中未找到 JSON 数组")
        return []

    try:
        raw_list = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("记忆更新 JSON 解析失败: %s", text[:200])
        return []

    if not isinstance(raw_list, list):
        return []

    actions: list[UpdateAction] = []
    for item in raw_list:
        if not isinstance(item, dict):
            continue
        try:
            actions.append(
                UpdateAction(
                    action=str(item.get("action", "")),
                    level=str(item.get("level", "")),
                    type=str(item.get("type", "")),
                    title=str(item.get("title", "")),
                    slug=str(item.get("slug", "")),
                    content=str(item.get("content", "")),
                    filename=str(item.get("filename", "")),
                )
            )
        except Exception:
            logger.warning("解析 UpdateAction 失败: %s", item, exc_info=True)
            continue

    return actions
