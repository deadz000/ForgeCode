---
name: review
description: 客观审查代码变更与潜在问题
allowed_tools: [read_file, grep, glob, bash]
mode: fork
fork_context: none
---

# Review

审查当前代码变更，输出结构化报告：

1. 用 `git status --porcelain` 与 `git diff` 定位变更文件。
2. 读取关键文件，寻找 bug、可读性问题、边界条件和可简化处。
3. 不臆测未读到的代码；每个结论尽量给出文件与行号。
4. 最终报告按严重程度排序：High / Medium / Low。

审查重点（可为空）：

$ARGUMENTS