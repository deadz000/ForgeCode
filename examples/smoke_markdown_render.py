"""冒烟：长 Markdown 流式渲染性能 + 未闭合代码块兜底。"""

import time

from rich.console import Console
from rich.markdown import Markdown

from forgecode.tui.app import _prepare_markdown_render

md = (
    "# 标题\n\n"
    "**粗体** 和 *斜体* 以及 `行内代码`\n\n"
    "- 列表项 1\n- 列表项 2\n\n"
    "## 代码块\n\n"
    "```python\n" + ("def f(x):\n    return x * 2\n\n" * 40) + "```\n\n"
    "| a | b |\n|---|---|\n| 1 | 2 |\n"
) * 3
print("len:", len(md))
console = Console(force_terminal=True, width=100, file=open("nul", "w", encoding="utf-8", errors="replace"))
t0 = time.time()
for _ in range(50):
    console.print(Markdown(_prepare_markdown_render(md), code_theme="monokai"))
print(f"avg render {((time.time() - t0) / 50) * 1000:.1f}ms")

open_md = md + "\n```\n还没闭合的代码"
prepped = _prepare_markdown_render(open_md)
print("open-fence trunc ok:", len(prepped) < len(open_md))
t1 = time.time()
for _ in range(50):
    console.print(Markdown(_prepare_markdown_render(open_md), code_theme="monokai"))
print(f"avg render open-fence {((time.time() - t1) / 50) * 1000:.1f}ms")

# 长文本边界（约 1 万字符）
_blk = (
    "## 段\n\n**粗体** 文本 `x`\n\n- a\n- b\n\n```python\n"
    + ("def f(x):\n    return x * 2\n\n" * 60)
    + "```\n\n"
)
long_md = _blk * 4
print("long len:", len(long_md))
t2 = time.time()
for _ in range(30):
    console.print(Markdown(_prepare_markdown_render(long_md), code_theme="monokai"))
print(f"avg render long {((time.time() - t2) / 30) * 1000:.1f}ms")
