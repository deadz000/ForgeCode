---
name: commit
description: 分析 git diff 并生成规范的 commit
allowed_tools: [bash, read_file, grep]
mode: inline
---

# Commit

按以下步骤完成一次规范的 git commit：

1. 先执行 `git status --porcelain` 与 `git diff`，了解当前改动。
2. 如果 diff 过大，用 `grep` / `read_file` 聚焦关键文件，不猜测改动内容。
3. 按改动类型组织提交信息，使用简洁的祈使句，如 `fix: ...` / `feat: ...`。
4. 只提交用户明确要求的范围，不做无关改动。

用户附加要求（可为空）：

$ARGUMENTS