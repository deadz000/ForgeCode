# Agent Team Plan## 架构概览

本章引入 `forgecode.team` 顶层包,把 ch13 SubAgent 的「子 Agent」扩展为「Team 队员」。整体分四层:

1. **数据模型层**(`team/types.py` + `team/manager.py` + `team/persistence.py`)——Team、TeammateInfo 数据结构与持久化
2. **后端层**(`team/backend/`)——`Backend` Protocol 与三种实现 tmux / iterm2 / inprocess,屏蔽 spawn 差异
3. **协作层**(`team/mailbox/`、`team/registry/`、`team/tasks/`)——邮箱(含文件锁)、AgentNameRegistry、共享任务列表
4. **工具与集成层**(`team/tools/` + `agent` 包扩展 + `coordinator` 包)——5 个协作工具 + `Agent` 工具的 `team_name` 分支 + Coordinator Mode

Lead 仍是 `tui.ForgeCodeApp.main_agent`——本期 Lead 没有独立类型,通过 `coordinator.is_enabled()` 在启动时收窄其工具集即可。

依赖方向(单向):
```
tui  ──→  agent  ──→  team  ──→  team/{backend,mailbox,registry,tasks,tools}
                       └──→  worktree(ch14)、task(ch13)、session(ch12)、subagent(ch13)
```
`team` 不反向依赖 `agent` 包(避免环);`agent` 通过新增的 `TeamHook` Protocol 注入 team 行为。

## 核心数据结构### `team.Team`

```python
from dataclasses import dataclass, field
from datetime import datetime
import asyncio

@dataclass
class Team:
    name: str                       # 用户给的原始名
    sanitized_name: str             # 经 sanitize 后用于路径,Team 主键
    lead_agent_id: str              # 固定 "lead"(本期 Lead = 主 Agent)
    backend: "BackendType"          # 全 team 默认后端;可被 member 覆盖
    description: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    members: list["TeammateInfo"] = field(default_factory=list)

    # 派生路径(不持久化)
    config_dir: str = ""
    config_path: str = ""           # <config_dir>/config.json
    tasks_path: str = ""            # <config_dir>/tasks.json
    mailbox_dir: str = ""           # <config_dir>/mailbox/

    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False, compare=False)
```

### `team.TeammateInfo`

```python
@dataclass
class TeammateInfo:
    name: str
    agent_id: str
    agent_type: str = ""             # "" 表 Fork
    model: str = ""                  # "" 表 inherit
    worktree_path: str = ""          # 绝对路径
    branch: str = ""
    backend_type: "BackendType" = "in-process"
    pane_id: str = ""                # tmux pane id / iterm2 split id / "" for in-process
    is_active: bool | None = None    # None/True 活跃,False 空闲;不存在视为终止
    plan_mode_required: bool = False
    session_dir: str = ""            # 绝对路径
```

序列化通过手写 `to_dict` / `from_dict` 完成(F19c 的 reload 流程需要细粒度控制 `is_active` 的 None 语义)。

### `team.Manager`

```python
@dataclass
class Manager:
    teams: dict[str, Team] = field(default_factory=dict)   # 按 sanitized_name 索引
    home_dir: str = ""
    wt_mgr: "worktree.Manager" = None
    task_mgr: "task.Manager" = None
    registry: "AgentNameRegistry" = None
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False, compare=False)
```

### `team.BackendType`

```python
from enum import StrEnum

class BackendType(StrEnum):
    TMUX = "tmux"
    ITERM2 = "iterm2"
    IN_PROCESS = "in-process"
```

### `team/backend.Backend`

```python
from typing import Protocol, Any
from dataclasses import dataclass

class Backend(Protocol):
    def type(self) -> BackendType: ...
    async def spawn(self, req: "SpawnRequest") -> tuple[str, str]: ...   # (pane_id, agent_id)
    async def wake(self, pane_id: str, agent_id: str) -> None: ...
    async def kill(self, pane_id: str, agent_id: str) -> None: ...

@dataclass
class SpawnRequest:
    team_name: str
    member_name: str
    agent_id: str
    worktree_path: str
    session_dir: str
    agent_type: str
    model: str
    initial_prompt: str
    plan_mode_required: bool

    # in-process 专用——同进程后端直接复用这三个对象
    sub_agent: Any = None       # agent.Agent
    conv: Any = None            # conversation.Conversation
    task_mgr: Any = None        # task.Manager
```

### `team/mailbox.Message` / `Box`

```python
from enum import StrEnum
from dataclasses import dataclass, field
from typing import Any

class MessageType(StrEnum):
    TEXT = "text"
    SHUTDOWN_REQUEST = "shutdown_request"
    SHUTDOWN_RESPONSE = "shutdown_response"
    PLAN_APPROVAL_RESPONSE = "plan_approval_response"

@dataclass
class Message:
    from_: str                       # json key "from"
    to: str
    type: MessageType
    summary: str
    content: str
    payload: dict[str, Any] | None = None
    timestamp: int = 0
    read: bool = False

class Box:
    def __init__(self, dir_: str) -> None:
        self._dir = dir_             # <team_config_dir>/mailbox/

    async def write(self, agent_id: str, msg: Message) -> None: ...
    async def read(self, agent_id: str) -> list[Message]: ...
    async def read_unread(self, agent_id: str) -> tuple[list[int], list[Message]]: ...
    async def mark_read(self, agent_id: str, indices: list[int]) -> None: ...
```

文件锁机制内置在 `Box` 内,所有公开方法都走锁。

### `team/registry.AgentNameRegistry`

```python
import threading

class AgentNameRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_name: dict[str, str] = {}   # name → agent_id
        self._by_id: dict[str, str] = {}     # agent_id → name

    def register(self, name: str, agent_id: str) -> None: ...
    def unregister(self, name: str) -> None: ...
    def resolve(self, name_or_id: str) -> str | None: ...
    def name_of(self, agent_id: str) -> str | None: ...
```

注意:本章把 `task.Manager._by_name` 替换/委托给这套 registry——`task.Manager` 改为持一个 `AgentNameRegistry` 引用。

### `team/tasks.Store`

```python
from enum import StrEnum
from dataclasses import dataclass, field

class Status(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"

@dataclass
class Task:
    id: str
    title: str
    description: str = ""
    status: Status = Status.PENDING
    assignee: str = ""
    blocked_by: list[str] = field(default_factory=list)
    blocks: list[str] = field(default_factory=list)
    created_at: int = 0
    updated_at: int = 0

class Store:
    def __init__(self, path: str) -> None:
        self._path = path
        self._lock = asyncio.Lock()

    async def create(self, t: Task) -> str: ...
    async def get(self, id_: str) -> Task: ...
    async def list_(self, filter_: "Filter") -> list[Task]: ...
    async def update(self, id_: str, patch: "Patch") -> None: ...
```

### `coordinator` 包

```python
# src/forgecode/coordinator/__init__.py
def is_enabled(cfg) -> bool: ...
def allowed_tools() -> list[str]: ...
def system_prompt_suffix() -> str: ...
```

仅 3 个纯函数,无状态。

## 模块设计### `forgecode.team`(顶层)**职责:** Team / TeammateInfo / Manager 数据结构与持久化,跨子包的协调入口。
**对外接口:** `Manager(...)`、`Manager.create/get/delete`、`Team.add_member/set_member_active/remove_member`
**依赖:** `worktree`、`task`、`session`、`team.backend`、`team.mailbox`、`team.registry`、`team.tasks`

### `forgecode.team.backend`**职责:** 屏蔽 tmux / iterm2 / in-process spawn 差异。
**对外接口:** `Backend` Protocol、`detect() -> BackendType`、`new_backend(t: BackendType, **deps) -> Backend`
**依赖:** `team`(取常量)、`agent` 与 `task`(in-process 实现用)

注意:`backend` 包反向依赖 `agent` 会成环。解决:`in-process` 实现走「接口适配」——`backend.spawn` 接收 `SpawnRequest` 中的 `sub_agent: Any`,由调用方(`team` 包)预先构造好;`backend` 包只做调度,不知道 `agent.Agent` 类型。或者把 `in-process` 实现单独提到 `team.backend.inprocess`,允许它依赖 `agent`,而 `team.backend.tmux` / `iterm2` 不依赖。

**采用方案:** 三种后端各一个子模块(`tmux.py` / `iterm2.py` / `inprocess.py`),每个独立实现 `Backend` Protocol,工厂函数 `new_backend(...)` 接收所需依赖。`inprocess` 子模块依赖 `agent` 包没问题(`agent` 在更低层)。

### `forgecode.team.mailbox`**职责:** 邮箱文件 + 文件锁的读写。
**对外接口:** `Box.write/read/mark_read`、`Message` 类型
**依赖:** 仅 stdlib(`os`、`json`、`asyncio`、`pathlib`)

### `forgecode.team.registry`**职责:** Agent name ↔ agent_id 双向映射。
**对外接口:** `register/unregister/resolve/name_of`
**依赖:** 仅 stdlib

### `forgecode.team.tasks`**职责:** 共享任务列表的 CRUD + 依赖图维护。
**对外接口:** `Store.create/get/list_/update`、`Task`、`Filter`、`Patch` 类型
**依赖:** 仅 stdlib

### `forgecode.team.tools`**职责:** 5 个协作工具实现(TaskCreate、TaskGet、TaskList、TaskUpdate、SendMessage)+ 2 个 Team 管理工具(TeamCreate、TeamDelete)。
**对外接口:** 每个工具一个工厂函数 `new_xxx_tool(mgr: team.Manager) -> tool.Tool`
**依赖:** `tool`、`team`、`team.{mailbox,registry,tasks}`

### `forgecode.coordinator`**职责:** Coordinator Mode 的开关检测、工具白名单、系统提示词。
**对外接口:** `is_enabled() -> bool`、`allowed_tools() -> list[str]`、`system_prompt_suffix() -> str`
**依赖:** `config`(读 feature flag)

### `agent` 包扩展

- 新增 `agent.TeamHook` Protocol:
  ```python
  class TeamHook(Protocol):
      # spawn_teammate 让 Agent 工具委托给 Team Manager 处理 team_name 分支。
      # 返回 final_text(立即返回 task_id JSON 描述)。
      async def spawn_teammate(self, req: "TeamSpawnRequest") -> str: ...
      # is_teammate_context 判断当前上下文是否在某队员的执行上下文中(用于拦截嵌套 spawn)。
      def is_teammate_context(self, ctx) -> tuple[str, str, bool]: ...
  ```
- `AgentTool` 持一个 `team_hook: TeamHook | None` 字段(可选,None 时降级为 ch13 行为)
- `Agent.execute` 在 `team_name != ""` 时调 `team_hook.spawn_teammate`

### `task` 包扩展

- `task.Manager` 持一个 `name_reg: AgentNameRegistry` 引用(原 `_by_name` 字段废弃,改委托)
- `task.Manager.send_message` 复用——Team 模块续派直接调它

### `tui` 包扩展

- `ForgeCodeApp` 新增字段 `team_mgr: team.Manager`
- 注入 `/team` 系列 slash 命令(`src/forgecode/command/builtin_team.py`)
- 状态栏新增 `[COORDINATOR]` 标签(若 `coordinator.is_enabled()`)

## 模块交互### TeamCreate 调用路径

```
LLM 调 TeamCreate(team_name="demo")
  ↓
tools.TeamCreate.execute
  ↓
await team.Manager.create("demo", "")
  ↓
1. sanitize("demo") → "demo"
2. detect_backend() → "tmux"
3. mkdir ~/.forgecode/teams/demo/
4. mkdir ~/.forgecode/teams/demo/mailbox/
5. 写 config.json(原子)
6. team.members = [TeammateInfo(name="lead", agent_id="lead", is_active=None)]
7. teams["demo"] = team
  ↓
返回 {"team_name":"demo","backend":"tmux","config_path":"..."}
```

### Agent(team_name=...) spawn 路径

```
LLM 调 Agent(team_name="demo", subagent_type="general-purpose", name="alice", prompt="...")
  ↓
agent.AgentTool.execute
  ↓
判断 team_name != "" → 委托给 team_hook.spawn_teammate
  ↓
await team.spawn_teammate(req)
  ↓
1. manager.get("demo") 取 Team
2. 校验调用者权限(in-process 队员不许 spawn,Pane 队员可以但 team_name 屏蔽)
3. catalog.resolve(agent_type) 取 SubAgentDefinition
4. member_name = req.name(或自动 alice/agent-a1b2c3)
5. await wt_mgr.create("team-demo/"+member_name, "HEAD", False) → worktree
6. 申请 session_dir(util 函数,沿用 ch12 格式)
7. 构造 SpawnRequest
8. 若 backend=in-process:
   - 构造 sub_agent(new_session_runtime + cwd + allowed_tools 含协作工具)
   - 构造 sub_conv(new_from_messages 走 Fork 路径,或空 Conv 走定义式)
   - 注入 <team-context> reminder
   - 注入 system_prompt 附录(F39)
   - SpawnRequest.sub_agent / conv / task_mgr 填好
9. await backend.spawn(req) → (pane_id, agent_id)
10. registry.register(member_name, agent_id)
11. await team.add_member(TeammateInfo(...))
  ↓
返回 {"member_name":"alice","agent_id":"...","worktree":"...","backend":"tmux"}
```

### SendMessage 调用路径

```
LLM 调 SendMessage(to="alice", summary="hi", message="hello")
  ↓
tools.SendMessage.execute
  ↓
1. 取调用者所属 Team(从 ctx 中 TeammateContext 取,或主 Agent 走 active team)
2. resolve to:
   - "*" → 广播
   - 否则 registry.resolve(to) → agent_id
3. 校验消息类型权限(plan_approval_response 仅 Lead,shutdown_response 仅发给 Lead)
4. 对每个目标 agent_id:
   - await mailbox.write(agent_id, msg)
   - 取 TeammateInfo.pane_id 与 backend_type
   - 若 Pane 后端:await backend.wake(pane_id, agent_id)
   - 若目标已 stop(in-process,task.Manager.get(agent_id).status != Running):
     - 从 session_dir 恢复 Conv
     - await task_mgr.send_message(parent_ctx, name, message) 续派
5. 返回 {"delivered_to":["agent-xxx"],"timestamp":...}
```

### 队员 Loop 内邮箱注入

```
队员的 agent.Agent.run 每轮迭代开头(在调 LLM 前):
  ↓
读 ctx 中的 TeammateContext(包含 Box、agent_id)
  ↓
indices, unread = await mailbox.read_unread(agent_id)
  ↓
若 len(unread) > 0:
  reminder = build_incoming_messages_reminder(unread)
  把 reminder 加入本轮 system_reminders
  await mailbox.mark_read(agent_id, indices)
```

`agent.Agent` 已有 system_reminders 注入机制(ch05 / ch07 plan reminder 走同一通道);新增一种 reminder 来源即可。

### 队员 run_to_completion 结束的通知

```
task.Manager._run_task asyncio task 结束(完成 / 失败 / 取消)
  ↓
若该 task 关联到 Team 队员(通过 registry.name_of(agent_id) 反查 name → 查 team)
  ↓
await team.set_member_active(member_name, False)
await mailbox.write(lead_agent_id, Message(type="text", summary="<name> idle", ...))
await backend.wake(lead_pane_id, lead_agent_id)   # 若 Lead 是 Pane 后端
```

需要在 `task.Manager._run_task` 的 try/finally 中加 hook,或者在 `team` 包注册一个回调到 task 包(走依赖反转)。**采用方案:** 在 `task.Manager` 新增 `on_task_done(fn: Callable[[str], Awaitable[None]])` 回调注册接口,`team` 包初始化时注册。

### Coordinator Mode 启用路径

```
cli.main 启动时,在构造主 Agent 后:
  ↓
if coordinator.is_enabled(cfg):
    main_agent.set_allowed_tools(coordinator.allowed_tools())
    main_agent.append_system_prompt(coordinator.system_prompt_suffix())
    app.coordinator_mode = True
```

TUI 渲染 statusbar 时检测 `coordinator_mode` 添加 `[COORDINATOR]` 标签。

## 文件组织

```
src/forgecode/team/
├── __init__.py                    — 包导出
├── types.py                       — Team / TeammateInfo / BackendType 等类型
├── manager.py                     — Manager(create/get/delete/add_member/set_member_active/remove_member)
├── persistence.py                 — 原子写 config.json,sanitize 函数,reload_from_disk_locked
├── spawn.py                       — spawn_teammate 主流程(被 agent.TeamHook 调用)
├── feature.py                     — FORK_TEAMMATE feature flag 读取
├── backend/
│   ├── __init__.py                — Backend Protocol、SpawnRequest、new_backend 工厂
│   ├── detect.py                  — detect()
│   ├── tmux.py                    — Tmux Backend 实现
│   ├── iterm2.py                  — iTerm2 Backend 实现
│   └── inprocess.py               — InProcess Backend 实现
├── mailbox/
│   ├── __init__.py                — Box 类型与 read/write/mark_read
│   ├── lock.py                    — 文件锁机制(抢锁、重试、stale 处理)
│   └── message.py                 — Message / MessageType
├── registry/
│   └── __init__.py                — AgentNameRegistry
├── tasks/
│   ├── __init__.py                — Task / Store
│   └── filter.py                  — Filter/Patch + is_ready 计算
└── tools/
    ├── __init__.py
    ├── team_create.py             — TeamCreate 工具
    ├── team_delete.py             — TeamDelete 工具
    ├── task_create.py
    ├── task_get.py
    ├── task_list.py
    ├── task_update.py
    ├── send_message.py
    └── teammate_filter.py         — 队员专属工具白名单(注入到 apply_agent_tool_filter)

tests/
├── test_team_manager.py
├── test_team_spawn.py
├── test_team_mailbox.py           — 并发与 stale 锁测试
├── test_team_registry.py
├── test_team_tasks.py
├── test_team_backend_detect.py
├── test_team_backend_tmux.py
├── test_team_backend_inprocess.py
├── test_team_tools.py
└── test_coordinator.py

src/forgecode/coordinator/
└── __init__.py                    — is_enabled / allowed_tools / system_prompt_suffix

src/forgecode/agent/
├── agent_tool.py                  — 修改:增加 team_name 参数与 TeamHook 委托
├── team_hook.py                   — 新建:TeamHook Protocol、TeammateContext
└── team_mailbox.py                — 新建:Loop 头部注入 incoming-messages reminder

src/forgecode/task/
└── manager.py                     — 修改:on_task_done 回调注册;改用 registry.AgentNameRegistry

src/forgecode/command/
└── builtin_team.py                — 新建:/team list/info/delete/kill 4 个命令

src/forgecode/tui/
├── app.py                         — 修改:接收 team_mgr;启动时检测 coordinator.is_enabled
├── tasks.py                       — 修改:consume_lead_mail / wait_for_lead_mail 后台 task
├── stream.py                      — 修改:begin_autonomous_turn
└── view.py                        — 修改:渲染 [COORDINATOR] 标签

src/forgecode/config/
└── __init__.py                    — 修改:新增 FeaturesConfig.coordinator_mode / fork_teammate

src/forgecode/cli/
├── __init__.py                    — 修改:wire team.Manager,注册 7 个新工具,接入 coordinator
└── team_member.py                 — 新建:--team-member 自治循环
```

## 技术决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| Team 包归属 | `forgecode.team` 顶层包 | 与 ch13 `subagent`、ch14 `worktree` 平级,职责清晰 |
| 后端三选一时机 | `detect()` 在 `TeamCreate` 时一次性决定 | 与 README 一致:不做运行时回退,行为可预测 |
| 后端实现拆分 | 各一个子模块 `tmux.py / iterm2.py / inprocess.py` | `inprocess` 需要依赖 `agent` 包,拆开避免污染其他 backend |
| Backend Protocol | 三方法 `spawn/wake/kill` | 最小集;not pause/resume(本期不做) |
| Lead 表示 | 不引入独立类型,Lead = `ForgeCodeApp.main_agent` | 收窄改动;Coordinator Mode 在工具集层面区分 |
| 邮箱实现 | `<team_config_dir>/mailbox/<agent_id>.json` + 同名 `.lock` | 跨进程通信现成方案;in-process 与 Pane 共用一套 |
| 锁文件参数 | `os.open(O_CREAT\|O_EXCL\|O_WRONLY)`,5-100ms 抖动 10 次,>10s 视 stale | README 明定;避免雪崩;Python 没有 Go 的 `syscall.Flock` 跨平台等价,所以走 EEXIST 抢占 |
| 任务存储 | `<team_config_dir>/tasks.json` 单文件 | Team 内任务量小(几十条),无需 DB;原子写 + 文件锁 |
| AgentNameRegistry 归属 | 独立 `team.registry` 子包,`task.Manager` 委托 | 解耦;消除 ch13 `task.Manager._by_name` 的局部状态 |
| `task.Manager` 改造 | 加 `on_task_done` 回调,Team 注册 | 依赖反转,避免 task 包反向依赖 team |
| Team 持久化原子性 | `<file>.tmp` + `os.replace` | 与 ch14 worktree session、ch12 session 一致;Python `os.replace` 跨平台原子 |
| Worktree 命名 | `team-<sanitized_team>/<member>`(嵌套 slug,`/` → `+`) | 复用 ch14 嵌套 slug 能力;不污染顶层 worktree 命名空间 |
| Member session_dir | 沿用 ch12 `<root>/.forgecode/sessions/<id>/` 格式 | 复用 `session.Writer`,无需新机制;Team 删除时一并清理 |
| Coordinator 开启检测 | `feature_has(cfg, "COORDINATOR_MODE") and env_truthy(env)` | README 明定双锁;一次决定不允许运行时改 |
| Coordinator 工具白名单 | 硬编码常量,启动时直接 `set_allowed_tools` | LLM 无法解锁,安全边界清晰 |
| Plan 审批本期形态 | 文本 Plan + Lead 用 `plan_approval_response` 回复 | 不强制结构化 Plan 类型,降低实现成本 |
| Fork 队员 | 受 `FORK_TEAMMATE` flag 控制,默认关 | README 明定;避免默认带满上下文 |
| 收敛 merge | 不提供专用工具,Lead 用 Bash 自主跑 git | README 明定;LLM 解冲突 = 语义理解,这是 LLM 优势 |
| `Agent` 工具的 `team_name` 在 in-process 队员处可见性 | 参数对模型可见,但调用时拦截抛错 | 与其在 schema 层动态裁剪不如统一 schema + 运行时校验,缓存友好 |
| 队员 Loop 邮箱注入 | 复用 `agent.Agent` 既有 system_reminders 通道,新增一种 reminder 来源 | 不改 Loop 主流程,改动最小 |
| TUI Coordinator 标签 | 状态栏静态渲染 | 视觉提示,运行时不可改 |
| 多 Team 并存 | `Manager.teams` dict 支持,但 spawn 时按 `team_name` 显式选 | 灵活;典型场景同一时刻一个活跃 Team |
| Team 删除时 Worktree 处理 | 调 `wt_mgr.remove(name, discard_changes=True)`,失败只警告 | 与 ch14 退出语义一致;`force=True` 才放行,无 force 时有活跃成员就拒删,有变更也保留(自动 cleanup 已处理) |
| 错误命名 | 自定义异常类 `TeamHasActiveMembersError` / `InProcessTeammateNoSpawnError` 等 | 调用方可 `except` 判别 |
| 并发模型 | `asyncio.Lock` 保护 Team / Manager 状态;mailbox 文件锁跨进程 | 与 Textual 的 asyncio event loop 天然契合;不引入 threading 池 |
| 子进程模型 | `python -m forgecode --team-member` + `asyncio.create_subprocess_exec` | 标准 Python 启动方式,跨平台 |