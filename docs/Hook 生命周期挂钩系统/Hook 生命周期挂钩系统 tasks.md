# Hook 生命周期挂钩系统 Tasks## 文件清单

| 操作 | 文件 | 职责 |
|------|------|------|
| 新建 | `src/forgecode/permission/matcher.py` | Matcher Protocol、四种实现、`compile_matcher` 工厂 |
| 新建 | `tests/permission/test_matcher.py` | 四种 type × 边界条件覆盖 |
| 修改 | `src/forgecode/permission/rule.py` | `parse_rule` 识别前缀、`Rule` 持有 `matcher` 替代 pattern 字符串、`hit_any` / `match_rule` 改造 |
| 修改 | `tests/permission/test_rule.py` | 扩展用例覆盖新语法 |
| 修改 | `src/forgecode/permission/settings.py` | `to_rule_set` 改造:失败 rule 走 stderr |
| 修改 | `tests/permission/test_settings.py` | 验证 stderr 报错与跳过逻辑 |
| 新建 | `src/forgecode/hook/__init__.py` | 包标识 + 暴露 `Engine` / `Event` / `load` / `DispatchResult` |
| 新建 | `src/forgecode/hook/event.py` | 11 个 `Event` 枚举 + 拦截类列表 + `is_blocking` 判定 |
| 新建 | `src/forgecode/hook/rule.py` | `Rule` / `Condition` / `Action` / `Payload` 数据结构 |
| 新建 | `src/forgecode/hook/matcher.py` | `eval_condition` / `get_by_path` |
| 新建 | `src/forgecode/hook/loader.py` | YAML 解析、双层合并、字段校验 |
| 新建 | `tests/hook/test_loader.py` | 字段校验、加载错误、合并测试 |
| 新建 | `src/forgecode/hook/engine.py` | `Engine` + dispatch 主流程 + only_once |
| 新建 | `tests/hook/test_engine.py` | 各事件 dispatch、拦截、reminder、once 覆盖 |
| 新建 | `src/forgecode/hook/executor.py` | 四类 action 执行器 |
| 新建 | `tests/hook/test_executor.py` | shell exit2、http block、prompt、subagent stub |
| 修改 | `src/forgecode/agent/runtime.py` | `SessionRuntime` 加 `pending_reminders` + `hook_engine` 字段 + `reset_for_new_session` 清空 |
| 修改 | `tests/agent/test_runtime.py` | 验证 `pending_reminders` 行为 |
| 修改 | `src/forgecode/agent/agent.py` | `Agent.__init__(..., hook_engine=...)` 参数、11 个 emit 点(部分由 tui 触发,agent 负责 PreUserMessage/PreToolUse/PostToolUse/PreCompact/PostCompact/Stop/Notification) |
| 修改 | `tests/agent/test_agent.py` | 拦截路径测试 |
| 新建 | `src/forgecode/tui/hooks.py` | `/hooks` 命令 handler、App 的 hook 查询方法 |
| 修改 | `src/forgecode/tui/app.py` | `AppParams` 加 `hook_engine`、App 持有;`on_mount` 触发 SessionStart |
| 修改 | `src/forgecode/tui/stream.py` | `_submit()` 内 UserPromptSubmit dispatch + 拦截集成 |
| 修改 | `src/forgecode/tui/commands.py` | `/clear`、`/resume` 触发 SessionEnd + SessionStart/Resume |
| 修改 | `src/forgecode/command/builtins.py` | 加 `/hooks` 内置命令 |
| 修改 | `src/forgecode/command/ui.py` | UI 接口加 hook 查询方法 |
| 修改 | `src/forgecode/cli.py` | 加 `hook.load(root)` 与 wiring;SessionEnd 兜底 |
| 修改 | `pyproject.toml` | 新增依赖 `httpx`(若未引入) |

## T1: 实现 `permission.Matcher` 接口与四种类型**文件:** `src/forgecode/permission/matcher.py`
**依赖:** 无
**步骤:**
1. 新建 `matcher.py`,声明 `Matcher(Protocol)`,要求 `match(s: str) -> bool` 与 `__str__`
2. 实现 4 个 frozen dataclass:
   - `ExactMatcher(value: str)`:`match` 返回 `s == value`
   - `GlobMatcher(pattern: str, is_command: bool)`:command 模式调 `match_command`,否则 `match_path`;`__str__` 返回 `pattern`
   - `RegexMatcher(src: str, compiled: re.Pattern[str])`:`match` 返回 `compiled.search(s) is not None`
   - `NotMatcher(inner: Matcher)`:`match` 返回 `not inner.match(s)`
3. 实现工厂 `compile_matcher(pattern: str, *, is_command: bool) -> Matcher`:
   - 空串 → `raise ValueError("empty matcher pattern")`
   - 以 `=` 起头 → `ExactMatcher(rest)`
   - 以 `~` 起头 → `re.compile(rest)`,失败转 `ValueError`
   - 以 `!` 起头 → 递归 `compile_matcher(rest, is_command=is_command)` 包装为 `NotMatcher`
   - 其它 → `GlobMatcher(pattern, is_command)`
4. `match_command` / `match_path` 沿用 `permission` 包已有实现(若未抽出可在本模块内重用 `fnmatchcase`)
5. 写 docstring 解释每个 Matcher 类型的语义

**验证:** `python -c "from forgecode.permission.matcher import compile_matcher; print(compile_matcher('=foo', is_command=False))"` 输出 `=foo`

## T2: matcher 单元测试**文件:** `tests/permission/test_matcher.py`
**依赖:** T1
**步骤:**
1. 覆盖 4 种类型各自的命中/不命中用例
2. `=git status` 命中 `git status`、不命中 `git status -s`
3. `~^npm (install|test)$` 命中 `npm install`、不命中 `npm run dev`
4. `!=foo` 不命中 `foo`、命中 `bar`
5. `!~^rm` 命中 `ls -lh`、不命中 `rm -rf .`
6. `!git *` 命中 `npm install`、不命中 `git status`(嵌套 not + glob)
7. 编译失败:`~[invalid` 应抛 `ValueError`
8. 空串:`""` 应抛 `ValueError`
9. 用 `pytest.mark.parametrize` 表驱动,每条用例附 `id=...` 描述

**验证:** `pytest tests/permission/test_matcher.py -v` 通过

## T3: 升级 `permission.Rule` 与 `parse_rule`**文件:** `src/forgecode/permission/rule.py`
**依赖:** T1
**步骤:**
1. `Rule` dataclass 改:去 `pattern` 字段、加 `matcher: Matcher | None`(`None` 表示该工具全匹配)与 `raw: str`(原始描述)
2. `parse_rule` 签名改:`def parse_rule(s: str) -> tuple[Rule | None, str | None]`——返回错误描述让 `to_rule_set` 写日志
3. `parse_rule` 内部:剥出 `tool` 与 `pattern` 后调 `compile_matcher(pattern, is_command=(tool == "Bash"))`;空 pattern 仍按 `None` matcher 表示"全匹配"
4. 改造 `match_rule(r: Rule, target: str)`:`r.matcher is None` 返回 True(全匹配),否则 `r.matcher.match(target)`
5. `escape_glob` 保留不变,仅供 ch08 自动生成的精确规则使用
6. docstring 更新说明四种语法

**验证:** `pytest tests/permission/ -k rule` 不出现导入错误

## T4: 升级 `to_rule_set` 错误日志**文件:** `src/forgecode/permission/settings.py`
**依赖:** T3
**步骤:**
1. `to_rule_set` 改造:`parse_rule` 失败时 `print(f'rule {raw!r} parse failed: {err}', file=sys.stderr)`
2. 顶部 `import sys`
3. 加注释说明:失败的 rule 不进入 RuleSet,但其它 rule 不受影响

**验证:** `python -c "from forgecode.permission.settings import to_rule_set; print('ok')"` 不报错

## T5: 扩展 `test_rule` 与 `test_settings`**文件:** `tests/permission/test_rule.py`、`tests/permission/test_settings.py`
**依赖:** T3、T4
**步骤:**
1. `test_rule`:补充用例
   - `Bash(=git status)` 精确匹配
   - `Bash(~^npm.*)` 正则匹配
   - `Bash(!~^rm)` 反向正则
   - `Write(**/*.py)` glob 沿用(确认向后兼容)
2. `test_settings`:用 `capsys` fixture 捕获 stderr,构造一份含非法 rule 的 yaml,验证 `to_rule_set` 返回的 RuleSet 不含该 rule(检查 `rule_set.allow` / `deny` 长度即可),且 stderr 含 `parse failed`
3. 旧测试 `test_match_command` / `test_match_path` 改成调用 matcher 的形式或保留底层函数测试

**验证:** `pytest tests/permission/ -v` 全部通过

## T6: hook 包基础数据结构**文件:** `src/forgecode/hook/__init__.py`、`src/forgecode/hook/event.py`、`src/forgecode/hook/rule.py`
**依赖:** 无
**步骤:**
1. `__init__.py`:包标识,re-export `Engine` / `Event` / `load` / `DispatchResult`
2. `event.py`:
   - `class Event(str, enum.Enum)`,11 个成员对应 YAML 字面量(`SESSION_START = "SessionStart"` 等)
   - `BLOCKING_EVENTS: frozenset[Event] = frozenset({Event.PRE_TOOL_USE, Event.USER_PROMPT_SUBMIT})`
   - `def is_blocking(e: Event) -> bool: return e in BLOCKING_EVENTS`
   - `def parse_event(s: str) -> Event | None`:`Event(s)` 包 try/except `ValueError`
3. `rule.py`:
   - `Rule`、`Condition`、`AtomCondition`、`Action`、`ShellAction`、`PromptAction`、`HttpAction`、`SubagentAction`、`ActionType`、`CombineMode` 等 dataclass / 枚举
   - 类型别名 `Payload = dict[str, Any]`
   - 注意:`Rule.asyncio_mode` 字段替代 YAML 的 `async`(Python 关键字)

**验证:** `python -c "from forgecode.hook import Event; print(Event.PRE_TOOL_USE.value)"` 输出 `PreToolUse`

## T7: `hook.matcher` 字段路径求值**文件:** `src/forgecode/hook/matcher.py`
**依赖:** T6、T1
**步骤:**
1. `get_by_path(p: Payload, path: str) -> str`:按 `.` 分隔;递归取值;中途遇 `None` 或非 dict 返回空串
2. 字段值非字符串时:`bool` / `int` / `float` 用 `str(value)`(`True` → `"True"`,与 N6 输出保持一致);嵌套对象转 `json.dumps(value, sort_keys=True)`
3. `eval_condition(c: Condition | None, p: Payload) -> bool`:
   - `c is None` → True
   - 遍历 `c.atoms`,每条用 `get_by_path` + `AtomCondition.matcher.match`
   - `CombineMode.ALL_OF` 要求全部 True、`CombineMode.ANY_OF` 要求至少一个 True

**验证:** `pytest tests/hook/test_matcher.py`(若新增独立测试)通过;或在 `test_engine.py` 间接覆盖

## T8: `hook.Loader` YAML 解析**文件:** `src/forgecode/hook/loader.py`
**依赖:** T6、T7、T1
**步骤:**
1. 定义 `def load(project_root: str | Path) -> Engine`:
   - 计算两个候选路径:`<project_root>/.forgecode/hooks.yaml`、`Path.home() / ".forgecode" / "hooks.yaml"`
   - 文件不存在跳过;存在但 `yaml.safe_load` 失败时 `print(..., file=sys.stderr)` 后跳过整文件
   - 顶层结构必须含 `hooks: list`;不合法整文件跳过并打 stderr
   - 对每条 dict 调内部 `_compile_rule(source, idx, raw) -> Rule | None`
   - 累积成功的 rule、stderr 输出失败的 rule
   - 跨文件 name 冲突时跳过后者,stderr 打提示
2. `_compile_rule` 内做字段校验:
   - `name` 必填且非空
   - `event` 枚举(用 `parse_event`,失败 → `hook "<name>": unknown event "<value>", skipped`)
   - `action.type` 枚举与子字段必填(`shell.command`、`prompt.text`、`http.url`、`subagent.agent_name` + `subagent.prompt`)
   - `if` 顶层 `all_of` / `any_of` 互斥
   - 每个原子条件的 `match.type` ∈ `{exact, glob, regex, not}` 且 `value` / `inner` 字段完整
   - `async` + `is_blocking(event)` → 报错 `hook "<name>": async not allowed for blocking events, skipped` 跳过
   - `timeout` 字符串解析:支持 `30s` / `5m` / 浮点秒;用一个小函数 `_parse_duration(s) -> float`(用 `re` 匹配 `\d+(\.\d+)?([smh]?)`),失败 → 报错跳过;缺省 30.0
3. Matcher 编译用 `permission.compile_matcher`;hook 上下文中的 matcher 都作用于 payload 字段值,统一传 `is_command=False`(glob 走 `match_path`,段内 `*` 不跨 `/`)
   - **决策修正**:tool_input.command 这类 shell 字符串字段如果想做整串通配,用户应改用 regex 表达;文档中注明此约束

**验证:** `python -c "from forgecode.hook.loader import load; print(load('.'))"` 不抛异常

## T9: `hook.Loader` 测试**文件:** `tests/hook/test_loader.py`
**依赖:** T8
**步骤:**
1. `tmp_path` fixture 场景:写一份合法 `hooks.yaml`(含 2 条 hook),`load` 返回 Engine 含 2 条 rule
2. 字段缺失:name 空、event 不存在、action.type 无效 → 跳过该条但其它通过
3. `all_of` + `any_of` 同时存在 → 跳过该条
4. async + PreToolUse → 跳过该条且 capsys 捕获 stderr 含 `async not allowed for blocking events`
5. 跨文件同名冲突 → 项目级保留、用户级跳过(monkeypatch `Path.home` 指向 tmp_path)
6. matcher 编译失败(非法正则) → 跳过该条

**验证:** `pytest tests/hook/test_loader.py -v` 通过

## T10: `hook.Engine` 与 dispatch 主流程**文件:** `src/forgecode/hook/engine.py`
**依赖:** T6、T7
**步骤:**
1. `Engine` 类:`_rules`、`_sources`、`_lock: asyncio.Lock`、`_once_fired: set[str]`、`_executor`
2. `__init__(self, rules: list[Rule], sources: list[str])`
3. `async def dispatch(self, event: Event, payload: Payload) -> DispatchResult`:
   - 遍历 rules,跳过非本事件
   - 加锁查 `_once_fired`,命中跳过;`reset_for_new_session` 清空
   - `eval_condition`;不通过跳过
   - 命中后:
     - `rule.asyncio_mode` 为 True → `asyncio.create_task(self._executor.run(rule, payload, blocking=False))`,立即继续(不等结果、不进入 `injected_prompts` 与 `blocked` 判定);若 only_once,标记 fired
     - 同步:`await self._executor.run(rule, payload, blocking=is_blocking(event))`
   - 同步结果处理:
     - `outcome.err is not None` → stderr 日志 `[hook <name>] <event.value> failed: <reason>`,继续下一个 rule(不拦截)
     - `outcome.prompt` 非空 → 加入 `injected_prompts`
     - `outcome.blocked and is_blocking(event)` → 设置 `result.blocked` + `reason` + `blocking_hook_name`,break
   - 命中且执行无 fatal err 的 rule,若 `only_once` → 加入 `_once_fired`
4. `async def reset_for_new_session(self)`:加锁清空 `_once_fired`
5. property `sources` 与 `rules` 返回副本

**验证:** `python -c "import asyncio; from forgecode.hook.engine import Engine; asyncio.run(Engine([], []).dispatch('Stop', {}))"` 通过(传字面量会失败,改用 Event.STOP)

## T11: `hook.Executor` 四类动作执行**文件:** `src/forgecode/hook/executor.py`
**依赖:** T6
**步骤:**
1. `Executor` 类(可空字段或仅 `_http_client: httpx.AsyncClient`)
2. `__init__(self)`:`self._http_client = httpx.AsyncClient()`(单实例复用连接池)
3. `async def run(self, rule, payload, *, blocking) -> ExecutionResult` 分发到下面四个内部方法
4. `async def _run_shell(self, sa, payload, blocking, timeout)`:
   - `proc = await asyncio.create_subprocess_shell(sa.command, stdin=PIPE, stdout=PIPE, stderr=PIPE)`
   - `payload_json = json.dumps(payload, sort_keys=True).encode()`
   - `stdout, stderr = await asyncio.wait_for(proc.communicate(payload_json), timeout=timeout)`
   - 超时 `asyncio.TimeoutError`:`proc.kill(); await proc.wait()`,返回 `err=TimeoutError(...)`
   - `blocking and proc.returncode == 2` → `blocked=True, reason=(stderr or stdout).decode().rstrip("\n")`
   - `proc.returncode == 0` → 不拦截不报错
   - 其它非 0 returncode → `err=RuntimeError(f"exit {code}: {stderr.decode()}")`
5. `def _run_prompt(self, pa) -> ExecutionResult`:返回 `ExecutionResult(prompt=pa.text)`
6. `async def _run_http(self, ha, payload, blocking, timeout)`:
   - 默认 `method = ha.method or "POST"`
   - body:`ha.body is None` 时 `json.dumps(payload, sort_keys=True)`;否则 `ha.body.format_map(payload)`,渲染异常按 `err` 处理
   - `resp = await self._http_client.request(method, ha.url, content=body, headers=ha.headers, timeout=timeout)`
   - status 2xx 且 `json.loads(resp.text)` 含 `{"decision":"block","reason":"..."}` → `blocked=True`
   - 网络错(`httpx.HTTPError`) / 超时(`httpx.TimeoutException`) / JSON 解析失败 → `err`
7. `def _run_subagent(self, sa) -> ExecutionResult`:仅 `print(f"[hook subagent] not yet implemented, skipped: {sa.agent_name}", file=sys.stderr)`,返回空 `ExecutionResult()`
8. payload JSON 序列化用共享辅助 `_marshal_sorted(p) -> bytes`,保证 key 字典序

**验证:** `python -c "from forgecode.hook.executor import Executor; print(Executor())"` 通过

## T12: executor 单元测试**文件:** `tests/hook/test_executor.py`
**依赖:** T11
**步骤:**
1. shell exit 2 with stderr → blocked=True + reason 含 stderr
2. shell exit 0 → 放行不报错
3. shell exit 1 → err 非 None 不拦截
4. shell stdin JSON 解析:脚本读 stdin 后 echo 出来,验证 key 字典序(`sh -c "cat"` + 比对输出)
5. shell timeout:`sleep 2 && echo done` + timeout 0.1s → err 类型为 `TimeoutError`
6. prompt → result.prompt 字段非空
7. http with `pytest-httpserver` 或自起 `aiohttp` 桩返回 `{"decision":"block","reason":"x"}` → blocked=True
8. http with 5xx → err 非 None
9. http 模板 body 含 `{event}` → server 收到正确字段
10. subagent → capsys 捕获 stderr 含占位文本

**验证:** `pytest tests/hook/test_executor.py -v` 通过

## T13: `hook.Engine` 测试**文件:** `tests/hook/test_engine.py`
**依赖:** T10、T11
**步骤:**
1. 多 rule 同事件按声明序执行
2. 拦截类事件下首个 blocked 的 rule 中断后续
3. 非拦截类事件下 blocked 字段不传递(fake exit code 2 但 `is_blocking(event)=False` 也不 set `blocked`)
4. prompt rule 的 prompt 累加到 `injected_prompts`
5. only_once 在首次执行后被加入 `_once_fired`,第二次 dispatch 跳过
6. `reset_for_new_session` 后 only_once 重置
7. async rule 不进入 blocked 判定(用 `asyncio.Event` 验证 task 已起)

**验证:** `pytest tests/hook/test_engine.py -v` 通过

## T14: agent `SessionRuntime` 扩展**文件:** `src/forgecode/agent/runtime.py`、`tests/agent/test_runtime.py`
**依赖:** T6
**步骤:**
1. `SessionRuntime` 加字段:`pending_reminders: list[str]`、`hook_engine: Engine | None`
2. `__init__` 初始化空 list 与 None
3. `async def reset_for_new_session(self)`:清空 `pending_reminders`、若 `hook_engine is not None` 调 `await hook_engine.reset_for_new_session()`
4. 新增 `def append_reminders(self, prompts: list[str]) -> None`:加锁(`threading.Lock` 或 `asyncio.Lock`)追加
5. 新增 `def take_reminders(self) -> list[str]`:加锁取出并清空
6. 测试覆盖:`append_reminders` + `take_reminders` 单线程行为;`reset_for_new_session` 清空

**验证:** `pytest tests/agent/test_runtime.py -v` 通过

## T15: `Agent.__init__` 加 hook_engine 与 emit 框架**文件:** `src/forgecode/agent/runtime.py`、`src/forgecode/agent/agent.py`
**依赖:** T14
**步骤:**
1. `Agent.__init__` 新增 `hook_engine: Engine | None = None` 参数,赋给 `self._hook_engine`
2. 私有方法 `async def _dispatch_hook(self, event: Event, payload: Payload) -> DispatchResult`:
   - `self._hook_engine is None` → 返回空 `DispatchResult`
   - `await self._hook_engine.dispatch(event, payload)`
   - 把 `injected_prompts` 调 `self._runtime.append_reminders`
   - 返回结果(保留 `blocked` + `reason` 供 PreToolUse 用)
3. 私有方法 `def _build_reminder(self, mode, iter) -> str`:
   - 原 `plan_reminder` + `"\n\n".join(self._runtime.take_reminders())`

**验证:** `python -c "from forgecode.agent.agent import Agent; print(Agent)"` 通过

## T16: agent 各事件 emit 接入**文件:** `src/forgecode/agent/agent.py`
**依赖:** T15
**步骤:**
1. 每轮 iter 顶部、`_manage_context_auto` 之前 `await self._dispatch_hook(Event.PRE_COMPACT, {"trigger":"auto"})`;`manage_context` 返回后 emit `Event.POST_COMPACT` 带 before/after tokens
2. `_emergency_compact_and_decide`:同样 PreCompact/PostCompact,trigger="emergency"
3. `_stream_once` 调 `provider.stream` 之前 emit `Event.PRE_USER_MESSAGE`,payload 含 conversation 末尾 user 消息
4. 把 reminder 串改造:取 `self._build_reminder(mode, iter)` 替代原裸的 `plan_reminder(full)`
5. `_execute_batched` 改造:
   - 单工具循环开始处 emit PreToolUse,payload 含 `tool_name`、`tool_input`;`blocked=True` 时构造 `_hook_blocked_result`、emit PhaseStart/PhaseEnd(is_error=True),continue
   - tool 拿到 result 后、emit PhaseEnd 之前 emit PostToolUse,payload 含 `tool_name`、`tool_input`、`tool_result`、`is_error`
6. emit Done 之前调 `Event.STOP`,payload `{"iter": iter}`
7. emit Approval 之前调 `Event.NOTIFICATION`,payload `{"kind":"approval", "detail": tool_name}`
8. emit Err 之前调 `Event.NOTIFICATION`,payload `{"kind":"stream_error", "detail": str(err)}`
9. 拦截结果整合:定义 `_hook_blocked_result(call_id, hook_name, reason) -> ToolResult`:`content=f"[hook {hook_name}] {reason}"`、`is_error=True`

**验证:** `python -c "from forgecode.agent.agent import Agent; print('ok')"` 通过

## T17: `test_agent` 拦截路径与 emit 覆盖**文件:** `tests/agent/test_agent.py`、`tests/agent/test_runtime.py`
**依赖:** T16
**步骤:**
1. 构造一个 fake provider + 真实 `hook.Engine` 注入合成 rules
2. 测试:PreToolUse 拦截时工具结果是 `_hook_blocked_result` 形式、PhaseStart/PhaseEnd 仍 emit
3. 测试:PreUserMessage 注入的 prompt 在下一次 `_stream_once` 的 reminder 串中可见
4. 测试:Stop 事件在 Done 前一刻被 emit
5. 用 `pytest-asyncio` 跑 async 测试函数

**验证:** `pytest tests/agent/ -k hook -v` 通过

## T18: tui `ForgeCodeApp` 持有 `hook_engine`**文件:** `src/forgecode/tui/app.py`
**依赖:** T15
**步骤:**
1. `AppParams` dataclass 加 `hook_engine: Engine | None`
2. `ForgeCodeApp` 类加属性 `self.hook_engine: Engine | None`
3. `__init__` 内:
   - 把 `params.hook_engine` 赋给 `self.hook_engine` 与 `self.runtime.hook_engine`
   - 构造 agent 时传 `hook_engine=params.hook_engine`
4. `on_mount()` 末尾 `await self._dispatch_session_start()`

**验证:** `python -c "from forgecode.tui.app import ForgeCodeApp; print(ForgeCodeApp)"` 通过

## T19: tui `UserPromptSubmit` 拦截集成**文件:** `src/forgecode/tui/stream.py`
**依赖:** T18
**步骤:**
1. `_submit()` 重写:
   - 现有的 strip 与 slash 分发保留
   - 非 slash 路径:构造 payload `self._base_payload() | {"prompt": text}`
   - `result = await self.hook_engine.dispatch(Event.USER_PROMPT_SUBMIT, payload)`
   - `result.blocked` → `self._show_error_block(f"[hook {result.blocking_hook_name}] {result.reason}")`,不消费 `Input`
   - 否则:`self.runtime.append_reminders(result.injected_prompts)`;`self.conv.add_user(text)`;`await self._begin_turn()`
2. 提供辅助方法 `def _base_payload(self) -> Payload`:返回 `{"event": event.value, "session_id": ..., "cwd": str(self.cwd), "mode": self.mode.name.lower()}` 通用字段(event 由 caller 设置)

**验证:** `python -c "from forgecode.tui.stream import ..."` 通过

## T20: tui SessionStart / End / Resume**文件:** `src/forgecode/tui/app.py`、`src/forgecode/tui/commands.py`、`src/forgecode/tui/stream.py`
**依赖:** T18、T19
**步骤:**
1. 新增 `async def _dispatch_session_start(self)`:构造 payload + 调 `Engine.dispatch` + `injected_prompts` 写入 runtime
2. 新增 `async def _dispatch_session_end(self)`:仅同步调 dispatch
3. 新增 `async def _dispatch_session_resume(self)`:同 SessionStart 流程,event 改为 `Event.SESSION_RESUME`
4. `on_mount()` 末尾 await `_dispatch_session_start`
5. `/clear` handler 内:先 `await self._dispatch_session_end()`,再 `await self.runtime.reset_for_new_session()`,最后 `await self._dispatch_session_start()`
6. `/resume` handler 选中会话恢复完毕后:先 `await self._dispatch_session_end()`(旧),切到新会话后 `await self._dispatch_session_resume()`
7. `handle_exit` 内:`await self._dispatch_session_end()` 后再退出
8. App 退出前由 `cli.main` 兜底:`await hook_engine.dispatch(Event.SESSION_END, base_payload)`(确保 Ctrl+C 退出也 emit)
   - 实际:`cli.main` 在 `app.run_async()` 返回后调一次 `dispatch`;tui 内的 `/clear`、`/resume` 自己控制

**验证:** `python -c "from forgecode.tui.app import ForgeCodeApp; print('ok')"` 通过

## T21: `/hooks` 命令**文件:** `src/forgecode/tui/hooks.py`、`src/forgecode/command/builtins.py`、`src/forgecode/command/ui.py`
**依赖:** T6、T10、T18
**步骤:**
1. UI Protocol 加方法 `hook_sources() -> list[str]`、`hook_rules() -> list[Rule]`
2. `ForgeCodeApp` 实现这两个方法(读 `self.hook_engine` 属性,None 时返回空)
3. 新增 `src/forgecode/tui/hooks.py`,实现 `async def handle_hooks(ctx, ui)`:
   - 取 rules 与 sources
   - 空时 `await ui.write_line("No hooks loaded.")`
   - 否则按 event 分组(保留 yaml 声明顺序)、每条一行 `  <name>  <event>  <action.type>  [once] [async]`
   - 末尾 `Loaded from: file1, file2`
4. `builtins.py` 注册新命令 `/hooks`,KindLocal,描述"列出已加载的 hook 列表"

**验证:** `pytest -k hooks_command -v` 通过(或手动启动后输入 `/hooks`)

## T22: `cli.main` wiring**文件:** `src/forgecode/cli.py`
**依赖:** T8、T18
**步骤:**
1. 在 `permission.new_engine` 之后调 `hook_engine = hook.load(root)`
2. `tui.create_app` 传 `hook_engine=hook_engine`
3. `await app.run_async()` 之后调:
   ```python
   if hook_engine is not None:
       await hook_engine.dispatch(Event.SESSION_END, base_payload)
   ```
   兜底 SessionEnd
4. 顶部 `from forgecode import hook`、`from forgecode.hook import Event`

**验证:** `python -m forgecode --help` 启动不报错

## T23: 整体编译与测试**文件:** —
**依赖:** T1-T22 全部
**步骤:**
1. `ruff check src tests` 通过
2. `pytest` 通过——hooks 相关测试 + 既有测试都得过

**验证:** 上述两条命令本地通过

## T24: 修复回归**文件:** 根据测试输出决定
**依赖:** T23
**步骤:**
1. 修复 ch08 / ch11 等老测试因 Matcher 改造而失败的用例
2. 修复 ch10 / ch11 测试因 `/hooks` 命令加入而影响排序或数量的用例
3. 重新跑全套测试

**验证:** `pytest` 全过

## T25: tmux 端到端实跑(验收 AC17 与 checklist 端到端场景)**文件:** `.forgecode/hooks.yaml` 临时测试配置
**依赖:** T23、T24
**步骤:**
1. 写测试 `hooks.yaml`:包含 AC4-AC15 各典型场景的 hook
2. tmux 新建 session 启动 `python -m forgecode` 或安装后的 `forgecode`
3. 依次触发:`write_file` 工具调用、含 delete 关键字的用户输入、git 命令、Stop 事件
4. 观察 stderr 日志、tool_result 内容、reminder 注入是否符合预期
5. 全程不卡顿、无未捕获异常栈

**验证:** 见 checklist.md

## 执行顺序

```
T1 → T2 → T3 → T4 → T5            # permission Matcher 扩展
T6 → T7 → T8 → T9                 # hook 基础结构 + Loader
T10 → T13                         # Engine
T11 → T12                         # Executor(与 Engine 并行)
T14 → T15 → T16 → T17             # agent 接入
T18 → T19 → T20                   # tui 接入
T21                               # /hooks 命令
T22                               # cli wiring
T23 → T24                         # 整体编译测试
T25                               # tmux 实跑验收
```

并行机会:
- T11/T12 与 T10/T13 互不依赖,可并行
- T11 与 T8 在 T6 完成后可并行
- T17 必须在 T16 之后
- T19 之前 T18 必须先完成