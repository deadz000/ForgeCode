# slash命令体系 Plan## 架构概览

```
┌──────────────────────────────────────────────────────────┐
│                  src/forgecode/tui                         │
│                                                          │
│  App.on_submit() ─┬─► command.parse → command.Registry   │
│                   │       (lookup by name/alias)         │
│                   │             │                        │
│                   │             ▼                        │
│                   │      command.Handler(ui)             │
│                   │             │                        │
│                   │             ▼ via UI Protocol        │
│                   │      App 属性桥接 (impl UI)          │
│                   │                                      │
│                   └─► (非 / 开头) conv.add_user + begin_turn│
│                                                          │
│  on_key (idle) ─► CompletionMenu 状态机 ─► render        │
└──────────────────────────────────────────────────────────┘
                  ▲
                  │ 依赖
                  │
┌──────────────────────────────────────────────────────────┐
│            src/forgecode/command  (新包)                   │
│                                                          │
│  Command/Kind/Handler 类型定义                           │
│  Registry: 注册 + 冲突检测 + 前缀匹配 + 字典序排序       │
│  UI Protocol: handler 操作 TUI 的唯一通道                │
│  parse: 解析 /<name> 形态                                │
│  12 条内置命令的 handler 实现 (按 Kind 分文件)            │
└──────────────────────────────────────────────────────────┘
```

- 新建包 `src/forgecode/command/`：纯领域逻辑,不依赖 textual
- 既有包 `src/forgecode/tui/`：删掉 `commands.py` 里的旧注册表与 5 个旧 handler;改为构造 Registry、实现 UI Protocol、把分发结果桥接回 App
- 自动补全菜单是 TUI 层独有的 UX 元素,完全在 `src/forgecode/tui/complete.py` 中实现,只读 Registry 拿候选列表

## 核心数据结构### `command.Kind`

```python
from enum import Enum

class Kind(Enum):
    LOCAL = "local"     # 纯本地: 只打印, 不改 App, 不进 history
    UI = "ui"           # 影响界面: 改 App 状态, 不进 history
    PROMPT = "prompt"   # 提示词: 注入 user 消息 + 触发回合, 进 history
```

### `command.Command`

```python
from dataclasses import dataclass, field
from typing import Awaitable, Callable

Handler = Callable[["UI"], Awaitable[None]]

@dataclass(slots=True)
class Command:
    name: str                                # 不带 "/" 前缀, 全小写, 唯一
    description: str                         # 一句话, 用于 /help 与补全菜单
    kind: Kind
    handler: Handler
    aliases: list[str] = field(default_factory=list)  # 不带 "/" 前缀, 全小写, 全局唯一(含 name)
    hidden: bool = False                     # /help 与补全菜单都不显示, 但 dispatcher 仍可命中
```

### `command.Registry`

```python
class Registry:
    def __init__(self) -> None:
        self._by_name: dict[str, Command] = {}   # 主名 + 别名都映射到同一 Command, key 已转小写
        self._visible: list[Command] = []        # 按 name 字典序, 排除 hidden

    def register(self, cmd: Command) -> None:   # 名/别名冲突即 raise RuntimeError
    def lookup(self, name: str) -> Command | None:   # name 已是小写
    def visible(self) -> list[Command]:               # 返回已排序的可见命令副本
    def prefix_match(self, prefix: str) -> list[Command]:  # prefix 含 "/", 内部 strip 并小写; 前缀匹配 name; 不匹配别名/描述
```

### `command.UI` Protocol

handler 通过该协议操作 TUI;`ForgeCodeApp` 实现此协议。

```python
from typing import Protocol
from forgecode.permission import Mode

class UI(Protocol):
    # 输出 (通过 RichLog.write 推 scrollback)
    def println(self, msg: str) -> None: ...
    def error(self, msg: str) -> None: ...

    # 模式
    def mode(self) -> Mode: ...
    def set_mode(self, m: Mode) -> None: ...

    # 对话注入 (KindPrompt 命令使用)
    # display_label 在 scrollback 中显示, preset_prompt 是实际写入 conversation/JSONL 的文本
    def inject_and_send(self, display_label: str, preset_prompt: str) -> None: ...

    # /status 与 /memory 等只读查询
    def usage_in(self) -> int: ...
    def usage_out(self) -> int: ...
    def model_name(self) -> str: ...
    def cwd(self) -> str: ...
    def tool_count(self) -> int: ...
    def memory_files(self) -> list[str]: ...
    def session_path(self) -> str: ...
    def session_id(self) -> str: ...

    # 影响界面动作
    def quit(self) -> None: ...
    def force_compact(self) -> None: ...
    def open_resume_menu(self) -> None: ...
    def clear_and_new_session(self) -> None: ...

    # 状态机查询
    def idle(self) -> bool: ...
```

### UI 实现的降级合约

- `dispatch_slash` 仅在 `SessionState.IDLE` 下被调用
- 即便如此,UI 实现需对 None 做防御:
  - `self.provider is None` → `model_name()` 返回 `""`
  - `self.agent is None` → `force_compact()` 用 `error("agent 未就绪")` 兜底
  - `self.writer is None` → `session_path()` / `session_id()` 返回空串
  - `self.mem_mgr is None` → `memory_files()` 返回 `[]`

### `tui.CompletionMenu` (新)

```python
from dataclasses import dataclass, field

@dataclass(slots=True)
class CompletionMenu:
    items: list[Command] = field(default_factory=list)   # 当前候选, 已按 name 字典序
    cursor: int = 0                                       # 当前高亮索引
    offset: int = 0                                       # 滚动偏移 (候选数 > MAX_ROWS 时)
    active: bool = False                                  # 是否激活

MAX_ROWS = 8

def update(self, input_text: str, reg: Registry) -> None:  # 根据当前输入刷新候选; 无 "/" 前缀则 deactivate
def move_up(self) -> None: ...
def move_down(self) -> None: ...
def selected(self) -> Command | None: ...
def hide(self) -> None: ...
def render(self, width: int) -> str: ...                  # 多行字符串, 已按 MAX_ROWS 截断 + 滚动
```

**边界规则**:
- `App._handle_completion_key` 在 TextArea 内容含 `\n` 时强制 `active=False` (避免多行粘贴误激活)
- `selected() is None` 时(零匹配),回车走未命中提示分支、Tab/ESC 仅关闭菜单

## 模块设计### `src/forgecode/command/__init__.py`
**职责**：包出口,re-export `Kind` / `Command` / `Handler` / `Registry` / `UI` / `parse` / `register_builtins`。

### `src/forgecode/command/command.py`
**职责**：定义 `Kind`、`Command`、`Handler` 类型别名。
**对外接口**：上面列出的类型。
**依赖**：仅标准库 `dataclasses`、`enum`、`typing`。

### `src/forgecode/command/registry.py`
**职责**：注册中心。维护 `_by_name` 字典、`_visible` 排序列表；`register` 时做冲突检测;`prefix_match` 提供补全数据源。
**对外接口**：上面 `Registry` 的方法集。
**依赖**：仅 `command.py` + 标准库。

### `src/forgecode/command/dispatch.py`
**职责**：`parse(input_text: str) -> tuple[str, bool]` —— 空白/空串/非 `/` 开头返回 `("", False)`;只含 `/` 返回 `("", True)`;取掉前导 `/`、第一个空白前的部分小写化作为 name;若 name 之后还有非空白尾随字符(用户传了参数),返回 `("", True)` 让 `lookup` 必然 miss 走未命中分支。纯字符串操作,无副作用。Registry 上的 `lookup` 已能完成查找,dispatch 不必另外封装。
**对外接口**：`parse`。

### `src/forgecode/command/ui.py`
**职责**：定义 `UI` Protocol；同时提供一个 `NopUI` 测试桩,供 registry/handler 单元测试用。
**对外接口**：`UI` Protocol、`NopUI` 类(所有写入方法 no-op、所有查询返回零值)。

### `src/forgecode/command/builtin_local.py`
**职责**：5 条纯本地命令的 handler——`/help`、`/status`、`/memory`、`/permission`、`/session`。
- `/help`：闭包捕获 reg,调用 `reg.visible()`,按"<name>  <description>" 两列对齐输出,通过 `ui.println` 打印。`register_builtins` 把 reg 自身传入 help handler 工厂。
- `/status`：按固定顺序输出 6 行——`Mode/Tokens/Tools/Memories/Model/Directory`,值来自 `ui.mode().value` / `ui.usage_in()`/`ui.usage_out()` / `ui.tool_count()` / `len(ui.memory_files())` / `ui.model_name()` / `ui.cwd()`。
- `/memory`：调用 `ui.memory_files()`,逐行打印文件名;为空时打印"无已加载的记忆文件"。
- `/permission`：打印 `ui.mode().value` 一行。
- `/session`：打印 "Session: <id>" + "Path: <path>" 两行(值来自 `ui.session_id()`、`ui.session_path()`)。

### `src/forgecode/command/builtin_ui.py`
**职责**：5 条影响界面命令——`/exit`、`/plan`、`/compact`、`/resume`、`/clear`。
- `/exit`：调用 `ui.quit()`。
- `/plan`：调用 `ui.set_mode(Mode.PLAN)` + `ui.println("已切换到 PLAN 模式")`。
- `/compact`：调用 `ui.force_compact()` (idle 守护由 dispatch_slash 在 handler 调用前完成,handler 自身不再检查)。
- `/resume`：调用 `ui.open_resume_menu()` (idle 守护由 dispatch_slash 统一做一次,open_resume_menu 自身不再检查)。
- `/clear`：调用 `ui.clear_and_new_session()`。

### `src/forgecode/command/builtin_prompt.py`
**职责**：2 条提示词命令——`/do`、`/review`。
- `/do`：`ui.set_mode(Mode.DEFAULT)` + `ui.inject_and_send("/do", prompt.EXECUTE_DIRECTIVE)`。
- `/review`：`ui.inject_and_send("/review", REVIEW_DIRECTIVE)` (REVIEW_DIRECTIVE 是模块级常量,文案如 "请审查上下文中的代码变更,指出潜在 bug、可读性问题、可简化处")。

### `src/forgecode/command/builtins.py`
**职责**：`register_builtins(reg: Registry) -> None`——按一致顺序在 reg 上注册 12 条命令,把对应 handler 写进 `Command(...)` 构造里;`/help` 的 handler 需要通过工厂函数捕获 reg。
**对外接口**：`register_builtins(reg)`。

### `src/forgecode/tui/commands.py` (改造)
**职责**：变成 thin glue:
1. 给 `ForgeCodeApp` 实现 `command.UI` Protocol 的所有方法(每个方法 1~5 行,属性桥接 + `RichLog.write`)
2. 提供 `ForgeCodeApp.dispatch_slash(text: str) -> bool`:调 `command.parse` → `self.cmd_registry.lookup` → 找到则 `await cmd.handler(self)`、未找到则向 RichLog 追加未知命令提示;返回 `True` 表示"已处理为命令"
3. 删掉 `builtin_commands` dict、`handle_exit/handle_plan/handle_do/handle_compact/handle_unknown` 等 5 个老 handler;保留 `handle_resume` 中和 `open_resume_menu` UI 方法整合的部分(ch09 写的 list/state 启动逻辑搬到 `ForgeCodeApp.open_resume_menu`)
**依赖**：`forgecode.command`、`forgecode.permission`、`forgecode.prompt`。

### `src/forgecode/agent/runtime.py` (改动)
- `SessionRuntime` 新增 `reset_for_new_session(self, ses_ctx: SessionContext) -> None` 方法:原子重置 `replacement` / `recovery` / `auto_tracking` 三个 compact 子状态,`usage_anchor` / `anchor_msg_len` / `turn_count` 清零,`session` 字段指向新的 `ses_ctx`;`context_window` 保留;writer 与 conv 重建由 `clear_and_new_session` 自身负责,不进 runtime 接口

### `src/forgecode/tui/stream.py` (改动)
- `submit()` 协程:把 `dispatch_command(text)` 这一行替换为 `await self.dispatch_slash(text)`,其余流程不变(空输入早返回、非命令走 `conv.add_user + begin_turn`)

### `src/forgecode/tui/complete.py` (新)
**职责**：自动补全菜单状态机 + 渲染。
- `CompletionMenu` dataclass 与方法见上面"核心数据结构"
- 提供 `ForgeCodeApp._handle_completion_key(event: events.Key) -> bool`:当菜单激活时返回 `True` 表示该键已被菜单消费;否则返回 `False` 让上层透传给 TextArea
- 提供 `ForgeCodeApp._sync_completion_from_input()`:每次 TextArea 内容变化后调用,根据当前内容刷新 `menu.active` / `menu.items`

### `src/forgecode/tui/app.py` (改动)
- `ForgeCodeApp` 增属性:`cmd_registry: Registry`、`completion: CompletionMenu`(注意:不要与已有的 `self.tool_registry: tool.Registry` 混淆,后者保持原名)
- `__init__`:构造 `Registry()` → `register_builtins(reg)` → 赋给 `self.cmd_registry`
- `on_key` 在 `SessionState.IDLE` 分支:
  - 先调 `self._handle_completion_key(event)`,被消费则直接 `event.stop()` 返回
  - 否则继续走原 TextArea key 处理 + Enter 触发 submit 的流程
  - TextArea 内容变化后(`on_text_area_changed`)调 `self._sync_completion_from_input()` 让菜单跟随输入实时刷新

### `src/forgecode/tui/view.py` (改动)
- 在 TextArea 渲染块下方、状态栏上方插入一个 `Static`(id="completion") widget;当 `self.completion.active` 时把 `self.completion.render(self.size.width)` 写入该 Static,否则清空
- 不动状态栏的左右字段、`mode_label`、`mode_status_style`

## 模块交互### 命令分发流(用户回车)

```
keystroke (Enter) ─► tui.on_key (IDLE)
                       │
                       ▼
                 tui.submit()
                  strip 输入
                  空输入 → 早返回
                       │
                       ▼
                await self.dispatch_slash(text)
                  │
                  ├─ command.parse(text)
                  │   is_slash=False → 返回 False (上层走 add_user + begin_turn)
                  │   is_slash=True 拿到 name
                  │
                  ├─ self.cmd_registry.lookup(name)
                  │   未找到 → RichLog.write(notice_block(unknown msg)), 清输入
                  │
                  └─ await cmd.handler(self)
                       │
                       ├─ 抛异常 → RichLog.write(error_block(str(exc)))
                       │
                       ▼
                     通过 UI Protocol 操作 self
                       ├─ println    → RichLog.write(notice_block(...))
                       ├─ set_mode   → self.mode = new_mode
                       ├─ inject_and_send → self.conv.add_user(preset) + asyncio.create_task(self.begin_turn(user_block(label)))
                       ├─ quit       → self.exit() (Textual App 异步退出)
                       ├─ force_compact / open_resume_menu / clear_and_new_session → 触发对应 sub-flow
```

注意:`UI.quit()` / `UI.force_compact()` 等都是直接调用 App 的对应方法(返回 None);Textual 内部用 asyncio,因此 handler 可以直接 `await` 异步动作。dispatch_slash 协程线性写下来即可,无需把"待执行 Cmd"另外缓冲。

### 自动补全流

```
keystroke (任意字符) ─► tui.on_key (IDLE)
                          │
                          ▼
                  self._handle_completion_key(event)
                    ┌─ 菜单 active=True:
                    │    ↑/↓       → menu.move_up/down, 消费
                    │    Tab/Enter → 执行 menu.selected() 的 handler, 关闭菜单, 消费
                    │    ESC       → menu.hide(), 消费
                    │    其他键    → 不消费, 透传 TextArea
                    │
                    └─ 菜单 active=False:
                         不消费, 透传

(透传 TextArea 处理后, on_text_area_changed)
self._sync_completion_from_input()
  读 self.input_area.text
  首字符是 "/" → menu.update(value, self.cmd_registry) → active=True 或刷新候选
  首字符非 "/" → menu.hide()

(渲染)
view 刷新:
  TextArea
  ↓ 如果 self.completion.active:
  Static#completion ← self.completion.render(width)  ← inline, 紧贴 TextArea
  ↓
  状态栏
```

## 文件组织

```
src/forgecode/command/                  新包
├── __init__.py        re-export
├── command.py         Kind 枚举, Command 与 Handler 类型
├── registry.py        Registry: register/lookup/visible/prefix_match
├── dispatch.py        parse(input_text)
├── ui.py              UI Protocol + NopUI 测试桩
├── builtins.py        register_builtins(reg) + REVIEW_DIRECTIVE 常量
├── builtin_local.py   /help /status /memory /permission /session
├── builtin_ui.py      /exit /plan /compact /resume /clear
└── builtin_prompt.py  /do /review

tests/
├── test_command_registry.py   注册中心冲突 / 前缀匹配测试
├── test_command_dispatch.py   parse 测试
└── test_command_builtins.py   12 条命令的注册与 NopUI 调用测试

src/forgecode/tui/
├── commands.py        改造: App 实现 UI Protocol + dispatch_slash + 删旧 handler
├── complete.py        新: CompletionMenu + _handle_completion_key + _sync_completion_from_input
├── stream.py          改: submit() 调 self.dispatch_slash
├── app.py             改: App 加 cmd_registry + completion 属性, __init__ 构造 cmd_registry
├── view.py            改: 插入 Static#completion 用于补全菜单渲染
├── resume.py          改: 把 handle_resume 函数体迁到 (ForgeCodeApp).open_resume_menu() 方法; 删除老 handle_resume
└── tests/test_tui.py  改: 旧的 test_tui_slash_compact_routes_to_command 等用例迁到新分发器

src/forgecode/agent/runtime.py  改: 新增 SessionRuntime.reset_for_new_session(ses_ctx); clear_and_new_session 调用此 helper 重置 compact 子状态

src/forgecode/__main__.py 不变 (TUI 构造时内部 wire cmd_registry)
src/forgecode/prompt.py   READY_HINT 由"硬编码列表" 改为"建议输入 /help 查看可用命令" (去掉与命令清单同步的负担)
tests/test_prompt.py    改: 跟随 READY_HINT 文案调整断言
```

## 技术决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| 命令系统包归属 | 新建 `src/forgecode/command/`,不留在 `src/forgecode/tui/` | tui 内 handler 持有 App 引用紧耦合,要满足 G3 必须把命令逻辑搬出 tui 包 |
| 注册方式 | 显式 `register_builtins(reg)`,不用 import 副作用 | 测试时能用空 registry,启动顺序明确,易做单测 |
| 冲突检测 | `register` 内部 `raise RuntimeError`,信息含具体名字/别名 | 失败快,启动期就报,不会进入运行时 |
| Handler 函数签名 | `async def handler(ui: UI) -> None` 而非 `def handler(app: ForgeCodeApp) -> None` | 满足 G3 解耦;handler 抛异常时,dispatch_slash 自动 `RichLog.write(error_block(str(exc)))`,用户能看到失败 |
| Idle 守护规则 | dispatch_slash 在调用 handler 前根据 Kind 判定:`Kind.UI` 与 `Kind.PROMPT` 命令在非 idle 状态拒绝(直接 error_block 提示);`Kind.LOCAL` 命令任何 state 都可执行 | handler 不再单独检查 `ui.idle()` |
| UI 与 Textual 协程衔接 | UI 方法直接同步改属性或同步调用 App 异步动作(`self.exit()` / `asyncio.create_task(self.begin_turn(...))`) | UI Protocol 方法保持无返回值,handler 写线性 `await` 代码 |
| Kind 与"是否进 history" | `Kind.PROMPT` = 调 `inject_and_send`; Kind 仅是元数据,实际行为靠 handler 主动调用 | 避免把"是否注入"做成隐式行为;由 handler 显式表达意图,可读 |
| 别名匹配范围 | dispatcher 命中(主名 + 别名都进 `_by_name`); 补全菜单仅按主名前缀 | 别名是输入快捷,补全是发现机制,语义不同;本期 12 条命令暂不填别名 |
| 补全菜单实现 | 自实现 inline 渲染到 `Static` widget,不用 Textual `OptionList` 弹窗 | `OptionList` 弹窗会抢焦点;inline `Static` + 自渲染足够 |
| 补全菜单激活条件 | TextArea 首字符为 `/` | 简单可靠;空输入或非 "/" 开头都不弹 |
| 补全菜单键位归属 | active 时 ↑/↓/Tab/Enter/ESC 都被消费; 关闭时透传 TextArea | 用户在菜单激活时不会期望普通编辑;关闭后所有键回到 TextArea |
| 老命令收编 | 一次性把 5 条旧 handler 重写为基于 UI Protocol 的新 handler;不保留过渡 | 双轨维护成本高于一次性重写 |
| /resume 状态机 | `UI.open_resume_menu` 内部仍由 tui 包持有 `SessionState` 与 `OptionList`(或自渲染列表) | 避免 command 包知道 Textual 类型;ch09 行为完全保留 |
| /clear 实现 | close 旧 writer → 用 `compact.new_session_context` 构造新 `SessionContext` → 用 `session.open_writer` 打开新 writer → 重新构造 `Conversation(on_append=..., on_replace=...)`(on_append 闭包重新捕获新 writer)→ `self.runtime.reset_for_new_session(...)` → `self.iter=0, self.usage_in=0, self.usage_out=0` | 旧 writer 关闭后其 hook 已失效,必须重建 conversation 才能挂上新 writer;旧 JSONL 文件保留,/resume 仍能看到 |
| /memory 数据源 | `UI.memory_files()` 由 App 委托给已有的 `mem_mgr` | 不重做记忆加载,只新增"列文件名"查询路径 |
| /status 字段渲染 | 6 行 key:value 两列对齐(key 用 `str.ljust`); Mode 用 `Mode.value`(枚举字符串);model_name 来源为 `self.provider.model`(provider 为 None 时返回空串),与状态栏取 model name 的来源一致,不读 self.engine | `Mode.value` 已是 camelCase(default/plan/acceptEdits/bypassPermissions) 与设计图一致 |
| tool_count 数据源 | `UI.tool_count()` 由 App 委托给 `self.tool_registry.count()`,即 `tool.Registry` 已有(若不存在则本期新增)的 O(1) 方法 | 与 `cmd_registry` 属性无关,二者并存 |
| 未命中提示文本 | "未知命令: /<name>。输入 /help 查看可用命令" | 唯一硬编码字符串;集中在 commands.py 中 |
| READY_HINT 处理 | 改为通用引导文案("准备好了,输入 /help 查看命令"),不再列具体命令名 | 消除 N7 要求的"硬编码命令清单" |
| 状态栏改动 | 不动 | N11 要求 |