"""通用选择题交互组件：单选/多选，方向键导航 + Enter 确认。

与主输入盒子同风格的 prompt_toolkit 非全屏 Application：
- 单选：↑/↓ 移动高亮，Enter 立即确认，Esc/Ctrl+C 取消
- 多选：↑/↓ 移动，Enter 切换勾选，移动到末尾『确认提交』按 Enter 提交，
  Esc/Ctrl+C 取消（不返回任何勾选）

审批（人在回路）等需要用户从选项中选择的场景统一走这里。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from prompt_toolkit.application import Application
from prompt_toolkit.formatted_text import StyleAndTextTuples
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
from prompt_toolkit.layout import Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.styles import Style

# ── 样式（与 PROMPT_STYLE 同风格：黑底白字）──

CHOICE_STYLE = Style.from_dict(
    {
        "title": "bold #00ff87",
        "subtitle": "#888888",
        "selected": "bg:#005f87 fg:#ffffff bold",
        "checked": "#00ff87 bold",
        "hint": "#555555",
    }
)


# ── 数据模型 ──────────────────────────────────


@dataclass(frozen=True)
class ChoiceOption:
    """一个可选中的选项。key 为返回值标识，label 为显示文本。"""

    key: str
    label: str
    description: str = ""


@dataclass
class ChoiceResult:
    """选择结果。单选：values 恰含一个 key；多选：values 为勾选的 keys。"""

    values: list[str] = field(default_factory=list)
    cancelled: bool = False


# ── 纯函数（便于单测）────────────────────────


def move_cursor(selected: int, delta: int, count: int) -> int:
    """循环移动高亮下标。count 为 0 时返回 0。"""
    if count <= 0:
        return 0
    return (selected + delta) % count


def toggle_index(checked: set[int], idx: int) -> set[int]:
    """切换勾选集合中的 idx。"""
    new_set = set(checked)
    if idx in new_set:
        new_set.discard(idx)
    else:
        new_set.add(idx)
    return new_set


def render_choice_lines(
    title: str,
    options: list[ChoiceOption],
    selected: int,
    checked: set[int],
    *,
    subtitle: str = "",
    multi: bool = False,
) -> list[tuple[str, str]]:
    """渲染选项列表为 (style, text) 行，供 FormattedTextControl 消费。

    单选：`> 1. 标签`（当前项高亮）；多选：`[x] 1. 标签` + 末尾『确认提交』。
    """
    lines: list[tuple[str, str]] = [("class:title", title)]
    if subtitle:
        lines.append(("class:subtitle", subtitle))
    if not options:
        lines.append(("class:hint", "（无可用选项）"))
        return lines

    confirm_idx = len(options)  # 多选时『确认提交』所在下标
    for i, opt in enumerate(options):
        if multi:
            mark = "[x]" if i in checked else "[ ]"
            prefix = f"{mark} {i + 1}."
        else:
            prefix = f"{i + 1}."
        style = "class:selected" if i == selected else ""
        suffix = f"  {opt.description}" if opt.description else ""
        lines.append((style, f"{prefix} {opt.label}{suffix}"))

    if multi:
        style = "class:selected" if selected == confirm_idx else ""
        lines.append((style, "[ 确认提交 ]"))

    hint = "↑/↓ 选择 · Enter 确认 · Esc 取消"
    if multi:
        hint = "↑/↓ 移动 · Enter 勾选 · 移到『确认提交』按 Enter 提交 · Esc 取消"
    lines.append(("class:hint", hint))
    return lines


# ── 交互组件 ─────────────────────────────────


class ChoiceQuestion:
    """方向键选择题。单选：Enter 直接确认当前项；多选：Enter 勾选 + 确认项提交。"""

    def __init__(
        self,
        title: str,
        options: list[ChoiceOption],
        *,
        subtitle: str = "",
        multi: bool = False,
        default_index: int = 0,
    ) -> None:
        self._title = title
        self._options = list(options)
        self._subtitle = subtitle
        self._multi = multi
        self._selected = default_index
        self._checked: set[int] = set()

    # ── 渲染 ──

    def _render(self) -> StyleAndTextTuples:
        result: StyleAndTextTuples = []
        for style, text in render_choice_lines(
            self._title,
            self._options,
            self._selected,
            self._checked,
            subtitle=self._subtitle,
            multi=self._multi,
        ):
            result.append((style, text))
        return result

    # ── 交互 ──

    def _result(self) -> ChoiceResult:
        if self._multi:
            values = [self._options[i].key for i in sorted(self._checked)]
            return ChoiceResult(values=values)
        return ChoiceResult(values=[self._options[self._selected].key])

    def _on_up(self, event: KeyPressEvent) -> None:
        self._selected = move_cursor(self._selected, -1, self._item_count())
        event.app.invalidate()

    def _on_down(self, event: KeyPressEvent) -> None:
        self._selected = move_cursor(self._selected, 1, self._item_count())
        event.app.invalidate()

    def _item_count(self) -> int:
        """可选中的项数：多选时含『确认提交』。"""
        return len(self._options) + (1 if self._multi else 0)

    def _on_enter(self, event: KeyPressEvent) -> None:
        if self._multi:
            if self._selected == len(self._options):
                event.app.exit(result=self._result())
            else:
                self._checked = toggle_index(self._checked, self._selected)
                event.app.invalidate()
        else:
            event.app.exit(result=self._result())

    def _on_cancel(self, event: KeyPressEvent) -> None:
        event.app.exit(result=ChoiceResult(values=[], cancelled=True))

    # ── 运行 ──

    def _build_app(self, input: Any = None, output: Any = None) -> Application[ChoiceResult]:
        kb = KeyBindings()

        @kb.add("up")
        def _up(event: KeyPressEvent) -> None:
            self._on_up(event)

        @kb.add("down")
        def _down(event: KeyPressEvent) -> None:
            self._on_down(event)

        @kb.add("enter")
        def _enter(event: KeyPressEvent) -> None:
            self._on_enter(event)

        @kb.add("escape")
        def _esc(event: KeyPressEvent) -> None:
            self._on_cancel(event)

        @kb.add("c-c")
        def _ctrlc(event: KeyPressEvent) -> None:
            self._on_cancel(event)

        body = Window(
            FormattedTextControl(self._render),
            dont_extend_height=True,
            always_hide_cursor=True,
        )
        return Application(
            layout=Layout(body),
            style=CHOICE_STYLE,
            full_screen=False,
            key_bindings=kb,
            input=input,
            output=output,
        )

    async def run(self, input: Any = None, output: Any = None) -> ChoiceResult:
        """运行选择题，返回 ChoiceResult。input/output 供测试注入 pipe。"""
        return await self._build_app(input, output).run_async()


async def ask_choice(
    title: str,
    options: list[ChoiceOption],
    *,
    subtitle: str = "",
    multi: bool = False,
    default_index: int = 0,
    input: Any = None,
    output: Any = None,
) -> ChoiceResult:
    """便捷入口：构造 ChoiceQuestion 并运行。"""
    q = ChoiceQuestion(title, options, subtitle=subtitle, multi=multi, default_index=default_index)
    return await q.run(input=input, output=output)
