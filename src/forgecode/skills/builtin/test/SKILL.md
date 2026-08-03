---
name: test
description: 运行项目测试并分析失败原因
allowed_tools: [bash, read_file, grep, glob]
mode: inline
---

# Test

按项目类型运行测试并分析失败：

1. 先通过 `glob` 查看项目布局（pyproject.toml / package.json / Cargo.toml 等）。
2. 运行项目对应的测试命令，例如 `pytest`、`npm test` 或 `cargo test`。
3. 若失败，读取失败输出与相关源码，定位根因并给出修复建议。
4. 不跳过失败、不谎报通过；最终汇总通过/失败统计。

附加测试要求（可为空）：

$ARGUMENTS