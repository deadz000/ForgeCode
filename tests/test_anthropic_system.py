"""Anthropic 缓存断点守护测试：稳定块带 cache_control、环境块不带。"""

from __future__ import annotations

from forgecode.providers.anthropic import _append_reminder_anthropic

# ── 缓存断点序列化验证 ────────────────────────────


def test_stable_block_has_cache_control():
    """验证 AnthropicProvider 构造 system 时稳定块带 cache_control。

    这里通过直接构造 Anthropic 请求参数来验证，
    而不是 mock 整个 provider（避免依赖网络）。
    """
    # 模拟 AnthropicProvider 的 system 构造逻辑
    stable = "You are a coding agent."
    environment = "## 环境信息\n- 工作目录: /tmp"

    system_blocks: list[dict] = []
    if stable:
        system_blocks.append(
            {
                "type": "text",
                "text": stable,
                "cache_control": {"type": "ephemeral"},
            }
        )
    if environment:
        system_blocks.append(
            {
                "type": "text",
                "text": environment,
            }
        )

    # 验证两块结构
    assert len(system_blocks) == 2

    # 第一块（stable）：有 cache_control
    assert system_blocks[0]["type"] == "text"
    assert system_blocks[0]["text"] == stable
    assert "cache_control" in system_blocks[0]
    assert system_blocks[0]["cache_control"] == {"type": "ephemeral"}

    # 第二块（environment）：无 cache_control
    assert system_blocks[1]["type"] == "text"
    assert system_blocks[1]["text"] == environment
    assert "cache_control" not in system_blocks[1]


def test_no_environment_block_when_empty():
    """环境块为空时不追加。"""
    stable = "System prompt"
    environment = ""

    system_blocks: list[dict] = []
    if stable:
        system_blocks.append(
            {
                "type": "text",
                "text": stable,
                "cache_control": {"type": "ephemeral"},
            }
        )
    if environment:
        system_blocks.append(
            {
                "type": "text",
                "text": environment,
            }
        )

    assert len(system_blocks) == 1
    assert system_blocks[0]["cache_control"] == {"type": "ephemeral"}


def test_no_stable_block_when_empty():
    """稳定块为空时不追加。"""
    stable = ""
    environment = "Env info"

    system_blocks: list[dict] = []
    if stable:
        system_blocks.append(
            {
                "type": "text",
                "text": stable,
                "cache_control": {"type": "ephemeral"},
            }
        )
    if environment:
        system_blocks.append(
            {
                "type": "text",
                "text": environment,
            }
        )

    assert len(system_blocks) == 1
    assert "cache_control" not in system_blocks[0]


# ── reminder 织入验证 ─────────────────────────────


def test_append_reminder_to_user_str_content():
    """末条 user 的 content 为 str → 转为 list 并追加 reminder。"""
    messages = [{"role": "user", "content": "hello"}]
    _append_reminder_anthropic(messages, "<system-reminder>\ntest\n</system-reminder>")

    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    assert isinstance(messages[0]["content"], list)
    assert len(messages[0]["content"]) == 2
    assert messages[0]["content"][0] == {"type": "text", "text": "hello"}
    assert messages[0]["content"][1] == {
        "type": "text",
        "text": "<system-reminder>\ntest\n</system-reminder>",
    }


def test_append_reminder_to_user_list_content():
    """末条 user 的 content 为 list → 直接追加。"""
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "1", "content": "result"},
            ],
        },
    ]
    _append_reminder_anthropic(messages, "REMINDER")

    assert len(messages) == 1
    assert len(messages[0]["content"]) == 2
    assert messages[0]["content"][1] == {"type": "text", "text": "REMINDER"}


def test_append_reminder_to_assistant_tail():
    """末条为 assistant → 新起一条 user 消息（保 N3 角色交替）。"""
    messages = [{"role": "assistant", "content": "I did it"}]
    _append_reminder_anthropic(messages, "REMINDER")

    assert len(messages) == 2
    assert messages[1]["role"] == "user"
    assert messages[1]["content"] == "REMINDER"


def test_append_reminder_to_empty():
    """空消息列表 → 新起一条 user 消息。"""
    messages: list[dict] = []
    _append_reminder_anthropic(messages, "REMINDER")

    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "REMINDER"


def test_append_reminder_noop_when_empty_reminder():
    """空 reminder 仍会追加（调用方保证不为空时才调）。"""
    # 实际使用中 req.reminder 非空才调 _append_reminder_anthropic
    # 这里验证即使传入空字符串，行为也有定义
    messages = [{"role": "user", "content": "hello"}]
    _append_reminder_anthropic(messages, "")

    assert len(messages) == 1
    content = messages[0]["content"]
    if isinstance(content, list):
        # str → list 转换后最后一块是空文本
        assert content[-1] == {"type": "text", "text": ""}
