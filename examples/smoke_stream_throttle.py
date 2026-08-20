"""冒烟：模拟真实流式输出（约 200 字符/s）下 Markdown 渲染的触发频率与负载。"""

import time

from rich.console import Console
from rich.markdown import Markdown

from forgecode.tui.app import (
    _MD_RENDER_CHUNK,
    _MD_RENDER_INTERVAL,
    _prepare_markdown_render,
)

# 10k 字符的长回答（含代码块），按 40 字符/chunk 流式吐出
_blk = (
    "## 段\n\n**粗体** 文本 `x`\n\n- a\n- b\n\n```python\n"
    + ("def f(x):\n    return x * 2\n\n" * 60)
    + "```\n\n"
)
full = _blk * 6
print("full len:", len(full))
console = Console(force_terminal=True, width=100, file=open("nul", "w", encoding="utf-8", errors="replace"))

last_len = 0
last_at = 0.0
render_count = 0
render_total_ms = 0.0
now = 0.0
text = ""
for ch in range(0, len(full), 40):
    text = full[:ch]
    now += 40 / 200.0  # 40 字符按 200 字符/s 流速
    if len(text) - last_len >= _MD_RENDER_CHUNK or now - last_at >= _MD_RENDER_INTERVAL:
        t0 = time.time()
        console.print(Markdown(_prepare_markdown_render(text), code_theme="monokai"))
        render_total_ms += (time.time() - t0) * 1000
        render_count += 1
        last_len = len(text)
        last_at = now

elapsed_s = len(full) / 200.0
print(
    f"simulated stream {elapsed_s:.1f}s, markdown renders {render_count}, "
    f"render cpu {render_total_ms:.0f}ms ({render_total_ms / (elapsed_s * 1000) * 100:.0f}% of wall)"
)
