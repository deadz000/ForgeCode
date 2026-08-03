# SubAgent 机制 Plan## 技术栈
- 语言：Python 3.12+
- TUI：Textual（async-first 的 TUI 框架）+ Rich(继承 ch02 起的现状)
- 配置：YAML 解析（`pyyaml`，import 名 `yaml`）
- LLM 通信：官方 Python SDK —— `anthropic`（`AsyncAnthropic`）、`openai`（`AsyncOpenAI`）
- 并发模型:asyncio + `asyncio.create_task` / `asyncio.Queue` / `asyncio.CancelledError`
- 工具调用与权限引擎沿用 ch04~ch12 既有的 `forgecode.agent` / `forgecode.permission` / `forgecode.hook` 模块

## 架构概览

本章实现拆为四个层次：

1. **subagent 包**（新增,核心数据层）——定义 Agent 角色的数据结构、Markdown+YAML 解析、Catalog 多来源加载、内置角色随包发布
2. **task 包**（新增,后台运行层）——`task.Manager` 管理后台任务生命周期,4 个内置工具(TaskList / TaskGet / TaskStop / SendMessage)
3. **agent 包扩展**——新增 `run_to_completion` 方法、6 个新构造参数、Fork 路径辅助函数 `build_forked_messages`、子 Agent 权限升级回调
4. **工具与 TUI 集成层**——Agent 工具实现、工具过滤多层防线常量、TUI 接入 task notification、ESC 切后台、Skill fork 改造为复用 SubAgent 底座

模块构成：

- `subagent.Definition` / `subagent.Catalog` / `subagent.Source*` — 数据结构与三层加载
- `forgecode.subagent.builtin/*.md` — 内置 3 个角色文件,`importlib.resources` 读取
- `task.Manager` / `task.BackgroundTask` — 后台任务管理与生命周期
- `task.*Tool` — 4 个内置工具,注册到 `tool.Registry`
- `agent.Agent.run_to_completion` / `system_prompt` / `provider` / `max_turns` / `permission_mode` / `approval_upgrader` — Agent 类扩展
- `agent/fork.py` — `build_forked_messages`、Fork Boilerplate 常量
- `agent/agent_tool.py` — Agent 工具实现
- `tool/filter.py` — `ALL_AGENT_DISALLOWED_TOOLS` / `ASYNC_AGENT_ALLOWED_TOOLS` 常量与过滤函数
- `tui` 改动 — TaskManager wiring、ESC 切后台、`<task-notification>` 注入、子 Agent 审批弹窗
- `tui/skill_fork.py` 改造 — 复用 `subagent.launch_fork`

## 核心数据结构### subagent.Definition

```python
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Literal

from forgecode.permission import PermissionMode

class Source(IntEnum):
    BUILTIN = 0
    USER = 1
    PROJECT = 2
    PLUGIN = 3  # 占位

    def __str__(self) -> str:
        return {0: "builtin", 1: "user", 2: "project", 3: "plugin"}.get(int(self), "unknown")

@dataclass
class Definition:
    """一个 Agent 角色的完整定义,从 Markdown+YAML frontmatter 解析。"""

    name: str                              # frontmatter.name (-> agent_type)
    description: str                       # frontmatter.description (-> when_to_use)
    tools: list[str] = field(default_factory=list)             # frontmatter.tools 白名单;空表示不收窄
    disallowed_tools: list[str] = field(default_factory=list)  # frontmatter.disallowedTools 黑名单
    model: Literal["haiku", "sonnet", "opus", "inherit"] = "inherit"
    max_turns: int = 0                     # 0 表示沿用全局默认 (25)
    permission_mode: PermissionMode = PermissionMode.DEFAULT  # "dontAsk" 单独处理(见 dont_ask 字段)
    dont_ask: bool = False                 # 是否启用"绕过 Ask"的子 Agent 兜底模式
    background: bool = False               # 强制后台
    system_prompt: str = ""                # Markdown body(去 frontmatter 后的全文)
    file_path: str = ""                    # 定义文件绝对路径(用于调试)
    source: Source = Source.BUILTIN

    def is_fork(self) -> bool:
        return self.name == "__fork__"
```

### subagent.Catalog

```python
import threading

class Catalog:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._defs: dict[str, Definition] = {}                    # name -> 最高优先级定义
        self._by_source: dict[Source, list[Definition]] = {}      # 各层副本(供 /agents 命令展示与 debug)

    def resolve(self, name: str) -> Definition | None: ...
    def list(self) -> list[Definition]: ...        # 按 name 排序
    def list_by_source(self, src: Source) -> list[Definition]: ...

    def fork_definition(self) -> Definition:
        """返回 Fork 路径用的临时 Definition——name="__fork__",
        system_prompt 留空(子 Agent 走继承的系统提示),
        但 disallowed_tools 不应包含 Agent 工具
        (Fork 子 Agent 工具集保留 Agent,靠 QuerySource 阻断)。
        """
        ...

def load_catalog(root: str) -> Catalog:
    """顺序加载:builtin -> user -> project,优先级高的覆盖低的;
    解析错误走 stderr 警告并跳过;返回非 None Catalog 即使无任何定义。"""
    ...
```

### task.Manager 与 BackgroundTask

```python
import asyncio
import time
from dataclasses import dataclass, field
from enum import IntEnum

class Status(IntEnum):
    RUNNING = 0
    COMPLETED = 1
    FAILED = 2
    CANCELLED = 3

@dataclass
class Usage:
    input: int = 0
    output: int = 0
    cache_write: int = 0
    cache_read: int = 0

@dataclass
class BackgroundTask:
    """一个后台子 Agent 的完整状态快照。"""

    id: str                                # manager 生成,如 "task_<8 字节十六进制>"
    name: str                              # F1 中 Agent 工具 name 参数,可空
    sub_agent: "Agent"
    conv: "Conversation"
    task: str                              # 初始任务文本(send_message 不更新此字段)
    status: Status = Status.RUNNING
    result: str = ""                       # 跑完的最终文本
    err: BaseException | None = None
    start_time: float = field(default_factory=time.monotonic)
    end_time: float = 0.0
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    handle: asyncio.Task | None = None     # 跑动协程的 asyncio.Task,Stop 时调 cancel()
    usage: Usage = field(default_factory=Usage)
    tool_count: int = 0
    last_activity: str = ""

@dataclass
class PartialState:
    """前台→后台移交时已收集的中间状态。"""

    last_assistant_text: str = ""
    tool_count: int = 0
    last_activity: str = ""
    usage: Usage = field(default_factory=Usage)

class Manager:
    """管理后台任务。协程安全(单事件循环)。"""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._tasks: dict[str, BackgroundTask] = {}
        self._by_name: dict[str, str] = {}              # name -> id,弱引用,后启动的覆盖
        self._done: asyncio.Queue[str] = asyncio.Queue(maxsize=32)

    async def launch(self, ag: "Agent", conv: "Conversation",
                     name: str, task: str) -> str: ...
    async def adopt_running(self, ag: "Agent", conv: "Conversation",
                            name: str, events: asyncio.Queue,
                            handle: asyncio.Task, partial: PartialState) -> str: ...
    def get(self, id: str) -> BackgroundTask | None: ...
    def list(self) -> list[BackgroundTask]: ...         # 按 start_time 升序
    async def stop(self, id: str) -> bool: ...
    def subscribe_done(self) -> asyncio.Queue[str]: ...
    async def send_message(self, name: str, message: str) -> str: ...
    # 找不到 name -> raise TaskNotFound;status != Completed -> raise TaskBusy
    # 成功时把 message 加到 conv,重新 launch 一轮跑动(选择**同 id**复用)
```

### agent 包扩展

```python
# 新增方法 ---

class Agent:
    # 新增字段 ---
    system_prompt: str | None = None        # 非空时 build_env_text / build_system_prompt 阶段用此覆盖默认
    max_turns: int = 0                      # 0 表示用全局 MAX_ITERATIONS
    permission_mode: PermissionMode | None = None
    dont_ask: bool = False
    approval_upgrader: "ApprovalUpgrader | None" = None

    async def run_to_completion(
        self,
        conv: "Conversation",
        task: str,
        events: asyncio.Queue | None = None,
    ) -> str:
        """执行子 Agent 的"跑到底"循环。

        复用主 ``run`` 的几乎所有逻辑(``_stream_once`` / ``_execute_batched`` / 权限判定),区别:
        - 不通过队列返回事件(内部消费),最终返回 final_text
        - max_turns 由 ``self.max_turns`` 决定(若 0 则用 MAX_ITERATIONS)
        - 不触发 memory update / 不触发 compact reminder 等主对话专属逻辑(子 Agent 上下文短,
          不需要;但内部依然走 ``_manage_context_auto`` 防止超长)
        - 接受一个可选的 events 队列,把内部事件(text/tool/approval)转发出去——
          TaskManager 借此聚合 tool_count / last_activity,
          TUI 借此渲染前台子 Agent 的进度
        """
        ...

# 新增类型 ---

# ApprovalUpgrader 是子 Agent 把审批请求升级到父 TUI 的回调。
# 实现方:TaskManager 把请求转发到主 TUI 的事件流;前台 inline 模式直接复用现有 Approval 路径。
ApprovalUpgrader = Callable[
    [ApprovalRequest],
    Awaitable[tuple[PermissionOutcome, bool]],
]
```

`Agent.__init__` 接受的新关键字参数:
- `system_prompt: str | None` — 非空时 build_env_text / build_system_prompt 阶段用此覆盖默认
- `max_turns: int` — 0 表示用全局 MAX_ITERATIONS
- `permission_mode: PermissionMode | None` — 子 Agent 启动模式(主 Agent 用 TUI 的运行时 mode)
- `dont_ask: bool`
- `approval_upgrader: ApprovalUpgrader | None`
- `provider: Provider | None` — 与父不同的 provider(model 覆盖时切换)

### fork.py 内容

```python
FORK_BOILERPLATE_TAG = "<fork_boilerplate>"

# Fork 子 Agent 首条 user 消息的前缀,约束其行为。
FORK_BOILERPLATE = """<fork_boilerplate>
你是一个 Fork 出来的工作进程。你不是主 Agent。
规则(不可协商):
1. 不能再 Fork(调用 Agent 工具会被拦截)。
2. 不要对话、不要提问、不要请求确认。
3. 直接使用工具:读文件、搜索代码、做修改。
4. 严格限制在你被分配的任务范围内。
5. 最终报告以 "Scope:" 开头,500 字以内。
</fork_boilerplate>

"""

def build_forked_messages(parent_msgs: list[Message], task: str) -> list[Message]:
    """把父对话克隆到 Fork 子对话,处理悬空 tool_use,追加 Boilerplate + task。

    行为:
      1. 深拷贝 parent_msgs(所有 Message + 内部 tool_calls / tool_results 列表)
      2. 扫描末尾 assistant 消息的 tool_calls,如果对应的 RoleTool 消息缺失,
         生成一条 placeholder tool_results(每个 ID 对一条"[forked, skipped]" 错误内容)
      3. 追加 user 消息 = FORK_BOILERPLATE + task

    返回新消息列表,直接用 ``Conversation.from_messages`` 装载即可。
    """
    ...

def is_fork_context(msgs: list[Message]) -> bool:
    """判定一个 conversation 的消息历史是否来自 Fork(用 FORK_BOILERPLATE_TAG 扫描)。
    QuerySource 检测的兜底机制——caller 链丢失时靠这个。
    """
    ...
```

### Agent 工具

`src/forgecode/agent/agent_tool.py`:

```python
@dataclass
class AgentArgs:
    prompt: str
    description: str
    subagent_type: str = ""
    model: str = ""
    run_in_background: bool = False
    name: str = ""

class AgentTool(Tool):
    """注册到 ``tool.Registry`` 的统一 Agent 工具。"""

    def __init__(
        self,
        catalog: subagent.Catalog,
        task_mgr: task.Manager,
        parent: Agent | None,         # 取 provider / registry / engine / runtime 等
        bg_enabled: bool,             # N6 配置开关
    ) -> None: ...

    @property
    def name(self) -> str: return "Agent"

    @property
    def read_only(self) -> bool: return False  # 子 Agent 可能做任何事

    def description(self) -> str:
        """列出已知的 subagent_type 名,从 catalog.list() 渲染。"""
        ...

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        # 1. 解析 args -> AgentArgs;校验 prompt / description 非空
        # 2. 防嵌套:从 ctx 取 parent_info,若 parent 已是子 Agent 或对话历史含 fork tag -> 返回错误
        # 3. resolve 定义:subagent_type 非空走 catalog.resolve,空走 catalog.fork_definition
        # 4. 决定 background:def.background or args.run_in_background or is_fork
        # 5. 应用工具过滤多层防线 apply_agent_tool_filter,得到 allowed: list[str]
        # 6. 选 provider:args.model 非空 -> 切;否则 def.model != "inherit" -> 切;否则用 parent
        # 7. 构造子 Agent + 子 conv(空白或 Fork 路径装填消息)
        # 8. 前台路径:asyncio.wait_for(run_to_completion(...), timeout=120)
        #    - 完成 → 返回 final_text
        #    - asyncio.TimeoutError → adopt_running,返回 {task_id, status:"timed_out_to_background"}
        # 9. 后台路径:launch,返回 {task_id, status:"async_launched"}
        ...

    def set_parent(self, ag: Agent) -> None: ...
```

### 工具过滤多层防线

`src/forgecode/tool/filter.py`:

```python
# 任何子 Agent 永远不能用的工具名列表。
# 本期最小列表:Agent。后续可扩展 AskUserQuestion / TaskStop / 系统级敏感工具。
ALL_AGENT_DISALLOWED_TOOLS: list[str] = ["Agent"]

# 自定义(user / project / plugin 来源)Agent 比内置 Agent 多禁用的工具。本期为空。
CUSTOM_AGENT_DISALLOWED_TOOLS: list[str] = []

# 后台 Agent 工具白名单。
# 不含 Agent / TaskStop / SendMessage / TaskList / TaskGet 等任何元工具。
ASYNC_AGENT_ALLOWED_TOOLS: list[str] = [
    "read_file", "write_file", "edit_file",
    "glob", "grep",
    "bash",
    "load_skill", "install_skill",
]
# MCP 工具与 Skill 工具按命名约定动态识别(以 "mcp__" 起头 / 来自 register_skill_tool),
# 通过 is_allowed_in_background 函数走另一条分支判定。

@dataclass
class FilterParams:
    all: list[str]                    # registry 的全部工具名(按注册顺序)
    source: int                       # subagent.Source 的整数值
    background: bool
    allowed: list[str] = field(default_factory=list)     # Agent 定义 tools 白名单
    disallowed: list[str] = field(default_factory=list)  # Agent 定义 disallowedTools 黑名单

def apply_agent_tool_filter(p: FilterParams) -> list[str]:
    """按 spec F30 顺序过滤。返回最终 allowed 列表(传给 Agent 构造参数)。"""
    ...
```

### TUI 集成层

`src/forgecode/tui/app.py` 改动：
- `ForgeCodeApp.__init__` 加 `task_mgr: task.Manager`、`subagent_catalog: subagent.Catalog`(由 cli 注入)
- `on_mount()` 末尾 `asyncio.create_task(self._consume_task_done())`
- 主对话 Agent 通过 `approval_upgrader=self.task_mgr.upgrade_approval` 让子 Agent 审批升级回主 TUI

`src/forgecode/tui/stream.py` 改动：
- `_consume_stream` 监听 ESC 键(Textual `BINDINGS = [("escape", "esc", "")]`):若 `state == STREAMING` 且当前有运行中的 SubAgent → 调 `self.task_mgr.adopt_running(...)`,切回 idle 态
- 监听 SubAgent ApprovalRequest 转发——TaskManager 通过 events 队列转回主 TUI 走现有 Approval 路径

`src/forgecode/tui/skill_fork.py` 改造：
- 删除现有 `run_sub_agent` 内的零散逻辑
- 改为调 `subagent.launch_fork(host, opts, conv)`,host 持有 `self.task_mgr` / `self.runtime` / `self.engine` 等

## 模块设计### 模块 A:`forgecode.subagent`**职责:**
- 数据结构 `Definition`
- Markdown + YAML 解析(复用 `skills/parser.py` 的 `parse_frontmatter_and_body`——抽到 `forgecode.util.markdown` 让两方共用,或 skills 与 subagent 都各自有一份)
- 三层 + 内置随包加载

**对外接口:**
- `load_catalog(root: str) -> Catalog`
- `Catalog.resolve(name)` / `list()` / `fork_definition()`

**依赖:**
- `forgecode.permission`(解析 permission_mode 字段)
- `pyyaml`
- 标准库 `pathlib` / `importlib.resources`

**关键设计:**
- Markdown 解析复用 `skills/parser.py` 的 `parse_frontmatter_and_body`——抽到 `subagent/parser.py` 独立实现一份(避免互相依赖),内容几乎一致
- 内置文件 `forgecode/subagent/builtin/general-purpose.md` / `explore.md` / `plan.md` 通过 `importlib.resources.files("forgecode.subagent.builtin")` 读取
- 加载错误统一 stderr `print(f"subagent {name}: ... skipped", file=sys.stderr)`

### 模块 B:`forgecode.task`**职责:**
- 后台任务生命周期管理
- 4 个内置工具(TaskList / TaskGet / TaskStop / SendMessage)

**对外接口:**
- `Manager()`
- `launch / adopt_running / get / list / stop / send_message / subscribe_done`
- `TaskListTool / TaskGetTool / TaskStopTool / SendMessageTool` 4 个 Tool 类(或 `new_task_list_tool(m)` 等工厂)

**依赖:**
- `forgecode.agent`(Agent)
- `forgecode.conversation`
- `forgecode.tool`
- `forgecode.llm`

**关键设计:**
- `_done` 队列 `maxsize=32` 够大,正常场景不可能填满;真满了 `put_nowait` 抛 `QueueFull` 时丢弃 + stderr 警告(主 TUI 漏一条通知不致命)
- `launch` 协程包 `try/except BaseException`,任何异常转 `status=failed`
- `stop` 调 `task.handle.cancel()`,handle 是 `asyncio.create_task(run_to_completion(...))`
- `send_message`:仅当 `status == COMPLETED` 时允许;否则 raise `TaskBusy`。重新 `launch` 时用 *同 id*,status 从 COMPLETED 重置回 RUNNING

### 模块 C:`forgecode.agent` 扩展**职责:**
- 新增 `run_to_completion` 方法
- 新增 6 个 `__init__` 关键字参数
- Fork 路径辅助

**对外新增接口:**
- `Agent.run_to_completion(conv, task, events=None) -> str`
- `Agent.__init__(..., system_prompt, max_turns, permission_mode, dont_ask, approval_upgrader, provider)`
- `build_forked_messages`
- `is_fork_context`

**关键设计:**
- `run_to_completion` 与 `run` 共用 `_stream_once` / `_execute_batched` / `_manage_context_auto` /
  `_record_read_file_if_applicable`,通过抽公共 helper 实现共享(把 `run` 的循环体抽到
  `_run_iter(conv, mode, iter_idx, ...)`,`run` 与 `run_to_completion` 都调它)
- 子 Agent 的 `permission_mode` + `dont_ask` 决策点在 `_execute_batched` 的 `_run_guarded` 内多一层短路:
  ```python
  if self.dont_ask:
      # 角色定义 dontAsk:走 sandbox / 黑名单 / 规则后,默认 Allow 而非 Ask
      if decision == PermissionDecision.ASK:
          decision = PermissionDecision.ALLOW
  ```
- 升级到父 TUI 的回调在 `_request_approval` 里调:
  ```python
  if self.approval_upgrader is not None:
      outcome, ok = await self.approval_upgrader(req)
      if ok:
          return outcome, True
  # 否则走默认 emit Approval event 路径(主 Agent inline 子 Agent 路径)
  ```

**Fork Boilerplate 注入策略:**
- `build_forked_messages` 把 Boilerplate 写在 user 消息开头(与 ch13 README 一致)
- `is_fork_context` 扫描 *所有* 历史 user 消息内容寻找 `<fork_boilerplate>`(QuerySource 兜底)

### 模块 D:Agent 工具与 TUI 集成**职责:**
- 把 Agent 工具注册到 registry
- TUI 接入 task notification
- 改造 Skill fork

**对外接口:**
- `AgentTool(catalog, task_mgr, parent, bg_enabled)`
- `subagent.launch_fork(host, opts)` 公共 Fork 启动函数(Skill fork 与 Agent 工具都调)

**关键设计:**
- `AgentTool.execute` 在前台 inline 路径返回结果时要小心:
  - 前台跑完返回 final_text 作为 tool_result content
  - 中途超时切后台 → 返回 JSON `{"task_id": "...", "status": "timed_out_to_background"}`
- 嵌套阻断:`AgentTool.execute` 入口检查 `ctx` 是否携带 `parent_agent_ctx_key`(子 Agent 启动时塞入);若有 → 返回结构化错误
  - 不依赖 ctx 单值:也扫 conv 历史是否含 Fork tag(`is_fork_context`)
- TUI 的 task notification 注入:
  - `on_mount()` 开 `asyncio.create_task(self._consume_task_done())`
  - `_consume_task_done()` 接 `done` 队列,`get` 拿状态,渲染成 `<task-notification>` 块,调 `self.runtime.append_reminders` 推入
  - 主对话下一次 run 自动拿到(已有机制)

## 模块交互### 启动期 wiring

```
cli.main()
  ├── tool.default_registry()       → registry
  ├── permission.Engine(root)       → engine
  ├── SessionRuntime(...)           → runtime
  ├── skills.load_catalog(...)      → skill_catalog
  ├── hook.load(...)                → hook_engine
  ├── subagent.load_catalog(root)   → subagent_catalog       ← 新增
  ├── task.Manager()                → task_mgr               ← 新增
  ├── registry.register(task.TaskListTool(task_mgr))         ← 新增
  ├── registry.register(task.TaskGetTool(task_mgr))          ← 新增
  ├── registry.register(task.TaskStopTool(task_mgr))         ← 新增
  ├── registry.register(task.SendMessageTool(task_mgr))      ← 新增
  ├── ForgeCodeApp(..., task_mgr=task_mgr, subagent_catalog=subagent_catalog, ...)
  │     │
  │     └── 在 ForgeCodeApp 内:Agent 工具的注册被推迟到主 Agent 构造后
  │         (因为要把 parent_agent 注入),或者 Agent 工具 lazy 拿:把 catalog / task_mgr 写死,
  │         parent_agent 通过函数 / 持有 self.app 拿
```

**简化方案:** Agent 工具在 `cli.main` 注册,parent 字段在 `ForgeCodeApp` 构造完后回填:
```python
agent_tool = AgentTool(subagent_catalog, task_mgr, parent=None,
                       bg_enabled=cfg.effective_enable_subagent_background())
registry.register(agent_tool)
# 再 ForgeCodeApp(...)
app = ForgeCodeApp(...)
# 再
agent_tool.set_parent(app.main_agent)
```

### 运行时:主 Agent 调 Agent 工具(前台,定义式)

```
LLM 流式产出 tool_use:{name:"Agent", input:{prompt:"...", subagent_type:"Explore"}}
    ↓
Agent._execute_batched → 路由到 AgentTool.execute(args, ctx)
    ↓
AgentTool.execute:
    1. 解析参数 -> AgentArgs
    2. 防嵌套:检测 ctx / conv 是否来自 Fork → 否
    3. catalog.resolve("Explore") → defi
    4. background = defi.background or args.run_in_background → False
    5. apply_agent_tool_filter(...) -> allowed
    6. provider = AnthropicProvider(model="haiku") if defi.model == "haiku" else parent.provider
    7. sub_runtime = SessionRuntime(200_000)
    8. sub_agent = Agent(
           provider=provider, registry=registry, version=version, engine=engine,
           runtime=sub_runtime,
           allowed_tools=allowed,
           system_prompt=defi.system_prompt,         ← 新
           max_turns=defi.max_turns,
           permission_mode=defi.permission_mode,
           dont_ask=defi.dont_ask,
           approval_upgrader=parent.task_mgr.upgrade_approval,
           hook_engine=parent.hook_engine,
       )
    9. sub_conv = Conversation()
    10. try:
            final_text = await asyncio.wait_for(
                sub_agent.run_to_completion(sub_conv, args.prompt, events),
                timeout=120.0,
            )
        except asyncio.TimeoutError:
            task_id = await task_mgr.adopt_running(
                sub_agent, sub_conv, args.name, events, running_task, partial,
            )
            return ToolResult(content=f'{{"task_id":"{task_id}","status":"timed_out_to_background"}}')

        return ToolResult(content=final_text)
```

### 运行时:主 Agent 调 Agent 工具(后台,显式)

```
AgentTool.execute:
    ...
    10. task_id = await task_mgr.launch(sub_agent, sub_conv, args.name, args.prompt)
    11. 返回 ToolResult(content='{"task_id":"task_xxx","status":"async_launched"}')
```

### 后台任务完成通知

```
task_mgr.launch 协程:
    final_text = await sub_agent.run_to_completion(conv, task, events)
    bt.result = final_text
    bt.err = None
    bt.status = Status.COMPLETED  # (or FAILED / CANCELLED)
    try:
        self._done.put_nowait(task_id)
    except asyncio.QueueFull:
        # 缓冲满,丢弃 + stderr 警告
        ...
    ↓
ForgeCodeApp._consume_task_done 协程:
    while True:
        task_id = await self.task_mgr.subscribe_done().get()
        bt = self.task_mgr.get(task_id)
        if bt is None:
            continue
        notification = build_task_notification(bt)  # <task-notification>...</task-notification>
        self.runtime.append_reminders([notification])
        # 不主动唤醒主对话:等主 Agent 下次 run 自然 take reminder
    ↓
下一次 self._begin_turn → self.agent.run → build_reminder takes pending_reminders → 注入 reminder 区
```

### Fork 路径

```
AgentTool.execute (subagent_type 空):
    1. defi = catalog.fork_definition()       # name="__fork__"
    2. background = True (Fork 强制)
    3. allowed = apply_agent_tool_filter(...)
       注意:这里 defi.disallowed_tools 不含 "Agent" → Fork 子 Agent 工具集保留 Agent
    4. forked_msgs = build_forked_messages(parent_conv.messages(), args.prompt)
    5. sub_conv = Conversation.from_messages(forked_msgs)
    6. sub_agent = Agent(..., allowed_tools=allowed, system_prompt=None)  # 继承主系统提示
    7. task_id = await task_mgr.launch(sub_agent, sub_conv, args.name, args.prompt)
    8. 返回 ToolResult(content='{"task_id":"...","status":"async_launched"}')
```

### Fork 子 Agent 调 Agent 工具被阻断

```
Fork 子 Agent 跑动中,LLM 又产 tool_use:{name:"Agent", input:{...}}
    ↓
sub_agent._execute_batched → AgentTool.execute(args, sub_ctx)
    ↓
AgentTool.execute:
    检测:is_fork_context(sub_conv.messages()) → True(消息中含 <fork_boilerplate>)
    → 返回 ToolResult(is_error=True,
                      content="Fork 子 Agent 不能再启动 Agent(检测到 fork boilerplate)")
```

注:由于 `ALL_AGENT_DISALLOWED_TOOLS = ["Agent"]` 已经把 Agent 工具从子 Agent 工具列表里剔除,理论上 Fork 子 Agent 的 LLM 看不到 Agent 工具。但 Fork 路径**故意保留**(为了 prompt cache 一致性),靠 QuerySource + Boilerplate 兜底拦截。

**结论:** Fork 子 Agent 工具列表 = 父工具列表 - disallowed_tools - 后台白名单交集 - 但不去除 Agent 工具。

### Skill fork 改造

```
ForgeCodeApp.execute("/foo") → skills.Executor.execute → fork 闭包 self._run_sub_agent
    ↓ (改造后)
self._run_sub_agent(conv, opts):
    return await subagent.launch_fork(
        host=subagent.HostFromApp(self),
        opts=subagent.ForkLaunchOpts(
            allowed_tools=opts.allowed_tools,
            model=opts.model,
            conv=conv,                     # skills 已构造好的 fork_conv
            system_prompt="",              # 走继承
            background=False,              # skills 仍走前台同步(返回 final_text 给 host)
            events_sink=None,
        ),
    )
```

`subagent.launch_fork` 内部:做与 `AgentTool.execute` 前台路径相同的 wiring,只是不读 catalog Definition。

## 文件组织

```
forgecode/
├── pyproject.toml
├── src/
│   └── forgecode/
│       ├── subagent/                       ← 新增包
│       │   ├── __init__.py                 公共导出
│       │   ├── definition.py               Definition / Source 类型
│       │   ├── parser.py                   parse_frontmatter_and_body + validate_meta
│       │   ├── catalog.py                  Catalog + load_catalog / resolve / list / fork_definition
│       │   ├── embed.py                    importlib.resources 读取 builtin/*.md + builtin_definitions()
│       │   ├── launch.py                   (本期取消,见 T31 说明) — 改放到 agent/launch.py
│       │   └── builtin/
│       │       ├── general-purpose.md
│       │       ├── explore.md
│       │       └── plan.md
│       │
│       ├── task/                           ← 新增包
│       │   ├── __init__.py
│       │   ├── manager.py                  Manager + BackgroundTask + launch / adopt_running / stop / send_message
│       │   └── tools.py                    TaskListTool / TaskGetTool / TaskStopTool / SendMessageTool
│       │
│       ├── agent/                          ← 现有包扩展
│       │   ├── agent.py                    现有,加 system_prompt / max_turns / permission_mode / dont_ask / approval_upgrader 字段;run 抽 _run_iter;_run_guarded 加 dont_ask 短路 + approval_upgrader 升级
│       │   ├── run_to_completion.py        ← 新增 run_to_completion 实现
│       │   ├── fork.py                     ← 新增 build_forked_messages / is_fork_context / FORK_BOILERPLATE
│       │   ├── agent_tool.py               ← 新增 AgentTool
│       │   ├── permission_upgrade.py       ← 新增 ApprovalUpgrader 类型 + default_upgrader
│       │   └── launch.py                   ← 新增 launch_fork(供 skill_fork 调用)
│       │
│       ├── tool/                           ← 现有包扩展
│       │   └── filter.py                   ← 新增 ALL_AGENT_DISALLOWED / ASYNC_AGENT_ALLOWED / apply_agent_tool_filter
│       │
│       ├── tui/                            ← 现有包改动
│       │   ├── app.py                      加 task_mgr / subagent_catalog 字段 + _consume_task_done 协程 + AgentTool 注册
│       │   ├── stream.py                   _consume_stream 加 ESC → adopt_running 分支;子 Agent ApprovalRequest 转发
│       │   ├── tasks.py                    ← 新增 _consume_task_done + build_task_notification + ESC 切后台辅助
│       │   └── skill_fork.py               ← 改造为复用 agent.launch_fork
│       │
│       ├── config.py                       ← 现有,加 enable_subagent_background 字段(默认 True)
│       └── cli.py                          ← 加 subagent.load_catalog / task.Manager / 4 个工具注册 / Agent 工具注册
│
└── tests/
    ├── subagent/
    │   ├── test_parser.py
    │   ├── test_catalog.py
    │   └── test_launch.py
    ├── task/
    │   ├── test_manager.py
    │   └── test_tools.py
    ├── agent/
    │   ├── test_fork.py
    │   ├── test_run_to_completion.py
    │   ├── test_agent_tool.py
    │   └── test_agent_tool_integration.py
    ├── tool/
    │   └── test_filter.py
    └── tui/
        └── test_tui.py
```

## 技术决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| run_to_completion 与 run 关系 | 共用底层 helper(`_run_iter` / `_stream_once`),不重新写一遍循环 | 避免两套循环逻辑漂移;主对话与子 Agent 在 ReAct 层面行为应一致 |
| 子 Agent 是否独立 PermissionEngine | 暂共享同一 Engine,但增加 approval_upgrader 让审批升级回主 TUI | 本期权限规则全局一致;独立 Engine 是为隔离规则集准备的预留扩展点 |
| Fork 强制后台 | 是 | ch13 README 设计;Fork 上下文长,前台同步会阻塞用户;并行 Fork 才有意义 |
| 后台通知形式 | system reminder 注入(`<task-notification>`),不直接 push 到 LLM | 与 ch12 pending_reminders 一致;不打断用户当前操作;主 Agent 下次 turn 自然消费 |
| 嵌套阻断三道闸 | `ALL_AGENT_DISALLOWED_TOOLS` 全局 + Fork 路径 QuerySource + Boilerplate 标记扫描 | 单一闸门失效(对话压缩、工具列表漂移)仍能兜底;定义式靠工具过滤,Fork 靠双闸 |
| 后台白名单粒度 | 列具体工具名 + MCP / Skill 工具按命名约定动态识别 | ch13 README 同款做法;不需要为每个 MCP 工具列在白名单里 |
| done 队列缓冲 32 | 够大 | 正常场景一会儿不会有 32 个任务同时跑完;真满则 `put_nowait` 抛 `QueueFull`,捕获后丢弃 + stderr |
| send_message 同 id 复用 | 是 | 状态语义上是"该任务继续",而非"新任务";UI / 查询体验更连贯 |
| 配置开关 enable_subagent_background | 默认 True | 后台是核心能力,默认开启;关闭后所有子 Agent 强制前台,主要供 CI / 调试用 |
| Markdown 解析器复用 | 不共享,subagent 包独立实现一份(几乎与 `skills/parser.py` 一致) | 避免抽公共包导致循环依赖;两个包字段不一样,复用收益有限 |
| Agent 工具的 parent 注入时机 | `cli.main` 注册时为 None,`ForgeCodeApp` 构造后 `set_parent` 回填 | `Registry` 在 `ForgeCodeApp` 之前已构造,Agent 工具的 parent 依赖 `app.main_agent` 反推 |
| ESC 切后台 vs Ctrl+C | ESC 切后台,Ctrl+C 仍是取消(沿用现有) | ESC 在 TUI 已经做"取消选择"用途,但流式态下 ESC 转为切后台是 ch13 README 设计 |
| 并发原语 | `asyncio.Queue` / `asyncio.Task` / `asyncio.Event` / `asyncio.wait_for` | Python async-first 体系;不用线程池,与 Textual 事件循环天然共存 |
| 内置 .md 加载 | `importlib.resources.files("forgecode.subagent.builtin")` | 标准库官方推荐方式;打包成 wheel 后仍能读取;无需 manifest 配置 |