# Worktree 隔离 Plan## 架构概览

新建 `src/forgecode/worktree/` 子包,集中放 Manager、Worktree、WorktreeSession、Slug 校验、创建后设置、自动清理、过期清理。其余包按以下方式接入:

- **`forgecode.tool`**:新增 `ctx.py`(with_cwd / cwd_from_ctx / resolve_path);改造 6 个核心工具用 resolve_path
- **`forgecode.subagent`**:`Definition` 加 `isolation` 字段,`parser.py` 解析 `isolation:` frontmatter
- **`forgecode.agent`**:`AgentTool.execute` 加 `_execute_with_worktree` 分支,启动时通过 ctx 注入 cwd
- **`forgecode.command`**:新增 `builtin_worktree.py`,提供 `/worktree` 一级命令与子命令(create/list/enter/exit/remove)
- **`forgecode.tui`**:在 App 字段加 `worktree_mgr: worktree.Manager`、`active_cwd: str`;主 Agent 每次 Run 前用 `with_cwd(active_cwd)` 包住
- **`src/forgecode/__main__.py` / `cli.py`**:`Manager(root)` 落在 `subagent_catalog = load_subagent_catalog(root)` 之后;失败降级为 None(可选);把 Manager 传给 `forgecodeApp` 和 `AgentTool`
- **`.gitignore`**:追加 `.forgecode/worktrees/` 与 `.forgecode/worktree_session.json`

## 核心数据结构### worktree.Worktree

```python
from dataclasses import dataclass
from datetime import datetime

@dataclass
class Worktree:
    name: str                # 原始 slug(可能含 /)
    path: str                # 绝对路径
    branch: str              # worktree-<flat_slug>
    based_on: str            # 创建时的 base 引用(HEAD / SHA)
    head_commit: str         # 创建时的 commit SHA
    created: datetime
    manual: bool             # True=用户手动创建(/worktree create 路径)
```

### worktree.WorktreeSession

```python
from dataclasses import dataclass, asdict
import json

@dataclass
class WorktreeSession:
    original_cwd: str
    worktree_path: str
    worktree_name: str
    original_branch: str
    original_head_commit: str
    session_id: str
    hook_based: bool = False

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, raw: str) -> "WorktreeSession":
        return cls(**json.loads(raw))
```

### worktree.Manager

```python
import asyncio
from pathlib import Path

class Manager:
    def __init__(self, repo_root: str) -> None: ...
    # repo_root: 绝对路径
    # worktree_dir: <repo_root>/.forgecode/worktrees
    # session_file: <repo_root>/.forgecode/worktree_session.json
    # symlink_dirs: 默认 ["node_modules", ".venv", "vendor"]
    # lock: asyncio.Lock
    # active: dict[str, Worktree]
    # current_session: WorktreeSession | None

    async def create(self, name: str, base_ref: str, manual: bool) -> Worktree: ...
    async def enter(self, name: str) -> WorktreeSession: ...
    async def exit(self, name: str, action: "ExitAction", opts: "ExitOptions") -> "ExitReport": ...
    async def remove(self, name: str, opts: "ExitOptions") -> None: ...
    async def auto_cleanup(self, name: str) -> "AutoCleanupReport": ...
    async def sweep_stale(self, cutoff: "datetime") -> list[str]: ...
    def list(self) -> list[Worktree]: ...
    def get(self, name: str) -> Worktree | None: ...
    def current_session(self) -> WorktreeSession | None: ...
```

### worktree 辅助类型

```python
from enum import Enum

class ExitAction(str, Enum):
    KEEP = "keep"
    REMOVE = "remove"

@dataclass
class ExitOptions:
    discard_changes: bool = False

@dataclass
class ExitReport:
    removed: bool
    path: str
    branch: str

@dataclass
class AutoCleanupReport:
    kept: bool
    path: str = ""
    branch: str = ""

class WorktreeHasChangesError(Exception):
    """Worktree 有未提交修改或本地多于 base 的 commit。"""
```

### tool ctx 帮助函数

```python
# src/forgecode/tool/ctx.py
import contextvars
from contextlib import contextmanager
from pathlib import Path

_ctx_cwd: contextvars.ContextVar[str | None] = contextvars.ContextVar("cwd", default=None)

@contextmanager
def with_cwd(directory: str):
    if not directory:
        yield
        return
    token = _ctx_cwd.set(directory)
    try:
        yield
    finally:
        _ctx_cwd.reset(token)

def cwd_from_ctx() -> str | None:
    return _ctx_cwd.get()

def resolve_path(p: str) -> str:
    base = _ctx_cwd.get() or str(Path.cwd())
    if not p:
        return base
    pp = Path(p)
    if pp.is_absolute():
        return str(pp)
    return str(Path(base) / pp)
```

### subagent.Definition 扩展

```python
@dataclass
class Definition:
    # ... 既有字段 ...
    isolation: str = ""  # "" 或 "worktree"
```

## 模块设计### `forgecode.worktree`(新子包)**职责:** Worktree 完整生命周期管理 + Slug 校验 + 后台清理。
**对外接口:** Manager(含上面所列方法)+ validate_slug + WorktreeHasChangesError 等导出常量/类型。
**依赖:** 标准库 + `asyncio.create_subprocess_exec` 调 git。
**关键内部函数:**
- `validate_slug(name: str) -> None` (失败抛 ValueError)
- `flat_slug(name: str) -> str` (`/` → `+`)
- `_perform_post_creation_setup(repo_root, wt_path, symlink_dirs)`
- `_has_worktree_changes(wt_path, base_commit) -> bool` (fail-closed)
- `_resolve_head_sha_from_fs(wt_path) -> str | None` (快速恢复)
- `_read_worktree_include(repo_root) -> list[str]`
- `_list_ignored_files(repo_root) -> list[str]`
- `_run_git(work_dir, *args) -> str` (统一 env: `GIT_TERMINAL_PROMPT=0`, `GIT_ASKPASS=""`,stdin 关闭)
- `random_agent_name() -> str` (用于 SubAgent 临时 worktree 名)

**文件:**
- `__init__.py` — 公开导出 Manager / validate_slug / WorktreeHasChangesError 等
- `manager.py` — Manager 类型 + 主要方法骨架
- `create.py` — Create + 快速恢复 + 创建后设置
- `lifecycle.py` — enter / exit / remove / auto_cleanup
- `sweep.py` — sweep_stale
- `slug.py` — validate_slug + flat_slug
- `session.py` — WorktreeSession + 持久化(JSON 原子写)
- `git.py` — `_run_git` helper、`_resolve_head_sha_from_fs`、`_has_worktree_changes`
- 测试统一在 `tests/test_worktree_*.py`

### `forgecode.tool` 改造**职责:** 增加 ctx cwd 传递机制,改造 6 个工具用 resolve_path / 子进程 cwd 参数。
**对外接口:** with_cwd / cwd_from_ctx / resolve_path(新增);6 个工具 execute 行为变更但 schema 不变。
**依赖:** 无新增。

**文件改动:**
- `ctx.py` — 新增
- `read_file.py` / `write_file.py` / `edit_file.py` — 在 `Path(...).stat()` / `read_text` / `write_text` 前用 `resolve_path(args.path)`
- `glob.py` — root 解析改 `resolve_path`
- `grep.py` — 同 glob
- `bash.py` — `asyncio.create_subprocess_exec(..., cwd=resolve_path(""))` (即 cwd 本身,空字符串解析为 cwd)

### `forgecode.subagent` 改造**职责:** Definition 加 isolation 字段;parser 解析。
**改动:**
- `parser.py` — frontmatter 字典中读 `isolation` 字段,合法值 `""` / `"worktree"`,其他值 stderr 警告回落空
- `definition.py` — `Definition` 加 `isolation: str = ""`

### `forgecode.agent` 改造**职责:** AgentTool 增加 worktree 分支,接受 Manager。
**改动:**
- `agent_tool.py`:
  - `AgentTool` 加属性 `worktree_mgr: worktree.Manager | None`
  - `AgentTool.__init__(..., worktree_mgr=None)`(签名末尾追加)
  - `execute` 内 `definition.isolation == "worktree"` 时走 `self._execute_with_worktree(...)`
- 新增 `agent_worktree.py`:
  - `_execute_with_worktree(definition, sub_agent, sub_conv, prompt, events) -> str`(async)
  - `build_worktree_notice(parent_cwd: str, wt_path: str) -> str`
  - 直接 `from forgecode.worktree import random_agent_name`(worktree 包不依赖 agent,无导入循环)

### `forgecode.command` 新增**职责:** `/worktree` 一级命令 + 子命令解析。
**改动:**
- `builtins.py` 增加 `registry.register(Command(name="worktree", ...))`
- 新增 `builtin_worktree.py`(handler 内自己 split 子命令 + 参数)
- `ui.py` 加 UI 协议方法 `worktree_accessor() -> WorktreeAccessor | None`(返回一个轻量协议,屏蔽 worktree 包反向依赖)

**UI 接口扩展:**

```python
# forgecode/command/ui.py
from typing import Protocol
from dataclasses import dataclass

@dataclass
class WorktreeSummary:
    name: str
    path: str
    branch: str
    active: bool
    manual: bool

class WorktreeAccessor(Protocol):
    async def create(self, name: str) -> tuple[str, str]: ...   # (path, branch)
    def list(self) -> list[WorktreeSummary]: ...
    async def enter(self, name: str) -> None: ...
    async def exit(self, action: str, discard: bool) -> bool: ...  # removed
    async def remove(self, name: str, discard: bool) -> None: ...

class UI(Protocol):
    # ... 既有方法 ...
    def worktree_accessor(self) -> WorktreeAccessor | None: ...
```

### `forgecode.tui` 改造**职责:** 持有 Manager 引用,把 active_cwd 注入主 Agent ctx。
**改动:**
- `app.py` `forgecodeApp` 加属性 `worktree_mgr: worktree.Manager | None`、`active_cwd: str = ""`(空表示进程 cwd)
- `forgecodeApp.__init__` 接收 `worktree_mgr`(或通过依赖注入)
- 在 App 的 run_once / submit 入口前,用 `with with_cwd(self._effective_cwd()):` 包住主 Agent Run 调用
- `_effective_cwd()` 返回 `self.active_cwd` 或 `str(Path.cwd())`
- 实现 `worktree_accessor()` 方法,返回一个适配 worktree.Manager 的实例
- 启动时(`forgecodeApp.__init__` 内)若 Manager 的 `current_session()` 非 None,把 `self.active_cwd = session.worktree_path`

### `src/forgecode/cli.py` / `__main__.py` 改造

```python
# 紧跟 subagent_catalog = load_subagent_catalog(root) 之后
try:
    worktree_mgr = worktree.Manager(root)
except Exception as exc:
    print(f"Worktree 管理器降级: {exc}", file=sys.stderr)
    worktree_mgr = None
else:
    # 后台跑过期清理,不阻塞启动
    asyncio.get_event_loop().create_task(
        worktree_mgr.sweep_stale(datetime.now() - timedelta(hours=24))
    )

agent_tool = AgentTool(
    catalog=subagent_catalog,
    task_mgr=task_mgr,
    parent=None,
    bg_enabled=cfg.enable_subagent_background,
    worktree_mgr=worktree_mgr,
)

app = forgecodeApp(
    # ... 既有参数 ...
    worktree_mgr=worktree_mgr,
)
```

## 模块交互**SubAgent + Worktree 启动链路:**

```
主 Agent 调 Agent 工具
  ↓
AgentTool.execute
  ↓
definition.isolation == "worktree"?
  ↓ yes
_execute_with_worktree:
  1. name = "agent-a" + random_hex(7)
  2. wt = await worktree_mgr.create(name, "HEAD", manual=False)
  3. notice = build_worktree_notice(parent_cwd, wt.path)
  4. task_text = notice + "\n\n" + prompt
  5. with with_cwd(wt.path):
  6.     final_text = await sub_agent.run_to_completion(sub_conv, task_text, events)
  7. report = await worktree_mgr.auto_cleanup(name)
  8. if report.kept: final_text += f"\n[Worktree 保留: {report.path}]"
  9. return final_text
```

**工具调用的 cwd 解析链路:**

```
模型调 read_file(path="server.py")
  ↓
agent.execute → registry.execute("read_file", args)
  ↓
read_file_tool.execute(args)
  ↓
abs = tool.resolve_path("server.py")
  ↓
ContextVar cwd 非空 → abs = cwd + "/server.py"
ContextVar cwd 为空 → abs = 进程 cwd + "/server.py"
  ↓
Path(abs).read_text()
```

**TUI 主 Agent Run 入口:**

```
async def run_once(self):
    cwd = self.active_cwd or str(Path.cwd())
    with with_cwd(cwd):
        events = self.agent.run(self.conv, mode)
        async for evt in events:
            ...
```

## 文件组织

```
src/forgecode/worktree/                — 新子包
├── __init__.py                       — 导出 Manager / validate_slug / 错误类型
├── manager.py                        — Manager 类型 + 构造
├── create.py                         — create + 快速恢复 + post-creation setup
├── lifecycle.py                      — enter / exit / remove / auto_cleanup
├── sweep.py                          — sweep_stale
├── slug.py                           — validate_slug + flat_slug
├── session.py                        — WorktreeSession + JSON 持久化
└── git.py                            — _run_git / _has_worktree_changes / _resolve_head_sha_from_fs

src/forgecode/tool/
├── ctx.py                            — 新增 with_cwd/cwd_from_ctx/resolve_path
├── bash.py                           — 改造:子进程 cwd=resolve_path("")
├── read_file.py                      — 改造:用 resolve_path
├── write_file.py                     — 改造:用 resolve_path
├── edit_file.py                      — 改造:用 resolve_path
├── glob.py                           — 改造:用 resolve_path
└── grep.py                           — 改造:用 resolve_path

src/forgecode/subagent/
├── definition.py                     — 加 isolation 字段
└── parser.py                         — 解析 isolation:

src/forgecode/agent/
├── agent_tool.py                     — execute 加 isolation 分支
└── agent_worktree.py                 — 新增:_execute_with_worktree + notice 构造

src/forgecode/command/
├── builtin_worktree.py               — 新增:/worktree handler
├── builtins.py                       — 增加 registry.register
└── ui.py                             — 加 WorktreeAccessor 协议

src/forgecode/tui/
├── app.py                            — 加 worktree_mgr / active_cwd / cwd 注入
└── worktree_adapter.py               — 实现 WorktreeAccessor(适配 worktree.Manager)

tests/
├── test_worktree_slug.py
├── test_worktree_manager.py
├── test_worktree_create.py
├── test_worktree_lifecycle.py
├── test_worktree_sweep.py
├── test_worktree_git.py
├── test_tool_ctx.py
├── test_subagent_parser.py           — 新增 isolation case
└── test_agent_worktree.py

src/forgecode/cli.py / __main__.py      — 接入

.gitignore                            — 追加两行
```

## 技术决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| cwd 传递方式 | `contextvars.ContextVar` + with_cwd 上下文管理器 | 已有 ContextVar 范式承载 conv / subagent_depth,Tool schema 不变,prompt cache 不抖动 |
| Worktree 目录位置 | `.forgecode/worktrees/<flat_slug>/` | README 既定方案;仓库内 + .gitignore 不追踪 |
| 嵌套 slug `/` 处理 | 替换为 `+`(flat_slug)做文件系统/分支名 | Git 分支的 `/` 是命名空间分隔符,会导致 `worktree-team/alice` 与 `worktree-team` 的 D/F 冲突 |
| Manager 构造失败处理 | 抛异常,forgecode 降级 worktree_mgr=None | 不阻塞 forgecode 启动;后续 isolation:worktree 调用回错误信息 |
| 快速恢复 | 纯 fs read,不调 git | README 说明大仓库 git fetch 6-8s,fs read 3ms;场景:同一 SubAgent 反复进同 worktree |
| 创建后设置失败处理 | 仅 stderr 警告 | 都是 best-effort,失败 ≠ 不可用 |
| `-B` vs `-b` | `-B`(重置) | 上次残留的孤儿分支不会让 create 失败 |
| `await asyncio.sleep(0.1)` 在 remove | 保留 | README 指出 git lockfile 竞态;100ms 是经验值 |
| os.chdir 使用场景 | 仅 Manager.exit 兜底一次 | 其他全部 explicit cwd;避免进程级 cwd 成为同步点 |
| 后台清理触发时机 | forgecode 启动时跑一次,asyncio.create_task 后台执行 | 不阻塞主流程;ch11 已有 session.clean_expired 同样做法 |
| `.worktreeinclude` 缺失行为 | 跳过 D 步骤,不报错 | 大多数项目没这文件 |
| `subagent.isolation` 默认值 | `""`(无隔离) | 不破坏 ch13 既有定义文件 |
| 临时 worktree 命名 | `agent-a<7hex>` | README 既定;sweep_stale 正则匹配 |
| Manager 用 asyncio.Lock 而非 threading.Lock | 整个项目跑在 asyncio 事件循环上,异步友好 | 子进程调用都是 await,避免线程锁阻塞事件循环 |
| `WorktreeAccessor` 协议在 command 包 | 隔离 worktree 包反向依赖 | command 包不应该导入 worktree(已经导入 permission + llm,加 worktree 是技术债) |
| TUI active_cwd 字段 | 字符串,空 = 进程 cwd | 既有 `self.cwd` 已是字符串字段,与之并存避免改 schema |
| `--resume` 与 worktree session | Manager.__init__ 内统一处理 | 启动时自动读 session,session 失效自动清空 |
| Linux/macOS 跨平台 | symlink 用 os.symlink | 跨 POSIX 平台一致;Windows 失败时 best-effort 跳过 |
| git 子进程调用 | `asyncio.create_subprocess_exec` | 不阻塞事件循环;统一注入 env 与 stdin=DEVNULL |
| 子 Agent 临时名随机源 | `secrets.token_hex(4)[:7]` | 标准库,加密强随机,7 位 hex 与正则一致 |