# Skill 技能包系统 Plan## 架构概览

新增一个 `forgecode.skills` 包承载所有 Skill 相关的"数据 + 加载 + 执行 + 激活态"逻辑，与现有 `forgecode.command`、`forgecode.tool`、`forgecode.prompt`、`forgecode.agent` 通过细窄接口交互。

按职责拆解：

- **forgecode.skills**：核心包。包含数据结构（`Skill`、`SkillMeta`、`ToolSpec`、`ActiveEntry`）、`SKILL.md` 解析、`tool.json` 解析、Catalog 三层路径扫描与覆盖、Skill 执行器（inline / fork 分支）、`ActiveSkills` 跨轮列表、`$ARGUMENTS` 渲染、`InstallSkill` zip 解压（zip-slip 防护），以及通过 `importlib.resources` 随包分发的三个内置 Skill 资源
- **forgecode.tool.load_skill**：新增 LoadSkill 工具实现。是系统工具，永远可见，受不带权限拦截
- **forgecode.tool.install_skill**：新增 InstallSkill 工具实现。普通工具，受权限模式约束
- **forgecode.tool.registry**：扩展—增加"系统工具"标记与 `filter_by_allowed(allowed: list[str])` 切片导出能力；增加"动态注册专属工具"入口（Skill 加载时把 `tool.json` 工具注册进来）
- **forgecode.command**：扩展—`register_skills_as_commands(reg, catalog, executor)` 把 Catalog 中每个 Skill 注册为 KindPrompt 命令；新增 `/skill` 命令（KindLocal，列出 Catalog）；删除 `handle_review` / `/review` 内置命令；UI 协议扩展 `list_catalog_skills / list_active_skills / clear_active_skills`
- **forgecode.prompt**：扩展—`optional_modules` 中现有的 "active-skills" 槽位重命名为 "skills-catalog"，承载第一阶段名字+描述列表；新增 `render_active_skills_block(entries) -> str` 函数供 env context 拼装
- **forgecode.agent**：扩展—`SessionRuntime` 新增 `active_skills: ActiveSkills` 字段；`Agent` 新增 `with_catalog` / `with_skill_executor` 配置项；`run()` 每轮重建 `sys` 时把 Catalog 列表传入 `build_system_prompt`、`env_text` 拼接时调用 `render_active_skills_block`；新增 `clear_active_skills() / activate_skill / list_active` 入口供 UI 与工具调用
- **forgecode.tui**：扩展—`App` 持有 catalog 引用与执行器；`handle_clear` 路径在 `clear_and_new_session` 后调 `active_skills.clear()`；UI 协议对应新增方法实现

## 核心数据结构### SkillMeta

```python
# forgecode/skills/types.py
from dataclasses import dataclass, field
from typing import Literal

@dataclass
class SkillMeta:
    name: str
    description: str
    allowed_tools: list[str] = field(default_factory=list)
    mode: Literal["inline", "fork"] = "inline"
    fork_context: Literal["none", "recent", "full"] = "none"
    model: str | None = None

    def is_fork(self) -> bool:
        return self.mode == "fork"
```

约定：`mode` 为空或 "inline" 视作 inline；`mode == "fork"` 视作 fork；其它值打 warning 后按 inline 处理。`fork_context` 仅 fork 时生效，缺省 "none"。

### Skill

```python
from enum import Enum
from pathlib import Path

class SkillSource(Enum):
    BUILTIN = "builtin"
    USER = "user"
    PROJECT = "project"

@dataclass
class Skill:
    meta: SkillMeta
    prompt_body: str           # SKILL.md 去 frontmatter 后的正文（启动时缓存，执行时重读覆盖）
    source_dir: Path           # 绝对路径，重读 SKILL.md / 解析 tool.json 时用
    source: SkillSource        # BUILTIN / USER / PROJECT
    tool_specs: list["ToolSpec"] = field(default_factory=list)
```

### ToolSpec

```python
@dataclass
class ToolSpec:
    name: str                    # 工具名（与 frontmatter allowed_tools 用名一致）
    description: str
    input_schema: dict           # 标准 function calling JSON Schema
    command: list[str]           # argv，首元素相对 source_dir 解析（或绝对路径）
    base_dir: Path               # 工作目录（exec 时的 cwd），固定为 source_dir
```

### Catalog

```python
import asyncio

class Catalog:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()       # 用 threading.RLock 亦可（启动期无并发，此处主要给 reload 用）
        self._by_name: dict[str, Skill] = {}
        self._order: list[str] = []       # 按 name 排序的稳定迭代序

    @classmethod
    def load(cls, work_dir: Path) -> "Catalog": ...
    def reload(self, work_dir: Path) -> None: ...
    def get(self, name: str) -> Skill | None: ...
    def list(self) -> list[Skill]: ...      # 按 order
    def names(self) -> list[str]: ...
    def validate_tools(self, reg: "ToolRegistry") -> list["ValidationIssue"]: ...
```

`Catalog.load` 按顺序扫描：
1. 通过 `importlib.resources.files("forgecode.skills.builtin")` 列出内置 Skill 目录并解析（`source=BUILTIN`）
2. `~/.forgecode/skills/*` 子目录（`source=USER`）
3. `<work_dir>/.forgecode/skills/*` 子目录（`source=PROJECT`）

后扫到的同名 `name` 覆盖前者。

### ActiveSkills

```python
import threading

@dataclass
class ActiveEntry:
    name: str
    body: str                    # 激活那一刻磁盘上的 SKILL.md 正文

class ActiveSkills:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: list[ActiveEntry] = []   # 保持激活顺序
        self._index: dict[str, int] = {}        # 重复激活的话覆盖原位置内容

    def activate(self, name: str, body: str) -> None: ...
    def clear(self) -> None: ...
    def snapshot(self) -> list[ActiveEntry]: ...  # 拷贝出当前列表（env 装配用）
    def names(self) -> list[str]: ...
```

### Executor

```python
class Executor:
    def __init__(
        self,
        catalog: Catalog,
        runtime: "SessionRuntime",
        registry: "ToolRegistry",
        provider: "Provider",
        eng: "PermissionEngine",
        version: str,
    ) -> None: ...

    # 入口：被 Slash 命令 handler 调用
    async def execute(
        self,
        ctx: "RunContext",
        ui: "UI",
        name: str,
        args: str,
    ) -> None: ...

    # inline 路径直接通过 ui.inject_and_send
    # fork 路径起子 Agent 跑完后通过 ui.append_assistant_message 写回主对话
```

## 模块设计### forgecode/skills/parser.py
**职责**：解析单个 Skill 目录 → `Skill`
**对外接口**：`def parse_skill_dir(dir_path: Path, source: SkillSource) -> Skill`
**依赖**：`pyyaml`（已在 pyproject 依赖中）

解析流程：
1. 读 `<dir>/SKILL.md`，分离 frontmatter（两行 `---` 之间）与 body
2. `yaml.safe_load(frontmatter)` → `SkillMeta`；校验 name 合法性、mode / fork_context 取值
3. 读 `<dir>/tool.json`（不存在则跳过）→ `list[ToolSpec]`，校验 command 数组非空、首元素可解析为路径
4. 组装 `Skill` 返回

### forgecode/skills/catalog.py
**职责**：三层路径扫描与覆盖管理
**对外接口**：`load / reload / get / list / names / validate_tools`
**依赖**：`forgecode.skills.parser`, `importlib.resources`

`importlib.resources`：
```python
from importlib.resources import files

def _iter_builtin_skill_dirs():
    base = files("forgecode.skills.builtin")
    for entry in base.iterdir():
        if entry.is_dir() and entry.joinpath("SKILL.md").is_file():
            yield entry
```

启动时把内置目录解压到一个临时位置或者直接以 traversable 抽象传给 parser；为统一处理（专属工具 exec 需要真实文件路径），首启时把内置 Skill 解压到 `$XDG_CACHE_HOME/forgecode/builtin-skills/`（或 `pathlib.Path(tempfile.gettempdir()) / "forgecode-builtin-skills"`）下，再走与文件系统目录一致的扫描逻辑。

`validate_tools`：遍历 Catalog 中所有 Skill 的 `meta.allowed_tools`，确认每个名字都能在传入的 `ToolRegistry` 里 `get` 到；记录所有不通过项返回。

### forgecode/skills/render.py
**职责**：把 Skill body 渲染为最终注入文本（inline 和 fork 路径都先经过这一层）
**对外接口**：`def render_body(skill: Skill, args: str) -> str`

逻辑：
- 替换所有 `$ARGUMENTS` 出现
- 若无占位符且 args 非空，在末尾追加 `\n\n## User Request\n\n<args>`
- 若 `allowed_tools` 非空，在 body 顶部插一段 ``This skill is designed to use only these tools: <list>. Prefer them over other tools when possible.\n\n---\n\n``

### forgecode/skills/executor.py
**职责**：inline / fork 分发与执行
**对外接口**：`Executor` 类（含 `execute(...)` async 方法）

inline 分支：
1. 从 Catalog 取 Skill
2. 从磁盘重读 `SKILL.md`（失败回退缓存）
3. `render_body`
4. `await ui.inject_and_send(display_label, body)` —— `display_label` 例如 `/<name>`

fork 分支：
1. 从 Catalog 取 Skill
2. 从磁盘重读 `SKILL.md`
3. `render_body`
4. 按 `fork_context` 构造初始 Conversation：
   - none：仅一条 user 消息（rendered_body）
   - recent：从主 conversation 拷最近 5 条原始消息，再追加 rendered_body
   - full：先用 `compact.summarize_for_fork(ctx, main_conv)`（基于 ch09 现成的摘要管道）产出摘要文本，作为一条 system 或 user 消息插入，再追加 rendered_body
5. 选 provider：默认主 provider；`skill.meta.model` 非空时调 `llm.new_provider(skill_model)` 重新构造
6. 构造子 Agent：复用 `agent.create(provider, registry, version, eng, runtime=fork_runtime)`，子 runtime 是独立 `new_session_runtime()`
7. 子 `await agent.run(...)` → 异步消费事件直到 done；累计 token 用量
8. 把累计 token 写回主 runtime 的 anchor（`usage += sub`）
9. 取子对话的最后一条 assistant 文本作为 final_text
10. `ui.append_assistant_message(final_text)`（新增 UI 方法）—— 主对话历史新增一条 assistant 消息

任一步骤出错（异常或 `asyncio.CancelledError`）：返回 `final_text = "[skill <name> failed: <reason>]"`，仍以 assistant 消息写入主对话。

### forgecode/skills/install.py
**职责**：InstallSkill 的核心逻辑——下载 zip、校验路径、解压到 `~/.forgecode/skills/`
**对外接口**：`async def install_from_url(source: str, catalog: Catalog, work_dir: Path) -> str`

流程：
1. 通过 `httpx.AsyncClient` 下载 source 到临时文件（限时 60s、限大小 50MB）
2. 用 `zipfile.ZipFile` 打开
3. 严格校验：所有路径必须以 `<top_dir>/` 起头、`<top_dir>` 满足 F3 命名、内部不含 `..`、不含绝对路径、不含符号链接（`ZipInfo.external_attr` 高位判定 symlink）
4. 解压到 `~/.forgecode/skills/<top_dir>/`
5. 调用 `catalog.reload(work_dir)` 触发热重载
6. 返回 `<top_dir>` 作为 skill_name

### forgecode/skills/builtin/*
**职责**：内置三个 Skill 的资源文件
**结构**：

```
forgecode/skills/builtin/
├── __init__.py             — 空文件，使 builtin 成为可被 importlib.resources 寻址的包
├── commit/SKILL.md
├── review/SKILL.md
└── test/SKILL.md
```

每个 SKILL.md 都是完整的目录型 Skill（本期三个 builtin 不需要 tool.json，因为只用现有工具）。

内容要点（详见 task.md 中的步骤）：
- commit: `mode=inline`, `allowed_tools=[bash, read_file, grep]`
- review: `mode=fork`, `fork_context=none`, `allowed_tools=[read_file, grep, glob, bash]`
- test: `mode=inline`, `allowed_tools=[bash, read_file, grep, glob]`

注：`pyproject.toml` 中需配 `[tool.hatch.build.targets.wheel.force-include]`（或 hatch 的 `include` 配置）确保 `**/SKILL.md` 资源随 wheel 打包。

### forgecode/tool/load_skill.py
**职责**：LoadSkill 工具实现
**对外接口**：实现 `Tool` 协议

```python
class LoadSkillTool:
    def __init__(self, catalog: Catalog, active: ActiveSkills, registry: ToolRegistry) -> None: ...

    # name / description / parameters / read_only / is_system / execute
```

`is_system` 返回 `True`——新加在 `Tool` Protocol（默认实现 `False`）。`execute` 流程：
1. 解析 `args["name"]`
2. `catalog.get(name)` → 不存在返回 `unknown skill: <name>`
3. 重读 `SKILL.md` 获取最新 body
4. `active.activate(name, body)`
5. 把 `skill.tool_specs` 注册进 `registry`（重复名静默覆盖，仅当前进程生效）
6. 返回 `Skill <name> activated. SOP pinned to env context. N specialized tools registered.`

### forgecode/tool/install_skill.py
**职责**：InstallSkill 工具实现
**对外接口**：实现 `Tool` 协议

```python
class InstallSkillTool:
    def __init__(self, catalog: Catalog, work_dir: Path) -> None: ...
```

`read_only` 返回 `False`（写盘 + 网络），`is_system` 返回 `False`。`execute` 直接 `await install_from_url(...)`，返回成功消息或错误。

### forgecode/tool/registry.py
**修改**：
- `Tool` Protocol 新增 `is_system: bool` 属性（默认 False）；现有 6 个工具与 MCP 工具默认实现返回 False
- LoadSkill 工具 `is_system` 返回 True
- 新增 `Registry.register_skill_tool(spec: ToolSpec)` 方法（动态注册专属工具）
- 新增 `Registry.system_definitions() -> list[ToolDefinition]`（仅返回系统工具）
- 新增 `Registry.definitions_filtered(allowed: list[str]) -> list[ToolDefinition]`（按白名单 + 系统工具豁免过滤）

注：本期不在主 agent loop 里用 `definitions_filtered` 改主对话工具集——按 spec F27 决议，inline 模式不真过滤。但 fork 模式子 Agent 用该方法构造工具集。

### forgecode/prompt/modules.py
**修改**：
- `optional_modules(instructions, memory)` 改为 `optional_modules(instructions, memory, skills_catalog)`
- 原 priority 90 槽位由 "active-skills" 重命名为 "skills-catalog"，内容由调用方传入
- 增加常量 `PRIO_SKILLS_CATALOG = 90`，删除 `PRIO_ACTIVE_SKILLS`

### forgecode/prompt/prompt.py
**修改**：
- `build_system_prompt(instructions, memory)` 改为 `build_system_prompt(instructions, memory, skills_catalog)`
- 增加 `render_active_skills_block(entries: list[ActiveSkillEntry]) -> str`，输出形如：
  ```
  ## Active Skills

  ### Skill: commit

  <body>

  ### Skill: review

  <body>
  ```
  entries 为空时返回空字符串
- 增加 `render_skills_catalog(items: list[SkillCatalogItem]) -> str`，输出 skills-catalog 模块内容；items 为空时返回空字符串

为避免 prompt 包反向依赖 skills 包，新增 dataclass 类型：
```python
@dataclass(frozen=True)
class SkillCatalogItem:
    name: str
    description: str

@dataclass(frozen=True)
class ActiveSkillEntry:
    name: str
    body: str
```

`skills.Catalog` 和 `skills.ActiveSkills` 提供两个适配方法 `to_prompt_items()` / `to_prompt_entries()` 把内部类型转换到 prompt 包的类型上。

### forgecode/agent/runtime.py
**修改**：
- `SessionRuntime` 新增字段 `active_skills: ActiveSkills`
- `new_session_runtime()` 初始化空 `ActiveSkills`
- `reset_for_new_session` 同时 `r.active_skills.clear()`

### forgecode/agent/agent.py
**修改**：
- 新增 `with_catalog(c: Catalog) -> AgentOption`：注入 catalog 引用（用于第一阶段列表与 clear_active_skills 入口）
- 新增 `Agent.activate_skill(name, body)` / `clear_active_skills()` 方法，转发到 `runtime.active_skills`
- `run()` 内每轮重建 sys 时：
  ```python
  sys = prompt.build_system_prompt(
      self._instruction_text,
      self._memory_text,
      prompt.render_skills_catalog(self._catalog.to_prompt_items()),
  )
  env_text = prompt.gather_environment(...).render() + "\n\n" + \
             prompt.render_active_skills_block(self._runtime.active_skills.to_prompt_entries())
  ```
  （`self._catalog` 为 None 时跳过；进度提示放在 sub-tasks）

### forgecode/command/registry.py + skills.py (新建)
**职责**：把 Catalog 注册为 KindPrompt 命令；新增 `/skill` 命令；UI 协议扩展
**对外接口**：
- `def register_skills_as_commands(reg: Registry, catalog: Catalog, exec: Executor) -> None`
- 提供给 reload 路径调用的 `def remove_skill_commands(reg: Registry) -> None`
- 新增内置 `/skill` 命令（KindLocal）

`reg.register` 时给每个 Skill 添加 `hidden=False` 的 Command；命令的 handler 闭包捕获 `skill.name` 与 `executor`，调用 `await exec.execute(ctx, ui, name, "")`（本期不支持参数；后续在 dispatcher 加参数后填）。

注：当前 ch10 的 Slash dispatch 是零参数，Skill 显式调用本期也走零参数。`$ARGUMENTS` 替换仅在 LoadSkill + 后续 user message 的隐式场景下被替换为空——这是合理的简化（参数交互通过 Skill 后续轮次的对话进行）。

为了支持 reload 时清理旧命令，Registry 新增 `remove_all(filter: Callable[[Command], bool])` 或 `remove_skill_commands()` 入口。

### forgecode/command/ui.py
**修改**：
- UI Protocol 新增方法：
  - `list_catalog_skills() -> list[SkillSummary]`（每条含 name/description/source/mode）
  - `list_active_skills() -> list[str]`
  - `clear_active_skills() -> None`
  - `append_assistant_message(text: str) -> None`（fork 路径用，把子 Agent 的 final_text 写入主对话历史）
- `NopUI` 提供零值实现

### forgecode/command/builtins.py
**修改**：
- 删除 `name="review"` 的注册块（让 Skill 接管）
- 修改 `handle_clear`：在调 `ui.clear_and_new_session()` 后追加 `ui.clear_active_skills()`
- 新增 `name="skill"`、kind=KindLocal、handler=`handle_skill` 的注册块

### forgecode/tui/*
**修改**：
- `App` 持有 `catalog: Catalog`、`executor: Executor`
- 实现新增的 UI 方法：`list_catalog_skills` / `list_active_skills` / `clear_active_skills` / `append_assistant_message`
- `tui.create_app` 接受新参数并接入

### src/forgecode/cli.py
**修改**：
- 启动时构造 `catalog: Catalog`、`active_skills: ActiveSkills` 并注入到 `SessionRuntime`
- 注册 LoadSkill / InstallSkill 内置工具
- 在工具注册完成后调 `catalog.validate_tools(registry)`；对每条 issue 打 warning 并把该 Skill 从 Catalog 中移除（保留其它）
- 调 `command.register_skills_as_commands` 完成自动注册
- 把 catalog/executor 传给 tui

## 模块交互### 启动期

```
cli.main:
  ├─ tool.create_default_registry()
  ├─ mcp.attach_servers(registry)              # 已有
  ├─ skills.Catalog.load(work_dir)             # 三层路径扫描
  ├─ registry.register(LoadSkillTool(...))     # 系统工具
  ├─ registry.register(InstallSkillTool(...))
  ├─ catalog.validate_tools(registry)          # fail-fast 检查
  │     不通过项 → 打 warning + 从 catalog 移除
  ├─ skills.Executor(catalog, registry, ...)
  ├─ command.register_builtins(cmd_reg)        # ch10 11 条（review 已删）
  ├─ command.register_skills_as_commands(cmd_reg, catalog, executor)
  ├─ command.register_skill_cmd(cmd_reg)       # /skill (新)
  └─ tui.create_app(... catalog, executor, ...)
```

### Skill 显式调用（/commit）

```
user → submit → command.dispatch("/commit")
       → handler 调 await executor.execute(ctx, ui, "commit", "")
                 ├ inline: render → ui.inject_and_send → agent.run 注入主对话
                 └ fork: render → 子 Agent.run → final_text → ui.append_assistant_message
```

### Skill 意图触发（自然语言）

```
user 输入"帮我提交一下" → agent.run loop
   └ stream_once 拿到 LLM 调 LoadSkill({"name":"commit"})
        → registry.execute → LoadSkillTool.execute
              ├ catalog.get → 重读 SKILL.md
              ├ active.activate("commit", body)
              └ 返回 tool_result
   下一轮迭代:
        sys = build_system_prompt(... catalog 清单不变)
        env_text = ... + render_active_skills_block([("commit", body)])
        ↑ Agent 现在看得到完整 SOP
```

### /clear

```
/clear handler → ui.clear_and_new_session() (ch10) → ui.clear_active_skills()
                                                          └ runtime.active_skills.clear()
下轮 env_text 中 active-skills 块为空字符串
```

### Reload（InstallSkill 后或者未来 /skill reload）

```
InstallSkillTool.execute → await skills.install_from_url(...)
   └ 解压完毕 → catalog.reload(work_dir)
                ├ 重新扫描三层路径
                ├ 通过 lock 原子替换 _by_name / _order
                └ command 端不会立刻感知—但 dispatcher 每轮按命令名查找 reg，
                   reload 完成后下次 /<name> 即可命中新 Skill。然而启动时已注册的
                   旧命令仍在 registry 中。为简化，提供下面策略：
```

进一步：`catalog.reload` 返回 `(added, removed)`，InstallSkill 工具拿到结果后调 `cmd_reg.remove_skill_commands` + `register_skills_as_commands`，确保 `/help` 和补全菜单立即同步。

### Fork 模式

```
executor.execute (fork) →
   ┌──────────────────── 子 Agent ────────────────────┐
   │ 新 Conversation 按 fork_context 初始化            │
   │ agent.create(provider, registry, version, eng,    │
   │              runtime=fork_runtime)                │
   │ await agent.run(ctx, conv, default_mode)          │
   │ 累计 token, 取末尾 assistant text                  │
   └───────────────────────────────────────────────────┘
   将 final_text 作为一条 assistant 消息插入主 conv
```

注：fork 模式下子 Agent 的 registry 是用 `Registry.definitions_filtered(allowed)` 构造的临时视图（共享底层 `Tool` 实例），系统工具豁免列入。

## 文件组织

```
forgecode/
├── pyproject.toml                    # 接线：dependencies 增 httpx；hatch include SKILL.md 资源
├── src/forgecode/
│   ├── cli.py                        # 启动期接线
│   ├── skills/                       # 新包
│   │   ├── __init__.py               # 对外导出 Catalog / ActiveSkills / Executor / SkillSource ...
│   │   ├── types.py                  # SkillMeta / Skill / SkillSource / ToolSpec / ActiveEntry
│   │   ├── parser.py                 # parse_skill_dir, parse_frontmatter_and_body, parse_tool_json
│   │   ├── catalog.py                # Catalog: load / reload / get / list / names / validate_tools
│   │   ├── active.py                 # ActiveSkills
│   │   ├── render.py                 # render_body, $ARGUMENTS 替换, allowed_tools 顶部提示
│   │   ├── executor.py               # Executor.execute (inline / fork)
│   │   ├── install.py                # install_from_url（zip 下载与 zip-slip 防护）
│   │   ├── adapter.py                # to_prompt_items / to_prompt_entries 桥接到 prompt 包
│   │   └── builtin/                  # importlib.resources 资源
│   │       ├── __init__.py
│   │       ├── commit/SKILL.md
│   │       ├── review/SKILL.md
│   │       └── test/SKILL.md
│   ├── tool/
│   │   ├── registry.py               # 修改：is_system 标记 + definitions_filtered + register_skill_tool
│   │   ├── load_skill.py             # 新：LoadSkill 工具
│   │   ├── install_skill.py          # 新：InstallSkill 工具
│   │   └── skill_tool.py             # 新：把 ToolSpec 适配为 Tool 实现（asyncio.subprocess exec）
│   ├── command/
│   │   ├── builtins.py               # 修改：删 /review、改 handle_clear、加 /skill
│   │   ├── builtin_skill.py          # 新：handle_skill (KindLocal 列表)
│   │   ├── skills.py                 # 新：register_skills_as_commands / remove_skill_commands
│   │   └── ui.py                     # 修改：新增 4 个 UI 方法 + NopUI 兜底
│   ├── prompt/
│   │   ├── modules.py                # 修改：active-skills → skills-catalog
│   │   ├── prompt.py                 # 修改：build_system_prompt 增 catalog 参数
│   │   ├── skills_block.py           # 新：render_active_skills_block / render_skills_catalog / 类型
│   │   └── environment.py            # 不动
│   ├── agent/
│   │   ├── runtime.py                # 修改：SessionRuntime.active_skills 字段
│   │   ├── agent.py                  # 修改：with_catalog / run 内构造 sys 与 env 拼接
│   │   └── ...
│   └── tui/
│       ├── app.py                    # 修改：持有 catalog/executor + 实现新 UI 方法
│       └── ...
├── tests/
│   ├── test_skills_parser.py
│   ├── test_skills_catalog.py
│   ├── test_skills_render.py
│   ├── test_skills_install.py
│   ├── test_prompt_skills.py
│   └── test_command_skill.py
└── docs/python/ch11/
    ├── spec.md
    ├── plan.md
    ├── task.md
    └── checklist.md
```

## 技术决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 数据格式 | 仅 SKILL.md（frontmatter+body） | 与 README 一致；解析路径单一；不引入 yaml/md 分离的认知负担 |
| Skill 形态 | 必须是目录 | 与 tool.json/references 自然契合；将来扩展空间大 |
| 优先级覆盖 | 内置 < 用户 < 项目 | 与 npm/git 习惯一致 |
| 内置 Skill 分发 | `importlib.resources` 随 wheel 走 | 与包一起分发；新机器装 forgecode 即附带，不依赖外部文件 |
| 内置 Skill 落地 | 启动期解压到 cache 目录后按文件系统统一处理 | tool.json + references/ 需要真实路径才能 exec 脚本 |
| 第一阶段注入位置 | system prompt 模块（priority 90） | 享受 prompt cache 稳定前缀 |
| 第二阶段注入位置 | env context（每轮重建） | 多 Skill 同激活、嵌套场景下 SOP 永远靠前；prompt cache 失效是设计意图 |
| LoadSkill 入参 | 仅 name | 与"意图识别"语义一致；参数走后续 user message 更自然 |
| LoadSkill 权限 | read-only + 系统工具 | 没有外部副作用；为支持嵌套必须豁免 allowed_tools |
| InstallSkill 权限 | 普通工具，受权限模式约束 | 写盘+网络，必须走授权 |
| fork 模式实现 | Python 端起子 Agent（同进程 asyncio task） | 直接复用现成 `agent.run`，不依赖将来 SubAgent 章节 |
| fork_context 默认 | none | "隔离"才是 fork 本意；需要带上下文的显式声明 |
| allowed_tools 在 inline 模式 | 仅 fail-fast + SOP 提示 | 避免 inline 期间动态切换工具集的生命周期复杂度；安全靠 ch08 权限引擎兜底 |
| Skill 与已有命令冲突 | 跳过加载 + warning | 保护内置命令的可靠性；Skill 想替换内置命令需要用户主动改源码 |
| 解析失败 | 跳过单个 Skill，warning，不阻断 | 与 instructions loader 一致的容错策略 |
| 热加载 | InstallSkill 后主动 reload；execute 时重读 body | 用户改 SKILL.md 下次执行立即生效；新装 Skill 不需要重启 |
| Skill 列表数据流 | adapter 桥接，prompt 包不依赖 skills 包 | 避免循环依赖 |
| UI 接口扩展 | 4 个新方法 + NopUI 全量实现 | 与 ch10 风格一致 |
| 闭包循环变量 | 用 `functools.partial(handler, name=skill.name)` 或显式默认参数 `def f(ctx, ui, _name=skill.name)` | Python 闭包按引用绑定，循环里必须显式拷贝 |
| zip 下载 | `httpx.AsyncClient` | 已有 async stack；流式读取易做 `LimitReader` 限大小 |
| 子进程 exec | `asyncio.create_subprocess_exec` + `asyncio.wait_for(..., timeout=30)` | 不阻塞 event loop；与 ch05 bash 工具实现一致 |
| Skill 自身参数 | 本期 /<name> 仅零参数；后续轮次对话补 | 与 ch10 F7 一致，不破坏 dispatcher |