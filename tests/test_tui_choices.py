"""tui.choices 选择题组件单测：纯函数 + 按键交互。"""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from forgecode.tui.choices import (
    ChoiceOption,
    ChoiceQuestion,
    ChoiceResult,
    ask_choice,
    move_cursor,
    render_choice_lines,
    toggle_index,
)

OPTIONS = [
    ChoiceOption("allow", "允许本次"),
    ChoiceOption("forever", "永久允许"),
    ChoiceOption("deny", "拒绝本次"),
]


# ── 纯函数 ──────────────────────────────────


def test_move_cursor_wraps_forward():
    assert move_cursor(2, 1, 3) == 0
    assert move_cursor(0, -1, 3) == 2
    assert move_cursor(1, 0, 3) == 1


def test_move_cursor_empty():
    assert move_cursor(0, 1, 0) == 0


def test_toggle_index_adds_and_removes():
    checked = toggle_index(set(), 1)
    assert checked == {1}
    checked = toggle_index(checked, 1)
    assert checked == set()
    checked = toggle_index({0, 2}, 1)
    assert checked == {0, 1, 2}


def test_render_single_select_marks_current():
    lines = render_choice_lines("权限确认", OPTIONS, selected=1, checked=set())
    texts = [t for _, t in lines]
    assert texts[0] == "权限确认"
    assert any(t.startswith("1. 允许本次") for t in texts)
    # 当前项带 selected 样式
    style_by_text = {t: s for s, t in lines}
    assert style_by_text["2. 永久允许"] == "class:selected"
    assert style_by_text["1. 允许本次"] == ""
    assert any("↑/↓ 选择" in t for t in texts)


def test_render_multi_select_marks_checked_and_confirm():
    lines = render_choice_lines("多选测试", OPTIONS, selected=3, checked={0}, multi=True)
    texts = [t for _, t in lines]
    assert any(t.startswith("[x] 1. 允许本次") for t in texts)
    assert any(t.startswith("[ ] 2. 永久允许") for t in texts)
    assert any(t == "[ 确认提交 ]" for t in texts)
    style_by_text = {t: s for s, t in lines}
    assert style_by_text["[ 确认提交 ]"] == "class:selected"
    assert any("Enter 勾选" in t for t in texts)


def test_render_subtitle_and_description():
    opt = ChoiceOption("x", "标签", description="副说明")
    lines = render_choice_lines("标题", [opt], selected=0, checked=set(), subtitle="子标题")
    texts = [t for _, t in lines]
    assert texts[1] == "子标题"
    assert any("标签  副说明" in t for t in texts)


# ── 按键交互（pipe input/output 模拟）────────────────


@contextmanager
def _pipe():
    """产出 (input, output) 管道对，供无控制台环境下的交互测试。"""
    from prompt_toolkit.input.defaults import create_pipe_input
    from prompt_toolkit.output.base import DummyOutput

    with create_pipe_input() as inp:
        yield inp, DummyOutput()


@pytest.mark.asyncio
async def test_single_select_enter_confirms_current():
    with _pipe() as (inp, out):
        inp.send_text("\r")  # 直接 Enter → 默认第 0 项
        q = ChoiceQuestion("t", OPTIONS)
        result = await q.run(input=inp, output=out)
    assert result == ChoiceResult(values=["allow"])


@pytest.mark.asyncio
async def test_single_select_down_and_enter():
    with _pipe() as (inp, out):
        inp.send_text("\x1b[B\x1b[B\r")  # ↓↓ → 第 2 项
        q = ChoiceQuestion("t", OPTIONS)
        result = await q.run(input=inp, output=out)
    assert result.values == ["deny"]


@pytest.mark.asyncio
async def test_single_select_up_wraps():
    with _pipe() as (inp, out):
        inp.send_text("\x1b[A\r")  # ↑ → 从第 0 项回绕到第 2 项
        q = ChoiceQuestion("t", OPTIONS)
        result = await q.run(input=inp, output=out)
    assert result.values == ["deny"]


@pytest.mark.asyncio
async def test_escape_cancels():
    with _pipe() as (inp, out):
        inp.send_text("\x1b\r")  # Esc（取消）后 Enter 应无效果
        q = ChoiceQuestion("t", OPTIONS)
        result = await q.run(input=inp, output=out)
    assert result.cancelled is True
    assert result.values == []


@pytest.mark.asyncio
async def test_multi_select_toggle_and_confirm():
    with _pipe() as (inp, out):
        # Enter 勾选第 0 项 → ↓ 到第 1 项 → Enter 勾选 → ↓↓ 到『确认提交』→ Enter 提交
        inp.send_text("\r\x1b[B\r\x1b[B\x1b[B\r")
        q = ChoiceQuestion("t", OPTIONS, multi=True)
        result = await q.run(input=inp, output=out)
    assert result.cancelled is False
    assert result.values == ["allow", "forever"]


@pytest.mark.asyncio
async def test_multi_select_empty_confirm():
    with _pipe() as (inp, out):
        # 直接 ↓↓↓ 到『确认提交』→ Enter 提交（无勾选）
        inp.send_text("\x1b[B\x1b[B\x1b[B\r")
        q = ChoiceQuestion("t", OPTIONS, multi=True)
        result = await q.run(input=inp, output=out)
    assert result.values == []


@pytest.mark.asyncio
async def test_ask_choice_entry():
    with _pipe() as (inp, out):
        inp.send_text("\x1b[B\r")  # ↓ → 第 1 项
        result = await ask_choice("t", OPTIONS, input=inp, output=out)
    assert result.values == ["forever"]
