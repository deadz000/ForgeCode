# Hook 生命周期挂钩系统 Plan## 技术栈

- 语言:Python 3.12+
- TUI:Textual(async-first)+ Rich
- 配置:YAML 解析(`pyyaml`,import 名 `yaml`,用 `yaml.safe_load`)
- HTTP 客户端:`httpx`(原生支持 async,与 Textual 事件循环天然融合)
- 异步进程:`asyncio.create_subprocess_shell` + `asyncio.wait_for` 超时
- 模板:Python 标准库 `str.format_map`(不开放函数调用)
- 测试:`pytest` + `pytest-asyncio`(async 测试)、临时目录用 `tmp_path`、HTTP 桩用 `pytest-httpserver` 或自起 `aiohttp` 桩

## 架构概览

本章拆为两个层次实现:

1. **权限匹配器升级层(`forgecode.permission` 包内改造)**——把 Pattern 形态从字符串升级到结构化 `Matcher` Protocol;新增 exact/regex/not 三种实现,glob 保留作为缺省类型。改造对外仅暴露语法升级和 stderr 错误回退,运行时 Allow/Deny 语义不变。

2. **Hook 主体层(新建 `forgecode.hook` 包)**——加载 YAML 规则、提供事件分派引擎、四类动作执行器;通过 11 个事件 emit 点接入 agent / tui。

模块构成:

- `permission.Matcher`(新):匹配 Protocol + 四种实现的工厂
- `hook.Loader`(新):YAML 解析 / 字段校验 / matcher 编译 / 双层文件合并
- `hook.Engine`(新):事件分派、only_once 集合、动作执行器协调
- `hook.Executor`(新):四类动作的执行入口(shell / prompt / http / subagent stub)
- `hook.matcher`(薄包装):复用 `permission.Matcher`,做字段路径取值与匹配组合
- `agent`/`tui` 改动:在生命周期 11 个时刻调 `Engine.dispatch`
- `command`:新增 `/hooks` 内置命令

## 数据流**启动期:**

```
cli.main
  ├─ permission.new_engine(root)         # 用升级后的 parse_rule(stderr 报错)
  ├─ hook.load(root)                     # 扫描两层 YAML、构造 Engine
  └─ tui.create_app(..., hook_engine=engine)
        ├─ agent.create(..., hook_engine=engine)
        └─ app.hook_engine = engine
```

**SessionStart emit 时机:**

```
cli.main 完成 wiring → tui.create_app 返回 ForgeCodeApp → app.run_async()
                                                         │
                                                         └─ Textual on_mount() 末尾
                                                            首条 user 输入到达前
                                                            派发 SessionStart 事件
```

实际接入:`ForgeCodeApp.on_mount()` 末尾 `await self._dispatch_session_start()`,该协程同步调 `Engine.dispatch`、收集 `injected_prompts` 注入到 `runtime.pending_reminders`、然后返回。

**UserPromptSubmit 路径:**

```python
async def _submit(self, text: str) -> None:
    text = text.strip()
    if text.startswith("/"):
        await self._dispatch_slash(text)
        return
    result = await self.hook_engine.dispatch(
        Event.USER_PROMPT_SUBMIT,
        self._base_payload() | {"prompt": text},
    )
    if result.blocked:
        # 输入框下方显示 [hook <name>] reason,不消费输入
        self._show_error_block(f"[hook {result.blocking_hook_name}] {result.reason}")
        return
    self.runtime.append_reminders(result.injected_prompts)
    self.conv.add_user(text)
    await self._begin_turn()
```

**PreToolUse 拦截路径:**

```python
async def execute_batched(calls, mode, queue):
    for call in calls:
        result = await self.hook_engine.dispatch(
            Event.PRE_TOOL_USE,
            {"tool_name": call.name, "tool_input": call.input, ...},
        )
        if result.blocked:
            await queue.put(PhaseStart(call_id=call.id))   # 用户仍能看到工具被尝试
            results[call.id] = hook_blocked_result(call.id, result.blocking_hook_name, result.reason)
            await queue.put(PhaseEnd(call_id=call.id, is_error=True))
            continue
        self.runtime.append_reminders(result.injected_prompts)
        # ... 原有的权限 check + 执行流程
        # PostToolUse dispatch 后再 append 一次 reminder
```

**Reminder 注入路径:**

```python
# Agent.run() 第 iter 轮 stream_once 之前:
reminder = plan_reminder
reminder += join_pending_reminders(self.runtime)  # 取出并清空 runtime.pending_reminders
await self._stream_once(..., reminder=reminder, ...)
```

## 核心数据结构与接口### `permission.Matcher`

```python
# forgecode/permission/matcher.py
from __future__ import annotations

import re
from dataclasses import dataclass
from fnmatch import fnmatchcase
from typing import Protocol

class Matcher(Protocol):
    """规则匹配的统一接口;四种实现:ExactMatcher / GlobMatcher / RegexMatcher / NotMatcher。"""

    def match(self, s: str) -> bool: ...
    def __str__(self) -> str: ...   # 调试 / /hooks 输出用

@dataclass(frozen=True)
class ExactMatcher:
    value: str

    def match(self, s: str) -> bool:
        return s == self.value

    def __str__(self) -> str:
        return f"={self.value}"

@dataclass(frozen=True)
class GlobMatcher:
    pattern: str
    is_command: bool          # True 走 match_command(整串通配),False 走 match_path

    def match(self, s: str) -> bool:
        if self.is_command:
            return match_command(self.pattern, s)
        return match_path(self.pattern, s)

    def __str__(self) -> str:
        return self.pattern

@dataclass(frozen=True)
class RegexMatcher:
    src: str
    compiled: re.Pattern[str]

    def match(self, s: str) -> bool:
        return self.compiled.search(s) is not None

    def __str__(self) -> str:
        return f"~{self.src}"

@dataclass(frozen=True)
class NotMatcher:
    inner: Matcher

    def match(self, s: str) -> bool:
        return not self.inner.match(s)

    def __str__(self) -> str:
        return f"!{self.inner}"

def compile_matcher(pattern: str, *, is_command: bool) -> Matcher:
    """
    解析单条匹配描述串,返回 Matcher。失败抛 ValueError。
    描述串规则:
      "=value"  -> ExactMatcher
      "~regex"  -> RegexMatcher
      "!inner"  -> NotMatcher(compile_matcher(inner))
      "value"   -> GlobMatcher(沿用现有 wildcard / match_path 语义)
    Bash 工具沿用整串通配(is_command=True),其它沿用 match_path。
    """
    if not pattern:
        raise ValueError("empty matcher pattern")
    head, rest = pattern[0], pattern[1:]
    if head == "=":
        return ExactMatcher(rest)
    if head == "~":
        try:
            return RegexMatcher(rest, re.compile(rest))
        except re.error as e:
            raise ValueError(f"invalid regex: {e}") from e
    if head == "!":
        return NotMatcher(compile_matcher(rest, is_command=is_command))
    return GlobMatcher(pattern, is_command)
```

### `permission.Rule`(改造)

```python
@dataclass
class Rule:
    tool: str                    # 不变
    matcher: Matcher | None      # 替换原 pattern 字符串;None 表示"该工具全匹配"
    allow: bool
    raw: str                     # 原始模式串,仅供错误日志与调试
```

`parse_rule` 升级:识别前缀,调用 `compile_matcher` 构造 matcher。失败时返回 `(None, error_str)`;调用方 `to_rule_set` 把错误打到 stderr 后跳过。

### `hook.Rule`

```python
# forgecode/hook/rule.py
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any

class Event(str, enum.Enum):
    SESSION_START = "SessionStart"
    SESSION_END = "SessionEnd"
    SESSION_RESUME = "SessionResume"
    USER_PROMPT_SUBMIT = "UserPromptSubmit"
    STOP = "Stop"
    PRE_USER_MESSAGE = "PreUserMessage"
    PRE_TOOL_USE = "PreToolUse"
    POST_TOOL_USE = "PostToolUse"
    PRE_COMPACT = "PreCompact"
    POST_COMPACT = "PostCompact"
    NOTIFICATION = "Notification"

BLOCKING_EVENTS: frozenset[Event] = frozenset({Event.PRE_TOOL_USE, Event.USER_PROMPT_SUBMIT})

def is_blocking(e: Event) -> bool:
    return e in BLOCKING_EVENTS

class CombineMode(str, enum.Enum):
    ALL_OF = "all_of"
    ANY_OF = "any_of"

class ActionType(str, enum.Enum):
    SHELL = "shell"
    PROMPT = "prompt"
    HTTP = "http"
    SUBAGENT = "subagent"

@dataclass
class AtomCondition:
    field: str                   # 形如 "tool_input.path"
    matcher: "Matcher"           # 复用 permission.Matcher

@dataclass
class Condition:
    mode: CombineMode            # CombineMode.ALL_OF 或 ANY_OF;二选一不混用
    atoms: list[AtomCondition]

@dataclass
class ShellAction:
    command: str

@dataclass
class PromptAction:
    text: str

@dataclass
class HttpAction:
    url: str
    method: str = "POST"
    headers: dict[str, str] = field(default_factory=dict)
    body: str | None = None      # 模板字符串,None 表示用 payload JSON

@dataclass
class SubagentAction:
    agent_name: str
    prompt: str

@dataclass
class Action:
    type: ActionType
    shell: ShellAction | None = None
    prompt: PromptAction | None = None
    http: HttpAction | None = None
    subagent: SubagentAction | None = None

@dataclass
class Rule:
    name: str
    event: Event
    action: Action
    condition: Condition | None = None      # None 表示无条件
    only_once: bool = False
    asyncio_mode: bool = False               # 对应 YAML 的 `async`(避免与关键字冲突)
    timeout_s: float = 30.0
    source: str = ""                         # 来源文件路径,供 /hooks 显示

# Payload 是事件分派时携带的上下文数据;条件求值与动作输入都用它。
# 序列化为 JSON 时保证 key 字典序(N6)用 json.dumps(payload, sort_keys=True)。
Payload = dict[str, Any]
```

### `hook.Engine`

```python
# forgecode/hook/engine.py
from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass, field

@dataclass
class DispatchResult:
    blocked: bool = False
    reason: str = ""
    blocking_hook_name: str = ""
    injected_prompts: list[str] = field(default_factory=list)

class Engine:
    def __init__(self, rules: list[Rule], sources: list[str]) -> None:
        self._rules = rules                       # 按加载顺序
        self._sources = sources                   # 加载来源文件列表,供 /hooks 显示
        self._once_fired: set[str] = set()        # only_once 已触发的 hook name
        self._lock = asyncio.Lock()
        self._executor = Executor()

    async def dispatch(self, event: Event, payload: Payload) -> DispatchResult:
        result = DispatchResult()
        for rule in self._rules:
            if rule.event is not event:
                continue
            async with self._lock:
                if rule.only_once and rule.name in self._once_fired:
                    continue
            if not eval_condition(rule.condition, payload):
                continue

            if rule.asyncio_mode:
                # async hook:起 task 后立即继续,不参与 Blocked / InjectedPrompts
                asyncio.create_task(self._executor.run(rule, payload, blocking=False))
                if rule.only_once:
                    async with self._lock:
                        self._once_fired.add(rule.name)
                continue

            outcome = await self._executor.run(rule, payload, blocking=is_blocking(event))
            if outcome.err is not None:
                print(
                    f"[hook {rule.name}] {event.value} failed: {outcome.err}",
                    file=sys.stderr,
                )
                continue
            if outcome.prompt:
                result.injected_prompts.append(outcome.prompt)
            if rule.only_once:
                async with self._lock:
                    self._once_fired.add(rule.name)
            if outcome.blocked and is_blocking(event):
                result.blocked = True
                result.reason = outcome.reason
                result.blocking_hook_name = rule.name
                break
        return result

    async def reset_for_new_session(self) -> None:
        async with self._lock:
            self._once_fired.clear()

    @property
    def sources(self) -> list[str]:
        return list(self._sources)

    @property
    def rules(self) -> list[Rule]:
        return list(self._rules)
```

Dispatch 内部流程:
1. 过滤匹配 event 的 rule
2. 跳过 `_once_fired` 中已触发的 only_once rule
3. 串行求值 if 条件
4. 命中条件后按 action.type 分发到 Executor
5. async rule 起 asyncio task、立即往下走
6. 同步 rule 等结果,拦截类事件下若 outcome 表达 block,累加到 DispatchResult,跳过后续同事件 rule
7. prompt 类 rule 把 text 累加到 `injected_prompts`

### `hook.Executor`

```python
# forgecode/hook/executor.py
from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import dataclass

import httpx

@dataclass
class ExecutionResult:
    blocked: bool = False
    reason: str = ""
    prompt: str = ""              # 仅 prompt 动作非空
    err: Exception | None = None  # hook 自身失败(不拦截)

class Executor:
    def __init__(self) -> None:
        # 默认 timeout=30s,可被 rule.timeout_s 覆盖
        self._http_client = httpx.AsyncClient(timeout=30.0)

    async def run(self, rule: Rule, payload: Payload, *, blocking: bool) -> ExecutionResult:
        action = rule.action
        if action.type is ActionType.SHELL:
            return await self._run_shell(action.shell, payload, blocking, rule.timeout_s)
        if action.type is ActionType.PROMPT:
            return ExecutionResult(prompt=action.prompt.text)
        if action.type is ActionType.HTTP:
            return await self._run_http(action.http, payload, blocking, rule.timeout_s)
        if action.type is ActionType.SUBAGENT:
            print(
                f"[hook subagent] not yet implemented, skipped: {action.subagent.agent_name}",
                file=sys.stderr,
            )
            return ExecutionResult()
        return ExecutionResult(err=RuntimeError(f"unknown action type: {action.type}"))
```

`_run_shell` 关键点:
- 调 `asyncio.create_subprocess_shell(sa.command, stdin=PIPE, stdout=PIPE, stderr=PIPE)`
- `payload_json = json.dumps(payload, sort_keys=True).encode()` 写到 stdin
- `await asyncio.wait_for(proc.communicate(input=...), timeout=timeout_s)`,超时 → 杀子进程并按失败处理
- `blocking and proc.returncode == 2` → `blocked=True`、`reason=(stderr or stdout).decode().rstrip("\n")`
- `proc.returncode == 0` → 不拦截不报错
- 其它非 0 returncode → `err=RuntimeError(f"exit {code}: {stderr.decode()}")`

`_run_http` 关键点:
- 默认 method=POST
- body:缺省时 `json.dumps(payload, sort_keys=True)`;否则 `ha.body.format_map(payload)`
- 用 `httpx.AsyncClient.request(method, url, content=body, headers=headers, timeout=timeout_s)`
- status 2xx 且 body 含 `{"decision":"block","reason":"..."}` → `blocked=True`
- 网络错/超时/JSON 解析失败 → `err`

## 模块设计### 模块 A:`permission.Matcher`**职责:** 提供四种匹配类型的统一接口;`compile_matcher` 解析前缀。
**对外接口:** `Matcher` Protocol、`compile_matcher(pattern: str, *, is_command: bool) -> Matcher`。
**依赖:** Python 标准库 `re`、`fnmatch`。
**改动文件:** `src/forgecode/permission/rule.py`(扩展 `parse_rule` / `match_rule`)、新增 `src/forgecode/permission/matcher.py`。

### 模块 B:permission 错误日志**职责:** `parse_rule` 失败时 stderr 打印失败规则与原因,原本静默跳过改为有声跳过。
**对外接口:** `to_rule_set` 内部行为变化,外部 API 不变。
**依赖:** 模块 A。

### 模块 C:`hook.Loader`**职责:** 扫描两层 YAML 文件、解析顶层 `hooks:` 数组、字段校验、Matcher 编译、合并去重。
**对外接口:** `load(project_root: str | Path) -> Engine`——返回引擎(内部已含来源文件列表);所有错误走 stderr 不抛异常。
**依赖:** 模块 A、`pyyaml`、`hook.Engine`。
**校验项:** name 必填 + 跨文件冲突、event 枚举、if 顶层 all_of/any_of 互斥、action.type 枚举与子字段、async + 拦截事件冲突、Matcher 编译失败、timeout 字符串格式合法。

### 模块 D:`hook.Engine`**职责:** Dispatch 流程编排、only_once 集合管理、`reset_for_new_session`。
**对外接口:** 见上一节 Engine 类。
**依赖:** 模块 E。

### 模块 E:`hook.Executor`**职责:** 四类动作的执行——shell(`asyncio.create_subprocess_shell` + stdin JSON + returncode 2 拦截)、prompt(直接返回 `injected_prompt`)、http(POST JSON + decision=block 解析)、subagent(stub 占位日志)。
**对外接口:** `run(rule, payload, *, blocking) -> ExecutionResult`。
**依赖:** `asyncio`、`httpx`、`json`、`str.format_map`。

### 模块 F:`hook.matcher` 包装**职责:** 把 `permission.Matcher` 应用到 payload 的字段路径上。
**对外接口:** `eval_condition(cond: Condition | None, payload: Payload) -> bool`、`get_by_path(payload: Payload, path: str) -> str`。
**依赖:** 模块 A。

### 模块 G:agent 接入**职责:** 在 `Agent.run` 等关键路径调 `Engine.dispatch`;处理 PreToolUse 拦截、注入 reminder。
**对外接口:** `Agent.__init__(..., hook_engine: Engine | None = None)`;`Agent._dispatch_hook(event, payload) -> DispatchResult` 私有方法。
**依赖:** 模块 D。
**改动文件:** `src/forgecode/agent/agent.py`、`src/forgecode/agent/runtime.py`(`SessionRuntime` 加 `pending_reminders: list[str]`、`reset_for_new_session` 清空)。

### 模块 H:tui 接入**职责:** SessionStart / SessionEnd / SessionResume / UserPromptSubmit / Notification 五个事件在 TUI 侧 emit;UserPromptSubmit 拦截集成到 `_submit()` 流程。
**对外接口:** `ForgeCodeApp` 私有方法 `_dispatch_session_start` / `_dispatch_session_end` 等。
**依赖:** 模块 D。
**改动文件:** `src/forgecode/tui/app.py`、`src/forgecode/tui/stream.py`、`src/forgecode/tui/commands.py`(/clear、/resume 触发 SessionEnd + SessionStart/Resume)。

### 模块 I:`/hooks` 命令**职责:** 输出已加载 hook 列表 + 加载来源文件。
**对外接口:** 注册到 `command.register_builtins`。
**依赖:** `ForgeCodeApp` 实现 UI 接口暴露 `hook_sources()` / `hook_rules()` 查询方法。

### 模块 J:cli wiring**职责:** 在 `cli.main` 中调 `hook.load(project_root)`,把 Engine 注入 agent 与 App。
**改动文件:** `src/forgecode/cli.py`、`src/forgecode/tui/app.py`(`AppParams` 加 `hook_engine` 字段)。

## 文件组织

```
forgecode/
├── pyproject.toml
├── src/forgecode/
│   ├── permission/
│   │   ├── __init__.py
│   │   ├── matcher.py            # 新增:Matcher Protocol 与四种实现
│   │   ├── rule.py               # 改造:parse_rule 识别前缀、Rule 持有 matcher
│   │   ├── settings.py           # 改造:to_rule_set 报 stderr
│   │   └── ...
│   ├── hook/                     # 全新包
│   │   ├── __init__.py           # 暴露 Engine / Event / load / DispatchResult
│   │   ├── event.py              # 11 个 Event 枚举 + 拦截类列表 + is_blocking
│   │   ├── rule.py               # Rule / Condition / Action / Payload 数据结构
│   │   ├── matcher.py            # eval_condition / get_by_path(复用 permission.Matcher)
│   │   ├── loader.py             # YAML 解析、字段校验、双层合并
│   │   ├── engine.py             # Engine + dispatch 主流程 + only_once 集合
│   │   └── executor.py           # 四类 action 执行器
│   ├── agent/
│   │   ├── agent.py              # 增 _dispatch_hook 与 PreToolUse/PostToolUse/Stop/PreCompact 等 emit
│   │   ├── runtime.py            # SessionRuntime 加 pending_reminders、hook_engine 字段
│   │   └── ...
│   ├── command/
│   │   └── builtins.py           # 加 /hooks 命令
│   ├── tui/
│   │   ├── app.py                # AppParams 加 hook_engine、App 持有
│   │   ├── stream.py             # _submit() 内拦截 + SessionStart emit
│   │   ├── commands.py           # /clear / /resume 触发 SessionEnd + SessionStart/Resume
│   │   └── hooks.py              # 新增:/hooks handler、App 的 hook 查询方法
│   └── cli.py                    # 加 hook.load(root) 与 wiring
├── tests/
│   ├── permission/
│   │   ├── test_matcher.py       # 四种 type 覆盖
│   │   └── test_rule.py          # parse_rule 新语法
│   ├── hook/
│   │   ├── test_loader.py        # 校验项覆盖
│   │   ├── test_engine.py        # 各事件 dispatch + 拦截 + reminder + once 覆盖
│   │   └── test_executor.py      # shell exit2 / http block / prompt / subagent stub 覆盖
│   ├── agent/
│   │   └── test_runtime.py       # pending_reminders 覆盖
│   └── tui/
│       └── test_stream.py        # _submit 拦截覆盖
└── docs/python/ch12/
    ├── spec.md
    ├── plan.md
    ├── task.md
    └── checklist.md
```

## 技术决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 匹配前缀语法 | `=` 精确、`!` 反向、`~` 正则、无前缀=glob | 单字符前缀让既有 `Bash(git *)` 这种写法继续 work;用户写新形式时直观(=foo 一眼就是精确) |
| 反向类型嵌套 | `!=value`、`!~regex`、`!glob` 都合法 | 反向是一元运算,对内层 matcher 取反;嵌套写法直接,不需要 `not()` 函数语法 |
| Matcher 用 Protocol + dataclass | 而非 enum + match-case | Protocol 与 frozen dataclass 组合贴合 Python 习惯,Matcher 不可变;新增类型时只要实现 `match` / `__str__` 即可 |
| Hook 包独立 | `forgecode.hook` | 与 `forgecode.permission` 平级;hook 依赖 `permission.Matcher`,但 permission 不依赖 hook,无循环 |
| Event 用 `str` 枚举 | `class Event(str, enum.Enum)` | YAML 字面量(SessionStart 等)与 enum value 直接对应;`Event("SessionStart")` 反查方便;日志可读 |
| Payload 用 dict[str, Any] | 而非 dataclass | 11 个事件字段差异大;dict + `get_by_path` 灵活;`json.dumps(..., sort_keys=True)` 天然有序 |
| Reminder 注入用 SessionRuntime 而非 Engine 状态 | `runtime.pending_reminders` | 与现有 plan reminder 同一注入点;下一轮自动清空;不污染 Engine |
| PreToolUse 拦截位置 | 权限 check 之前 | 让用户能用 hook 早于权限引擎做安全策略;hook 拦截后甚至不调权限 check |
| shell 用 sh -c | 而非 list 形式 `["sh", "-c", ...]` 直接给 exec | 用户写 hook 时常用 `\|`、`>` 这种 shell 语法;`create_subprocess_shell` 直接交给 sh 解释 |
| HTTP 默认 POST + JSON body | 而非 GET | hook 多是"事件通知"语义,POST 更合理;用户需要 GET 时显式声明 method |
| HTTP body 用 `str.format_map` | 不开放 Jinja2 等函数 | `format_map` 已经够覆盖字段插值;不引入额外依赖,也避免模板注入风险 |
| HTTP 客户端用 httpx | 而非标准库 urllib | httpx 原生 async,与 Textual 事件循环兼容;`httpx.AsyncClient` 复用连接池 |
| subagent 占位仅打日志 | 不抛异常也不阻塞 | spec 明确本期不实现,但配置应能加载——避免用户写早期配置后续章节直接生效 |
| only_once 用内存 set | 不写盘 | spec N5 明确本期不持久化;set 在 runtime 里,与 ActiveSkills 同生命周期 |
| 事件分派同步串行 | 多 hook 不并发 | 拦截语义需要顺序;同步 stderr 日志顺序也确定;async hook 单独起 task 但 dispatch 不等 |
| 拦截类 sync timeout 不全局上限 | 单条 hook timeout 累加 | 用户配的 timeout 自己负责;全局上限会引入复杂语义 |
| 字段名 `asyncio_mode` 替代 `async` | 避免与 Python 关键字冲突 | YAML 里仍写 `async: true`,Loader 内部映射到 `Rule.asyncio_mode`;dataclass 字段名要合法 |
| `/hooks` 命令风格 | 与 `/skill` 对齐 | 已加载条目按事件分组、每条一行;末尾标加载来源 |
| 加载来源记录 | `engine._sources: list[str]` | YAML 文件路径列表,`/hooks` 命令通过 `engine.sources` 取出展示 |