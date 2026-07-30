# 上下文管理 Checklist

> 每一项通过运行代码或观察行为来验证，聚焦系统行为。

## 实现完整性

### 包与目录结构

- [ ] **C1**：`src/forgecode/compact/` 子包存在，可被其他模块 import。
  - 验证：`ls src/forgecode/compact/` 列出 `compact.py` / `layer1.py` / `layer2.py` / `summary_prompt.py` / `recovery.py` / `token.py` / `state.py` / `const.py` / `__init__.py` 九个核心文件，外加 `tests/compact/` 下的 `test_*.py`。
  - 验证：`python -c "import forgecode.compact"` 退出码 0，无 ImportError。

- [ ] **C2**：常量集中在 `const.py`，未散落到其他文件。
  - 验证：在 `src/forgecode/compact/` 内执行 `grep -rn "= 50000\|= 200000\|= 20000\|= 13000\|= 3000\|= 10000"` 命中点全部在 `const.py`。
  - 验证：`DEFAULT_ANTHROPIC_CONTEXT_WINDOW` 与 `DEFAULT_OPENAI_CONTEXT_WINDOW` 是 `src/forgecode/config/protocol_defaults.py` 中的导出常量，可被 `forgecode.config` 引用。

### 状态对象

- [ ] **C3**：会话状态构造函数全部返回非 None 实例，且自动建立落盘目录。
  - 验证：编写或运行一段最小程序 `new_session_context(".")`，检查返回的 `session_id` 形如 `<unix_ts>-<hex>`，且 `spill_dir` 物理目录存在。
  - 验证：连续调用两次 `new_session_context` 得到不同的 `session_id`。

- [ ] **C4**：替换决策账本提供"已见"与"已替换"两本独立簿子。
  - 验证：单元测试用 kept / replaced / skip 组合检查：kept 后 `_seen_ids` 命中、`_replacements` 不命中；replaced 后两者都命中且 `_replacements` 返回值稳定。

- [ ] **C5**：熔断器有读、记录失败、记录成功、是否跳闸四个动作。
  - 验证：单元测试调 `record_failure` 三次后 `tripped()` 返回 True；再调一次 `record_success` 立即返回 False。

- [ ] **C6**：文件追踪状态线程安全，对外只暴露快照拷贝。
  - 验证：`pytest tests/compact/` 中跑 50 个并发 `record_file` + `snapshot` 的用例无异常。
  - 验证：修改 `snapshot()` 返回的列表不会影响下次调用的结果。

### 两层压缩

- [ ] **C7**：第 1 层提供单条落盘、聚合落盘、幂等、决策冻结四种行为。
  - 验证：对 60K 字符单条结果运行一次 `offload_and_snip`，再运行第二次，输出消息完全一致。
  - 验证：对 3 条 80K 字符的聚合场景，第一次调用后聚合字节回落到 200K 阈值以下。

- [ ] **C8**：第 1 层落盘失败不阻断主流程。
  - 验证：把 `spill_dir` 改成只读路径（`Path.chmod(0o500)`）运行 `offload_and_snip`，工具结果保持原文，账本中该 id 未被标记为已见。

- [ ] **C9**：预览体包含原始字节数、头部预览、落盘路径、重读提示四项。
  - 验证：抓取预览体字符串，用 `in` 操作符断言四个稳定标志子串：① 包含 `original size:` 子串；② 包含 `spill_dir` 路径片段（`Path(session.spill_dir) / tool_use_id` 的尾段）；③ 包含 `head preview` 标记；④ 包含 `文件读取工具` 与 `不要凭头部预览猜测` 两个关键短语。
  - 验证：预览体头部内容长度同时不超过 20 行且不超过 2048 字节（用 `text.count("\n")` + `len(text.encode())` 检查）。
  - 验证：相同入参连续两次构造预览体得到逐字节相等的字符串。

- [ ] **C10**：第 2 层摘要按"分析草稿 + 正式摘要"两阶段输出，正式摘要包含 9 个固定小节。
  - 验证：抓一次摘要请求体的 messages，最后一条 user 内容包含 `<analysis>` 与 `<summary>` 两个标签的说明，以及 9 个小节标题。
  - 验证：解析摘要返回结果，`<summary>` 之外的内容被丢弃。
  - 验证：抓一次完整摘要返回字符串，解析出第 6 部分（用户消息原文），断言会话内每条 user 消息的 content 都能在第 6 部分中作为子串找到（逐条 `in` 检查；覆盖 AC7）。

### 恢复三段

- [ ] **C11**：恢复段拼装三块内容：最近读过的文件、当前可用工具、边界提示消息。
  - 验证：调 `build_recovery_attachment(snapshot, tool_defs)` 后输出文本中能搜到 `最近读过的文件` / `当前可用工具` / `边界提示` 三个分节标题。
  - 验证：超过 5 条文件记录时仅输出最近 5 条；第 6、第 7 条路径**不**出现（反向断言）。
  - 验证：单文件超过 5000 token 时**保留头部**对应的字符片段，尾部出现 `(content truncated)`（不能截掉头部）。

- [ ] **C12**：边界提示消息文案稳定，不在两次调用之间漂移。
  - 验证：连续两次 `build_recovery_attachment` 在相同 snapshot 与 tool_defs 入参下返回的边界提示段逐字节一致（覆盖 C12 / 验收 prompt cache 稳定）。

### Token 估算

- [ ] **C13**：估算函数支持锚点 + 字符增量两种来源；返回类型 `int`。
  - 验证：单元测试 `anchor=0, all_msgs=[], anchor_msg_len=0` 返回 0；`anchor=5000, all_msgs=[msg]`（`msg.content` 350 字符 ASCII）、`anchor_msg_len=0` 返回 `5000 + math.ceil(350/3.5) = 5100`。
  - 验证：`usage_anchor` 返回 int，把 `input_tokens` / `output_tokens` / `cache_read` / `cache_write` 四个字段加和。

- [ ] **C13a**：估算 token 远低于自动阈值时 `manage_context` 不进入 layer2。
  - 验证：构造 `in_.estimated_token = threshold - 1`、`in_.context_window = 200000`，调一次 `manage_context`，断言 fake_provider 的摘要请求计数 == 0（layer2 未触发）；同样输入 `in_.estimated_token = threshold + 1` 时摘要请求计数 == 1（layer2 触发）。

### 手动入口与命令分发

- [ ] **C14**：TUI 输入以 `/` 开头时走命令路径，不发给 LLM。
  - 验证：注入 mock agent，TUI 收到 `/compact` 后 `mock_agent.stream_calls == 0`、`mock_agent.run_force_compact_calls == 1`。
  - 验证：注入 mock agent，TUI 收到 `/unknown` 后 `mock_agent.stream_calls == 0`，消息列表出现未知命令提示。

- [ ] **C15**：Agent 暴露 `run_force_compact` 给 TUI 调用。
  - 验证：方法签名为 `async def run_force_compact(self, conv, tool_defs) -> tuple[int, int]`，TUI 拿到 `(before, after)` 后用于拼系统消息（失败时让异常向上抛）。

### 紧急压缩与哨兵异常

- [ ] **C16**：`llm.PromptTooLongError` 哨兵异常存在并被 provider 包装。
  - 验证：`grep -n PromptTooLongError src/forgecode/llm/__init__.py` 命中。
  - 验证：编写专门的 provider PTL 包装单元测试 `test_anthropic_provider_wraps_prompt_too_long` / `test_openai_provider_wraps_prompt_too_long`：模拟 provider 抛出上下文过长的原始 SDK 异常，断言 `StreamEvent.err` 满足 `isinstance(err, PromptTooLongError) is True` 且 `err.__cause__` 是原 SDK 异常；对非 PTL 异常（500 等）断言 `isinstance` 为 False。

### 配置

- [ ] **C17**：`ProviderConfig` 新增 `context_window` 字段并能从 YAML 解码。
  - 验证：构造一个 yaml 字符串带 `context_window: 80000` 字段，`load(...)` 后对应 `ProviderConfig.context_window == 80000`。

- [ ] **C18**：`effective_context_window(p)` 在四种场景下返回正确值。
  - 验证：anthropic + 未配置 → 200000；openai + 配置 0 → 128000；anthropic + 配置 80000 → 80000；未知 protocol + 未配置 → 200000（保守默认）。

---

## 集成

### compact 与 conversation

- [ ] **I1**：Conversation 提供 `replace_history` 入口，且做深拷贝。
  - 验证：构造 2 条消息调 `replace_history` 后修改原列表，`messages()` 输出不被污染。
  - 验证：传 `None` / 空列表不抛异常，`messages()` 长度为 0。

- [ ] **I2**：管理上下文成功后，conversation 内存列表被替换为新序列。
  - 验证：让 fake_provider 触发一次 layer2 摘要后，`conv.messages()` 长度等于 `1（摘要 + 恢复合并） + 近期原文条数`。

### compact 与 agent

- [ ] **I3**：Agent 本轮迭代开头按 mode 选出 `defs`，把同一份列表同时传给 `ManageInput.tool_defs` 与 `Stream.Request.tools`。
  - 验证：用 set 比对工具名集合 ==（即 len 相等 + 每个名字双向包含）。
  - 验证：对每个工具，把恢复段中渲染的 JSON schema 字符串和 `Request.tools` 中对应工具的 `input_schema` 字段做 `json.loads` 后用 `==` 比较；不允许仅靠工具名匹配。
  - 验证：若 `Request.tools` 含有 N 个工具，恢复段必须正好渲染 N 个工具行，多一个少一个都算失败。
  - 验证：在 Agent 内对 defs 引用做断言——同一轮迭代内 `manage_context` 拿到的 `tool_defs` 列表 `id(...)` == stream 调用的 `Request.tools` 列表 `id(...)`（同一对象引用，而不是分别构造后内容相等）。
  - 验证：Plan Mode 切换时 defs 是 `read_only_definitions()`；Default Mode 时是 `definitions()`；恢复段与 stream 各跑一次都用同一份。

- [ ] **I4**：每轮主对话 stream 完成后用尾事件的 usage 更新锚点（替换，不是累加）。
  - 验证：fake_provider 在尾部 yield 一条带 `usage` 的 `StreamEvent`，Agent 内部 `runtime.usage_anchor` 等于 `input + output + cache_read + cache_write` 之和（int）。

- [ ] **I4-bis**：锚点连续被替换、不累加。
  - 验证：在 fake_provider 上脚本化连续 3 次 yield 不同的 Usage（例如 1000 / 1500 / 2200），断言每次 stream 完成后 `runtime.usage_anchor` 都被替换为最新 Usage 之和（依次 1000、1500、2200），而不是累加（覆盖 AC22）。
  - 验证：摘要请求（layer2 路径）结束后，`runtime.usage_anchor` 不被修改（fake_provider 让摘要请求也 yield Usage，断言 anchor 仍是主对话路径的最近值）。

- [ ] **I5**：ReadFile 工具成功后 Agent 用纯净字节写入 `RecoveryState`。
  - 验证：调用 ReadFile 读一个本地文件，断言 `recovery.snapshot()` 包含该文件路径，且记录内容不含行号前缀（与磁盘原文逐字节相等）。

- [ ] **I6**：管理上下文遇到 PTL 时进入紧急压缩并就地重试一次。
  - 验证：fake_provider 第 1 次 stream yield `PromptTooLongError`，紧急压缩后的第 2 次 stream 正常完成 → 整个 run 成功结束。
  - 验证：紧急压缩后的重试再次 yield PTL 时 Agent 上抛异常，不再进入第三次。

### compact 与 tui

- [ ] **I7**：TUI 命令分发表注册四项（迁移现有 `/exit` / `/plan` / `/do` + 新增 `/compact`）。
  - 验证：`grep -n "/compact\|/exit\|/plan\|/do" src/forgecode/tui/commands.py` 命中四项；`BUILTIN_COMMANDS` 字典长度为 4。
  - 验证：输入 `/anything-else` 走未知命令路径，提示包含可用命令列表。
  - 验证：迁移后 `/exit` 仍然退出；`/plan` 仍然切 plan 模式；`/do` 仍然切 default 模式并启动一轮 run。

- [ ] **I8**：`/compact` 处理完成后 TUI 输出带 token 数对比的系统消息。
  - 验证：mock agent 返回 `(before=120000, after=42000)`，TUI 输出一条系统消息包含两个数字。
  - 验证：mock agent 返回 `(before=500, after=300)` 也能正常显示系统消息，无任何阈值校验拦截（覆盖 AC13）。
  - 验证：mock agent 抛异常，TUI 输出 `压缩失败: <err>`，不退出。

- [ ] **I12**：手动 `/compact` 与 run 串行执行（`_run_lock` 互斥）。
  - 验证：构造一个长跑 run（fake_provider 慢响应），同时启动一个 `asyncio.create_task` 调 `run_force_compact`；断言两次操作按顺序串行完成，没有并发触发 `manage_context`。

### compact 与 config

- [ ] **I9**：`src/forgecode/cli.py` 启动时把 `effective_context_window(p)` 注入到 Agent。
  - 验证：跑 `python -m forgecode` 并配置 anthropic provider 不带 `context_window` → Agent 字段拿到 200000。
  - 验证：把 `context_window: 100000` 加入配置 → Agent 字段拿到 100000。

- [ ] **I10**：`.forgecode/config.yaml.example` 展示新字段用法与默认值注释。
  - 验证：打开示例文件，看到 `context_window: 200000` 之类的字段和 "可选；未配置时按 protocol 默认" 注释。

### 会话目录

- [ ] **I11**：进程启动后 `.forgecode/sessions/<id>/tool-results/` 物理目录被创建。
  - 验证：启动 forgecode 后 `ls .forgecode/sessions/` 出现新子目录；子目录名形如 `<unix_ts>-<hex>`。
  - 验证：进程退出后该目录依然保留，下次启动会再开一个新的子目录。

### Compact 状态事件路由（兑现 spec F24a / F24b）

- [ ] **I13**：自动压缩触发时 Agent yield `Event.compact = CompactEvent(phase=BEFORE_AUTO)` 与 `AFTER_AUTO` 一对事件；阈值未达不 yield。
  - 验证：单测 `test_agent_emits_auto_compact_events`（agent 包）收集 run async generator 所有 Event，断言 `compact is not None` 的事件正好出现 2 次，phase 序列 `[BEFORE_AUTO, AFTER_AUTO]`，且 After 的 `before > after` 与 `err is None`。
  - 验证：单测 `test_agent_no_compact_event_below_threshold`：估算 token 远低于阈值时跑 25 轮，收集到的 Compact 事件数为 0。
- [ ] **I14**：紧急压缩触发时 Agent yield `BEFORE_EMERGENCY` + `AFTER_EMERGENCY` 一对事件。
  - 验证：单测 `test_agent_emits_emergency_compact_events` 收集事件，断言出现 `[BEFORE_EMERGENCY, AFTER_EMERGENCY]` 这一对（无论后续主对话重试是否成功）。
- [ ] **I15**：TUI `_update_streaming` 在 `stream_msg.compact is not None` 时优先走渲染分支，文案由 `format_compact_notice` 统一格式化；手动 `/compact` 完成态回投也走同一格式化函数。
  - 验证：单测 `test_tui_renders_before_auto_notice` / `test_tui_renders_before_emergency_notice` / `test_tui_renders_after_compact_notice` 通过；用 `in` 操作符断言 scrollback 文本含目标短语，并断言此分支不调 `conv.add_user` / 不调 run。
  - 验证：手动 `/compact` 完成后的系统消息文本与 `format_compact_notice(CompactEvent(phase=AFTER_*, ...))` 字节相同（统一格式化的体现）。

---

## 编译与测试

- [ ] **B1**：`python -m compileall src/forgecode` 退出码 0，无语法错误；`python -c "import forgecode"` 成功。

- [ ] **B2**：`ruff check src/forgecode/` 无告警。

- [ ] **B3**：`ruff format --check src/forgecode/compact/ src/forgecode/agent/ src/forgecode/conversation.py src/forgecode/llm/ src/forgecode/tui/ src/forgecode/config/ src/forgecode/cli.py` 输出为空（全部已格式化）。

- [ ] **B4**：`ruff check --select I src/forgecode/compact/` 输出为空；import 分组遵循"标准库 / 第三方 / 本地"三段，组间空行隔开（PEP 8 + isort 默认风格）。

- [ ] **B5**：`pytest tests/compact/` 全部通过。覆盖：
  - 状态对象（决策冻结、并发安全）
  - token 估算（锚点 + 字符增量、usage 合并）
  - 第 1 层（单条 / 聚合 / 幂等 / 决策冻结 / 落盘失败降级）
  - 摘要 prompt（结构断言、`<summary>` 解析三种 case）
  - 恢复段（5 文件上限、5000 token 截断、工具列表逐项匹配）
  - 第 2 层（近期原文边界、tool_use/tool_result 配对修正、PTL 自重试、按比例丢弃）
  - 编排（自动触发阈值、熔断跳过、手动绕过）

- [ ] **B6**：`pytest tests/compact/ -k concurrent` 通过，无异常。重点用例：50 个 thread 并发往 `RecoveryState` 写入与 `snapshot`。

- [ ] **B7**：`pytest tests/test_conversation.py` 通过；`replace_history` 深拷贝与 `None` 输入两个用例覆盖。

- [ ] **B8**：`pytest tests/test_config.py` 通过；`effective_context_window` 四种 case 覆盖。

- [ ] **B9**：`pytest tests/agent/` 通过；新增"紧急压缩成功"与"紧急压缩后再次 PTL 上抛"两个用例。

- [ ] **B10**：`pytest tests/tui/` 通过；`/compact` 走命令路径与 `/unknown` 友好提示两个用例。

- [ ] **B11**：注释不出现"参考"、"取自"、"对齐"、"mirror"、"镜像"、"TS 实现"、"Go 实现"等外部引用语。
  - 验证：`grep -rn "参考\|取自\|对齐.*实现\|mirror\|镜像\|TS 实现\|TypeScript 实现\|Go 实现\|as in\|课程实现\|README" src/forgecode/compact/ src/forgecode/agent/ src/forgecode/conversation.py src/forgecode/llm/ src/forgecode/tui/ src/forgecode/config/` 全部无命中。

- [ ] **BB1**：文档自检——spec / plan / task / checklist 本身也不出现外部引用语。
  - 验证：`grep -rnE --exclude=checklist.md "取自 ch|取自 README|参考课程|参考 Claude|参考 TS|参考 Type|参考 Go|对齐 ch|对齐课程|对齐.*实现|镜像实现|as in " docs/python/ch08/` 无命中。模式只匹配具体短语；`--exclude=checklist.md` 排除自身，避免本条 BB1 与 B11 把正则模式当字符串列出后构成 self-fire。

- [ ] **B12**：`.forgecode/config.yaml.example` 可被解析。
  - 验证：编写一个测试 fixture，`yaml.safe_load(Path(".forgecode/config.yaml.example").read_text())` 不报错；映射到 `Config` 后 `validate()` 通过；新增的 `context_window` 字段在解码后非零。

---

## 端到端场景

### 场景 E1：长会话不撞墙

- [ ] **触发**：构造一个 fake_provider 脚本，30 轮迭代每轮返回一个工具调用，工具结果 30KB，配合一个较小的 `context_window`（例如 50000）。
- [ ] **预期**：30 轮完整跑完，无未捕获异常；中途至少触发一次自动 layer2 摘要；最终 `conv.messages()` 长度远小于 30。
- [ ] **观察方式**：在 Agent 主循环内打日志或在测试里数 layer2 触发次数；测试用例 assert `run` async generator 正常 `StopAsyncIteration`。

### 场景 E2：单条大工具结果

- [ ] **触发**：fake_provider 一轮返回一个工具调用，工具回填 80KB（80000 字节）字符串。
- [ ] **预期**：下一轮 stream 请求 messages 中该工具结果 content 已被替换为预览体，通过 4 条 `in` 断言：① 包含 `original size:` 子串与字节数（"80000"）；② 包含 `[saved to]` 与 `spill_dir` 尾段路径片段；③ 包含 `head preview` 标记；④ 包含 `文件读取工具` 与 `不要凭头部预览猜测` 两个关键短语。`.forgecode/sessions/<id>/tool-results/<tool_use_id>` 文件存在且 size = 80000 字节。
- [ ] **观察方式**：用 fake_provider 捕获第 N+1 次 stream 请求体，检查 content 字段；用 `Path(...).stat().st_size` 检查落盘文件大小。

### 场景 E3：单轮聚合超标

- [ ] **触发**：一条 RoleTool 消息内的 `tool_results` 列表含 3 条工具结果，每条 80KB（合计 240KB）。
- [ ] **预期**：至少 2 条被替换、落盘，未被替换的工具结果保持原文；下一轮请求中该 RoleTool 消息内剩余 `tool_results` 的 content 字节聚合 ≤ 200000 字节。
- [ ] **观察方式**：捕获 stream 请求体，sum 该消息内所有 `tool_results.content` 长度；检查 `spill_dir` 至少出现 2 个文件。

### 场景 E4：决策冻结

- [ ] **触发**：同一个 `tool_use_id` 在第 N 轮被决定不替换；继续跑到第 N+5 轮，期间内容未变。
- [ ] **预期**：第 N+1 ~ N+5 轮的请求体中该工具结果始终保持原文，无任何替换发生。
- [ ] **触发**：另一个 `tool_use_id` 在第 M 轮被决定替换。
- [ ] **预期**：第 M+1 ~ M+5 轮的请求体中该工具结果使用与第 M 轮逐字节相同的预览体（`==` 比较为 True）。
- [ ] **观察方式**：捕获多轮 stream 请求体，对同一 `tool_use_id` 在不同轮次的 content 字符串做 `==` 比较。

### 场景 E5：手动 /compact

- [ ] **触发**：在 TUI 启动后输入 `/compact`，压缩前估算 token = 1000（远低于自动阈值 167000）。
- [ ] **预期**：① fake_provider 收到一次摘要请求（`Request.tools is None`）——证明手动路径无视阈值；② 收到结果后 conversation 被替换为"摘要 + 恢复段 + 近期原文"（首条是合并了摘要与三段恢复的单条 user 消息，第 6 部分包含本次会话所有 user 消息原文，按出现顺序逐条可定位）；③ TUI 输出系统消息 `已压缩，token 从 X 降至 Y`，X、Y 都是非负整数；断言 X = 入口 `estimated_token`（= 1000），Y = 替换后估算（`estimate_tokens(0, new_msgs, 0)`）；④ stream 普通对话路径（主对话 run）未被调用。
- [ ] **观察方式**：mock agent 计数 `run_force_compact` / `run` 调用次数；fake_provider 捕获摘要请求体；TUI 输出断言。

### 场景 E6：紧急压缩

- [ ] **触发**：fake_provider 在第 K 次 stream yield `StreamEvent(err=wrapped_ptl)`（wrapped 通过 `isinstance` 命中 `PromptTooLongError`）。
- [ ] **预期**：① Agent 先强制跑一次 `offload_and_snip` 把大工具结果挪走（断言 `spill_dir` 多了文件）；② 再调用一次摘要请求（紧急路径）；③ conversation 被替换；④ `runtime.usage_anchor` 与 `anchor_msg_len` 被清零；用新消息列表重新估算 token；若估算 < `context_window - MANUAL_SAFETY_MARGIN`，**重试一次**第 K 次请求；⑤ 重试成功则整体流程继续；⑥ 重试再次 yield PTL 时上抛异常，不进入第三次。
- [ ] **观察方式**：fake_provider 脚本化三组场景：① 摘要 + 重试成功；② 摘要 + 重试再次 PTL；③ 摘要 + 重新估算后**仍** ≥ `context_window - MANUAL_SAFETY_MARGIN`（Agent 不发起第二次 stream 请求，直接上抛异常）。三个测试用例分别 assert。

### 场景 E7：熔断

- [ ] **触发 A（连续失败跳闸）**：让 fake_provider 对摘要请求连续 3 次抛异常（非 PTL 即可，例如 500）。
- [ ] **预期 A**：① 第 3 次失败后熔断器跳闸；② 第 4 次估算 token 跨越自动阈值时，`manage_context` 不再触发 layer2（用 `fake_provider.summarize_calls` 计数断言：第 4 次进入 `manage_context` 后计数不增加）；③ 手动输入 `/compact` 时仍能正常执行 layer2，不被熔断器拦截。
- [ ] **触发 B（PTL 用光也计入熔断）**：让 fake_provider 对摘要请求持续 yield PTL 直到 groups 全部丢光。
- [ ] **预期 B**：自动路径下该轮算一次失败，`auto_tracking._consecutive_failures += 1`；连续 3 次后跳闸。
- [ ] **触发 C（成功清零）**：fake_provider 摘要响应序列为 `[err, err, ok, err, err, err]`。
- [ ] **预期 C**：6 轮后熔断器才跳闸（而不是 5 轮），证明第 3 个 ok 把计数清零了。观察方式：在每次 `manage_context` 后读 `auto_tracking._consecutive_failures`，断言序列为 [1, 2, 0, 1, 2, 3]。
- [ ] **观察方式**：mock agent / fake_provider 内查询 `auto_tracking.tripped()` 状态与 `_consecutive_failures`；通过 `fake_provider.summarize_calls` 计数断言 layer2 是否真的被发起。

### 场景 E8：压缩后恢复

- [ ] **触发**：① 在压缩前先后读过 7 个不同文件；② 触发一次摘要。
- [ ] **预期**：压缩后下一轮 stream 请求 messages 中首条 user 消息的 content 同时包含：
  - 摘要 9 部分（标题字面匹配），且第 6 部分包含本次会话所有 user 消息原文（逐条 `in` 命中）。
  - 最近读过的文件块：仅展示最近 5 个，按时间戳倒序；断言恢复段文本中**不**出现第 6、第 7 个文件的路径子串（反向断言）；并断言出现的 5 个路径在文本中的位置顺序与时间戳倒序一致（每两个相邻路径用 `text.index(...)` 取位置，前者位置必小于后者）。
  - 当前可用工具块：每个工具一行；用 set 比对工具名集合 == `Request.tools` 的工具名集合；对每个工具做 `json.loads(schema)` 后 `==` 比较 `input_schema` 内容；工具数量正好等于 `Request.tools` 长度（多一个少一个都失败）。
  - 边界提示消息块：固定文案，明确告诉模型需要原文请重读。
- [ ] **观察方式**：捕获摘要后第 1 次 stream 请求 messages；按文本片段断言三段标题；用 set 比对工具名集合；用反向 `in` 断言被丢弃的文件路径不出现。

### 场景 E9：多 provider context_window

- [ ] **触发 1**：anthropic provider 不配置 `context_window`。
- [ ] **预期 1**：Agent 拿到的 `context_window = 200000`；自动阈值 = `200000 - 20000 - 13000 = 167000`。
- [ ] **触发 2**：openai provider 不配置 `context_window`。
- [ ] **预期 2**：Agent 拿到的 `context_window = 128000`；自动阈值 = `128000 - 20000 - 13000 = 95000`。
- [ ] **触发 3**：anthropic provider 配置 `context_window=100000`。
- [ ] **预期 3**：Agent 拿到的 `context_window = 100000`；自动阈值 = 67000；手动/紧急阈值 = `100000 - 20000 - 3000 = 77000`。
- [ ] **观察方式**：在三种配置下分别跑一次 run，构造刚好跨越阈值的估算 token，看是否触发 layer2。

### 场景 E10：不切断 tool_use / tool_result

- [ ] **触发**：构造一段对话尾部形如 `[..., user, assistant(tool_calls=[A]), tool(result of A), assistant(tool_calls=[B]), tool(result of B)]`，让 `pick_recent_tail` 按"两个下界都满足"算出的截断点正好落在 `tool(result of A)` 单条上。
- [ ] **预期**（并列断言）：
  ① 返回列表第一条 role 必为 `"user"` 或 `"assistant"`，不可为 `"tool"`；
  ② 若第一条为 assistant 且有 `tool_calls`，则列表中必须包含对应的 tool 消息（即 tool_use / tool_result 配对完整）；
  ③ 列表满足 `len(列表) >= 5` 且 `message_chars(列表)/3.5 >= 10000`（两个下界都满足）；
  ④ 列表长度不大于原 msgs 长度（即不会把不存在的消息算进去）。
- [ ] **观察方式**：单元测试构造对话后调 `pick_recent_tail`，按上述 4 条断言。

### 场景 E11：摘要请求自身 PTL

- [ ] **触发 A**：fake_provider 对前 3 次摘要请求 yield `PromptTooLongError`，第 4 次 yield 正常摘要。
- [ ] **预期 A**：① 前 3 次每次丢最旧的一组"用户提交 + 一组 assistant/tool 往返"后重试；② 第 4 次成功；③ 整个 `run_summary` 返回成功；④ 失败计数清零。
- [ ] **观察方式 A**：初始 groups 数为 G。fake_provider 记录每次摘要请求里的 groups 数（按 user role 切分），断言序列为 `[G, G-1, G-2, G-3]`，第 4 次（G-3）返回成功。
- [ ] **触发 B（超过 3 次后按比例丢）**：fake_provider 对前 4 次摘要请求都 yield PTL。
- [ ] **预期 B**：第 4 次重试切到按比例丢，`drop = math.ceil(剩余 * 0.2)` 且 `drop >= 1`；连续记录每次的 groups 数序列满足该递推。
- [ ] **触发 C（丢光仍失败）**：fake_provider 持续 yield PTL 直到消息组全部丢光。
- [ ] **预期 C**：抛最后一次异常；自动路径下 `auto_compact` 抛非 None 异常且熔断计数 +1；同等条件下 `force_compact`（手动/紧急）抛异常但熔断计数不变。系统**不**发送 messages 为空的摘要请求。

### 场景 E12：tmux 真实运行

- [ ] **触发**：`uv sync` 或 `pip install -e .`，在 tmux 中启动 `python -m forgecode`，配置 anthropic provider。
- [ ] **预期**：
  - 让 Agent 读一个 80KB 的本地文件 → `.forgecode/sessions/<id>/tool-results/` 下出现该工具调用 id 的文件；
  - 把 `context_window` 临时改成 80000（**不能低于 33000**，否则 `80000 - 33000 = 47000` 是负数会让自动压缩在每轮都触发，无法验证真实压缩信号），连续几轮对话后看到自动压缩日志；
  - 任意时刻输入 `/compact` 看到系统消息 `已压缩，token 从 X 降至 Y`；
  - 输入 `/unknown` 看到友好提示，未发 LLM；
  - 输入 `/exit` / `/plan` / `/do` 行为与本章迁移前一致；
  - 进程退出后 `.forgecode/sessions/<id>/` 仍存在，下次启动再开新子目录。
- [ ] **观察方式**：tmux 中目测；用 `ls .forgecode/sessions/` 与 `cat` 抽查落盘文件；`git status` 干净（覆盖 I12 `.gitignore`）。

### 场景 E13：自动压缩 UX 状态提示（兑现 spec F24a）

- [ ] **触发**：构造 fake_provider 脚本让某轮主对话开始前估算 token 跨越 `context_window - 20000 - 13000` 阈值；fake_provider 摘要请求 `await asyncio.sleep(0.2)` 后 yield 成功，模拟真实 LLM 摘要耗时。
- [ ] **预期**：
  - 摘要请求开始前（即 fake_provider 的摘要 stream 还没 yield 任何 chunk），TUI scrollback 已经打印 `正在压缩上下文...`（`in` 命中）。
  - 摘要请求完成后，TUI 接着打印 `已压缩，token 从 <before> 降至 <after>`，其中 before 和 after 都是非负整数；用 `re.match(r"^已压缩，token 从 \d+ 降至 \d+$", text)` 匹配；before > after。
  - 收集到的 Event 序列里在主对话 `_stream_once` 启动之前出现 `compact=CompactEvent(phase=BEFORE_AUTO)`；`manage_context` 返回后出现 `compact=CompactEvent(phase=AFTER_AUTO)`；两个事件之间不出现 Text / Tool 事件（说明 TUI 显示状态时 LLM 主对话还未开始）。
- [ ] **观察方式**：测试驱动 `Agent.run`，收集 events 列表并断言 phase 顺序；mock TUI（或集成测试启动 Textual `App.run_test()` 拿到 pilot 后用 `pilot.app.query_one(RichLog).lines` 收集 notice_block 文本逐条断言）。

### 场景 E14：紧急压缩 UX 状态提示（兑现 spec F24b）

- [ ] **触发**：fake_provider 在第 K 次主对话 stream yield `StreamEvent(err=wrapped_ptl)`；之后再为 Agent 准备一次摘要响应 + 一次重试主对话响应。
- [ ] **预期**：
  - PTL 发生后、紧急 `manage_context` 启动前，TUI scrollback 出现 `上下文撞墙，自动压缩中...`（`in` 命中）。
  - 紧急压缩成功后 TUI 接着出现 `已压缩，token 从 X 降至 Y`；之后主对话 `_stream_once` 重试一次成功，TUI 继续渲染重试后 LLM 的 Text / Tool 事件。
  - 收集到的 Event 序列：`[CompactEvent(BEFORE_EMERGENCY), CompactEvent(AFTER_EMERGENCY, err=None), Text/Tool... (重试结果)]`。
- [ ] **触发（失败分支）**：fake_provider 在紧急压缩内部让摘要请求 PTL 全部丢光后仍失败（不可恢复），或重试主对话再次 yield PTL。
- [ ] **预期（失败分支）**：
  - TUI 显示 `压缩失败：<err>` 系统消息（`in "压缩失败"` 命中）；Event 序列里 AFTER_EMERGENCY 的 `err is not None`。
  - 不会发起第三次 stream 请求（`fake_provider.stream_calls <= 2`）。
- [ ] **观察方式**：同 E13；fake_provider 维护 `stream_calls` / `summarize_calls` 计数器并在测试结尾断言。