# Hook 生命周期挂钩系统 Checklist

> 每一项通过运行代码或观察行为来验证,聚焦系统行为。

## 实现完整性### 权限匹配器扩展

- [ ] `permission.Matcher` Protocol 存在,四种实现(`ExactMatcher` / `GlobMatcher` / `RegexMatcher` / `NotMatcher`)各自可单独导入并运行(验证:`pytest tests/permission/test_matcher.py -v` 通过)
- [ ] `permission.Rule` 已替换 pattern 为 `matcher` 字段,`parse_rule` 能识别 `=` / `~` / `!` 前缀(验证:`pytest tests/permission/test_rule.py -v` 通过)
- [ ] `to_rule_set` 在 `parse_rule` 失败时输出 stderr 错误日志(验证:单测用 `capsys` 捕获含 `parse failed`)

### Hook 包

- [ ] `forgecode.hook` 包存在且可导入(验证:`python -c "import forgecode.hook"` 不抛 ImportError)
- [ ] 11 个 `Event` 成员全部声明且 `is_blocking` 仅对 `PRE_TOOL_USE` / `USER_PROMPT_SUBMIT` 返回 True(验证:`pytest tests/hook/test_event.py` 或集成在 `test_engine.py`)
- [ ] `load(...)` 能解析合法 YAML 并构造 Engine(验证:`test_loader.py` 全部通过)
- [ ] Loader 对字段缺失 / 枚举错 / async + 拦截事件冲突 / matcher 编译失败均报 stderr 并跳过该条(验证:对应 `test_loader.py` 子用例通过)
- [ ] `Engine.dispatch` 按声明顺序执行 rule 且拦截后中断后续(验证:`test_engine.py::test_dispatch_blocking` 通过)
- [ ] Executor 的 shell `returncode == 2` 触发 blocked、`returncode == 0` 放行、其它非 0 视为失败不拦截(验证:`test_executor.py::test_run_shell_*` 通过)
- [ ] Executor 的 HTTP 在 body 含 `{"decision":"block","reason":"..."}` 时触发 blocked(验证:`test_executor.py::test_run_http_*` 通过)
- [ ] Executor 的 prompt 动作通过 `ExecutionResult.prompt` 字段返回文本(验证:`test_executor.py::test_run_prompt` 通过)
- [ ] Executor 的 subagent 动作仅 stderr 输出占位日志、不阻塞(验证:`test_executor.py::test_run_subagent` 通过)
- [ ] only_once 状态在 `SessionRuntime` 上,`/clear` 与 `/resume` 时被 `reset_for_new_session` 清空(验证:`test_runtime.py::test_reset_for_new_session` 通过)

### agent / tui 集成

- [ ] `Agent.__init__` 接受 `hook_engine` 参数,agent 内部 `_dispatch_hook` 在 11 个 emit 点全部调用(验证:`test_agent.py::test_hook_emit_*` 覆盖每个事件)
- [ ] tui `_submit()` 在 UserPromptSubmit 拦截时不消费输入框、显示错误块(验证:`test_stream.py::test_submit_blocked` 通过)
- [ ] tui `on_mount()` 末尾派发 SessionStart 事件(验证:`test_app.py::test_init_dispatch_session_start` 或集成测试)
- [ ] `/clear` / `/resume` / `/exit` 触发 SessionEnd(验证:`test_commands.py::test_clear_dispatch_session_end` 等)
- [ ] `cli.main` 退出前兜底 SessionEnd(验证:cli 调用链审查)
- [ ] `/hooks` 命令注册到命令表(验证:`test_hooks_command.py` 中 `/hooks` 命令存在 + 输出格式正确)
- [ ] `pending_reminders` 在 `Agent.run` 取出后被清空(验证:`test_runtime.py::test_take_reminders` 通过)

## 集成

- [ ] `hook.Engine` 与 `permission.Matcher` 共用同一套匹配实现(验证:`forgecode.hook` 包不重复实现 exact/regex/glob)
- [ ] `hook.Engine` 接入 `Agent.run` 后所有现有 agent 测试不破坏(验证:`pytest tests/agent/ -v` 全过)
- [ ] `hook.Engine` 接入 tui 后所有现有 tui 测试不破坏(验证:`pytest tests/tui/ -v` 全过)
- [ ] PreToolUse 拦截结果当 tool_result 回灌后,LLM 视角看到的是 `is_error=True` 的 `ToolResult`,`content` 含 `[hook <name>] <reason>`(验证:`test_agent.py` 检查 `results[call_id]` 字段)
- [ ] reminder 注入路径与 plan reminder 协同——同一轮 LLM 请求的 reminder 串同时含两类(验证:`test_agent.py` 中构造 plan 模式 + hook prompt 注入,断言 reminder 串包含两段)

## 编译与测试

- [ ] 项目可导入无错误:`python -c "import forgecode"`
- [ ] 入口可启动:`python -m forgecode --help` 正常输出
- [ ] 所有单元测试通过:`pytest`
- [ ] ruff 检查通过:`ruff check src tests`
- [ ] (可选)类型检查:`mypy src/forgecode/hook` 无 error

## 端到端场景(tmux 实跑)

每个场景在 tmux 内启动一个 forgecode 实例完成,验证人工/可视化行为。

### 场景 1:PreToolUse shell 拦截 write_file**预置:** 在 `.forgecode/hooks.yaml` 写一条 hook:
```yaml
hooks:
  - name: block-write
    event: PreToolUse
    if:
      all_of:
        - field: tool_name
          match: { type: exact, value: write_file }
    action:
      type: shell
      command: "echo blocked by hook >&2; exit 2"
```

**步骤:**
- [ ] tmux 启动 `python -m forgecode`
- [ ] 给 LLM 输入"创建一个文件 hello.txt 内容是 hi"
- [ ] LLM 应触发 write_file,工具被拦截
- [ ] scrollback 内 tool_result 显示 `[hook block-write] blocked by hook`、文件未创建
- [ ] LLM 收到反馈后调整回应,不死循环

### 场景 2:SessionStart prompt 注入**预置:**
```yaml
hooks:
  - name: zh-cn-default
    event: SessionStart
    action:
      type: prompt
      text: "默认用 zh-CN 回复"
```

**步骤:**
- [ ] tmux 重启 forgecode
- [ ] 立刻发一句英文输入"hi there"
- [ ] LLM 应该用中文回复(因为 reminder 区注入了 zh-CN 指令)

### 场景 3:PostToolUse async shell 后台 ruff format**预置:**
```yaml
hooks:
  - name: ruff-after-write
    event: PostToolUse
    if:
      all_of:
        - field: tool_name
          match: { type: exact, value: write_file }
        - field: tool_input.path
          match: { type: glob, value: "**/*.py" }
        - field: is_error
          match: { type: exact, value: "False" }
    action:
      type: shell
      command: "ruff format \"$(jq -r .tool_input.path)\""
    async: true
    timeout: 5s
```

**步骤:**
- [ ] tmux 启动 forgecode
- [ ] 让 LLM 写一个故意排版不整齐的 Python 文件(如缩进错乱)
- [ ] LLM 完成写入后主对话立即进入下一轮,不停顿
- [ ] 验证文件被 `ruff format` 格式化(可手动 `cat` 该文件)

### 场景 4:UserPromptSubmit 拦截 delete 关键字**预置:**
```yaml
hooks:
  - name: warn-delete
    event: UserPromptSubmit
    if:
      all_of:
        - field: prompt
          match: { type: regex, value: "(?i)delete" }
    action:
      type: shell
      command: "echo \"用户消息含 delete 关键字\" >&2; exit 2"
```

**步骤:**
- [ ] tmux 启动 forgecode
- [ ] 输入"请帮我 delete 那个文件"
- [ ] 输入被拦截,scrollback 内显示 `[hook warn-delete] 用户消息含 delete 关键字`
- [ ] 输入框内容仍在(被退回用户重新编辑)
- [ ] LLM 端未收到这条 user 消息(不发起请求)

### 场景 5:Stop HTTP 通知**预置:**
- 本地起 echo server:`python3 -m http.server 9999 --bind 127.0.0.1` 或 `nc -l 9999`
```yaml
hooks:
  - name: notify-stop
    event: Stop
    action:
      type: http
      url: "http://127.0.0.1:9999/done"
      method: POST
```

**步骤:**
- [ ] tmux 启动 forgecode
- [ ] 让 LLM 简单回答一个问题后停止
- [ ] echo server 收到一次 POST,body 含 `"event":"Stop"`

### 场景 6:only_once + PreUserMessage**预置:**
```yaml
hooks:
  - name: first-turn
    event: PreUserMessage
    only_once: true
    action:
      type: shell
      command: "echo first-turn-fired >&2"
```

**步骤:**
- [ ] tmux 启动 forgecode
- [ ] 第一轮发任意消息,stderr 出现 `first-turn-fired`
- [ ] 第二轮发消息,stderr 没有再次出现
- [ ] 执行 `/clear` 进新会话,再发消息,stderr 重新出现 `first-turn-fired`

### 场景 7:错误配置不阻断启动**预置:** `hooks.yaml` 含一条非法 hook:
```yaml
hooks:
  - name: bad-async
    event: PreToolUse
    async: true
    action:
      type: shell
      command: "echo x"
  - name: good-hook
    event: SessionStart
    action:
      type: shell
      command: "echo ok"
```

**步骤:**
- [ ] tmux 启动 forgecode
- [ ] forgecode 启动期 stderr 打印 `hook "bad-async": async not allowed for blocking events, skipped`
- [ ] forgecode 仍然成功进入 idle 状态
- [ ] `/hooks` 命令仅列出 `good-hook`、未列 `bad-async`

### 场景 8:`/hooks` 命令**预置:** 一份包含 3 条合法 hook 的 `hooks.yaml`(任意 event 组合)

**步骤:**
- [ ] tmux 启动 forgecode
- [ ] 输入 `/hooks` 回车
- [ ] 输出按 event 分组,每条一行 `  <name>  <event>  <action.type>  [flags]`
- [ ] 末尾显示 `Loaded from: .../hooks.yaml`

### 场景 9:端到端组合(AC17)**预置:** `hooks.yaml` 包含场景 1、2、3、4 全部 hook

**步骤:**
- [ ] tmux 启动 forgecode
- [ ] 首轮:SessionStart 注入 zh-CN(场景 2),Agent 准备就绪
- [ ] 输入"帮我创建 hello.py,然后 ruff format 一下"
- [ ] LLM 调 write_file 创建文件 → 被场景 1 的 hook 拦截 → LLM 重试(可能换 edit_file)或换 bash 调 ruff
- [ ] 整个过程不卡顿、无未捕获异常栈
- [ ] `/hooks` 命令仍可工作显示 4 条 hook