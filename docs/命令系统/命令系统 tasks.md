# slash命令体系 Tasks

> 包名：`forgecode`（Python 3.12+）。源码位于 `src/forgecode/`，内部模块以 `forgecode.xxx` 导入；单测放在 `tests/`，运行框架 `pytest`。

## 文件清单

| 操作 | 文件 | 职责 |
|------|------|------|
| 新建 | `src/forgecode/command/__init__.py` | 包出口,re-export 公共类型与函数 |
| 新建 | `src/forgecode/command/command.py` | Kind 枚举、Command 与 Handler 类型 |
| 新建 | `src/forgecode/command/registry.py` | Registry: register/lookup/visible/prefix_match + 冲突检测 |
| 新建 | `tests/test_command_registry.py` | 注册、冲突、前缀匹配、visible 排序的单测 |
| 新建 | `src/forgecode/command/dispatch.py` | parse(input_text) — 解析 `/<name>` 形态 |
| 新建 | `tests/test_command_dispatch.py` | parse 各种输入的单测 |
| 新建 | `src/forgecode/command/ui.py` | UI Protocol + NopUI 测试桩 |
| 新建 | `src/forgecode/command/builtin_local.py` | 5 条纯本地命令(/help /status /memory /permission /session) |
| 新建 | `src/forgecode/command/builtin_ui.py` | 5 条影响界面命令(/exit /plan /compact /resume /clear) |
| 新建 | `src/forgecode/command/builtin_prompt.py` | 2 条提示词命令(/do /review) + REVIEW_DIRECTIVE 常量 |
| 新建 | `src/forgecode/command/builtins.py` | register_builtins(reg) 把 12 条命令一次性注入 |
| 新建 | `tests/test_command_builtins.py` | 12 条命令注册成功、NopUI 调用全部 handler 不抛 |
| 改造 | `src/forgecode/tui/commands.py` | 删旧 builtin_commands + handle_* 函数;新增 App 实现 UI Protocol 的全部方法 + dispatch_slash 入口 |
| 新建 | `src/forgecode/tui/complete.py` | CompletionMenu 类型 + _handle_completion_key + _sync_completion_from_input + render |
| 改造 | `src/forgecode/tui/resume.py` | handle_resume 改名/拆分为 ForgeCodeApp.open_resume_menu(UI Protocol 实现) |
| 改造 | `src/forgecode/tui/app.py` | App 增 cmd_registry+completion 属性; __init__ 构造 registry; on_key 在 IDLE 接入补全键位拦截 |
| 改造 | `src/forgecode/tui/stream.py` | submit() 把 dispatch_command 调用替换为 self.dispatch_slash |
| 改造 | `src/forgecode/tui/view.py` | 在 TextArea 下、状态栏上插入 Static#completion |
| 改造 | `tests/test_tui.py` | 老的 test_tui_slash_compact_routes_to_command / test_tui_unknown_slash_command_friendly 迁到新分发器 |
| 改造 | `src/forgecode/prompt.py` | READY_HINT 改为"建议输入 /help 查看命令"(不再列具体命令名) |
| 改造 | `tests/test_prompt.py` | 跟随 READY_HINT 变化 |
| 改造 | `src/forgecode/memory/manager.py` + `tests/test_memory_manager.py` | 新增 list_files |
| 改造 | `src/forgecode/session/writer.py` + `tests/test_session_writer.py` | 新增 path 属性 |
| 改造 | `src/forgecode/tool/registry.py` | 新增 count() |
| 改造 | `src/forgecode/agent/runtime.py` + `tests/test_agent_runtime.py` | 新增 reset_for_new_session |

## 任务### T0a: memory.Manager.list_files**文件**：`src/forgecode/memory/manager.py`、`tests/test_memory_manager.py`
**依赖**：无
**步骤**：
1. 在 manager.py 新增 `def list_files(self) -> tuple[list[str], list[str]]` — 列出项目层与用户层 memory 目录下的 `.md` 文件(含 `MEMORY.md` 自身);目录不存在视为空 list,不抛异常;其它 `OSError` 用 `logging.warning(...)` 记录后视为空 list;返回值已按文件名字典序排序
2. 单测覆盖 4 个 case:目录不存在 / 仅含 MEMORY.md / 含多 .md / 含 .md 与非 .md 混合

**验证**：`pytest tests/test_memory_manager.py -k list_files -v` 全绿

### T0b: session.Writer.path**文件**：`src/forgecode/session/writer.py`、`tests/test_session_writer.py`
**依赖**：无
**步骤**：
1. `Writer` 类新增 `self.path: str` 属性;`open_writer` / `__init__` 在打开成功后写 `self.path = str(<绝对路径>)`
2. (若已存在以 `path` 命名的字段,直接复用即可,不重复添加)
3. 单测:创建 writer 后断言 `writer.path` 非空且对应文件存在

**验证**：`pytest tests/test_session_writer.py -k path -v` 全绿
**注**:`session_id` 不由 writer 提供,数据源是 `self.runtime.session.session_id`

### T0c: SessionRuntime.reset_for_new_session + tool.Registry.count**文件**：`src/forgecode/agent/runtime.py`、`tests/test_agent_runtime.py`、`src/forgecode/tool/registry.py`
**依赖**：无
**步骤**：
1. runtime.py 新增 `def reset_for_new_session(self, ses_ctx: SessionContext) -> None` — 原子重置 `replacement` / `recovery` / `auto_tracking` / `session` / `usage_anchor` / `anchor_msg_len` / `turn_count`,把 `self.session` 指向 `ses_ctx`
2. test_agent_runtime.py 单测:调用后所有字段回到 `__init__` 时的零值,`session` 属性被替换
3. tool/registry.py 新增 `def count(self) -> int` — 返回当前已注册工具数量(O(1) 实现,基于现有内部 list/dict 长度)

**验证**：`pytest tests/test_agent_runtime.py -k reset -v` 全绿;`python -c "from forgecode.tool.registry import Registry; Registry().count()"` 不报错

### T1: 定义 Command 类型与 Kind 枚举**文件**：`src/forgecode/command/command.py`
**依赖**：无
**步骤**：
1. 新建包 `forgecode.command`(`__init__.py` 留空)
2. 定义 `class Kind(Enum)` 与 3 个成员 `LOCAL = "local"`、`UI = "ui"`、`PROMPT = "prompt"`
3. 定义 `Handler = Callable[["UI"], Awaitable[None]]` 类型别名(UI 协议在 T4 声明,可用前向引用字符串)
4. 定义 `@dataclass(slots=True) class Command` 字段:`name: str`、`description: str`、`kind: Kind`、`handler: Handler`、`aliases: list[str] = field(default_factory=list)`、`hidden: bool = False`

**验证**：`python -c "from forgecode.command.command import Kind, Command"` 不报错

### T2: 实现 Registry + 冲突检测 + 前缀匹配**文件**：`src/forgecode/command/registry.py`、`tests/test_command_registry.py`
**依赖**：T1
**步骤**：
1. `class Registry` 含 `_by_name: dict[str, Command]`、`_visible: list[Command]`
2. `__init__`:初始化空 dict + 空 list
3. `register(self, cmd: Command) -> None`:
   - 校验 `cmd.name` 非空且全小写、`cmd.aliases` 全部非空且全小写
   - 遍历 `(cmd.name, *cmd.aliases)` 每个 key,若已存在于 `_by_name` 则 `raise RuntimeError(f"command conflict: {key}")` 含具体冲突键
   - 通过后把每个 key 塞进 `_by_name` 都指向同一个 cmd
   - 若 `not cmd.hidden` 则 append 到 `_visible`,然后对 `_visible` 按 `name` 字典序排序(`_visible.sort(key=lambda c: c.name)`)
4. `lookup(self, name: str) -> Command | None`:小写化 name 后查 `_by_name.get(name.lower())`
5. `visible(self) -> list[Command]`:`return list(self._visible)` (拷贝防外部改动)
6. `prefix_match(self, prefix: str) -> list[Command]`:`p = prefix.lstrip("/").lower()`;遍历 `_visible`,name 以 `p` 开头入选;保持字典序返回;`p == ""` 时返回全部 visible
7. 写 5 个测试:`test_register_ok`、`test_register_duplicate_name_raises`、`test_register_duplicate_alias_raises`、`test_visible_sorted`、`test_prefix_match`

**验证**：`pytest tests/test_command_registry.py -v` 全绿

### T3: parse 输入解析**文件**：`src/forgecode/command/dispatch.py`、`tests/test_command_dispatch.py`
**依赖**：无
**步骤**：
1. `def parse(input_text: str) -> tuple[str, bool]`:对 `input_text` 调 `.strip()`;若不以 `/` 开头返回 `("", False)`;若仅为 `/` 返回 `("", True)`;否则取掉前导 `/`、按 `str.split(maxsplit=1)` 切;若有第二段非空(即用户传了参数),返回 `("", True)`(让 lookup miss);否则返回 `(name.lower(), True)`
2. 表驱动测试样本:`""` / `"   "` / `"hello"` / `"/"` / `"/help"` / `"  /HELP  "` / `"/help xx"`(→ `("", True)`) / `"/help  "`(→ `("help", True)`) / `"//double"` / `"/ /help"`(→ `("", True)`),确认每个返回值

**验证**：`pytest tests/test_command_dispatch.py -v` 全绿

### T4: UI Protocol + NopUI 测试桩**文件**：`src/forgecode/command/ui.py`
**依赖**：无(声明 UI Protocol 让 T1 的 Handler 类型签名合法)
**步骤**：
1. import `from forgecode.permission import Mode`
2. `class UI(Protocol)`:方法集完整列出(见 plan.md "core UI" 一节):println/error/mode/set_mode/inject_and_send/usage_in/usage_out/model_name/cwd/tool_count/memory_files/session_path/session_id/quit/force_compact/open_resume_menu/clear_and_new_session/idle
3. `class NopUI:` 实现该协议:所有写入方法 no-op、所有查询返回零值(`mode()` 返回 `Mode.DEFAULT`、`memory_files()` 返回 `[]` 等)
4. 在 dispatch_slash 用到的 helper 之前,先保证 NopUI 可用

**验证**：`python -c "from forgecode.command.ui import UI, NopUI; NopUI().mode()"` 不报错

### T5: 实现 5 条纯本地命令**文件**：`src/forgecode/command/builtin_local.py`
**依赖**：T1、T2、T4
**步骤**：
1. `def make_help_handler(reg: Registry) -> Handler`:返回 `async def _handler(ui)` 闭包,内部调 `reg.visible()`,计算最长 name 长度做对齐填充,逐条拼 `f"/{c.name.ljust(w)}  {c.description}"`,用 `\n` 连接后 `ui.println(...)` 一次输出
2. `async def handle_status(ui)`:6 行 key:value,key 列宽固定(`Mode:`/`Tokens:`/`Tools:`/`Memories:`/`Model:`/`Directory:` 中最长那个);值依次:`ui.mode().value`、`f"{ui.usage_in()} in / {ui.usage_out()} out"`、`f"{ui.tool_count()} enabled"`、`f"{len(ui.memory_files())} files"`、`ui.model_name()`、`ui.cwd()`;首行加标题 "ForgeCode Status"(空行隔开)
3. `async def handle_memory(ui)`:`files = ui.memory_files()`;`if not files: ui.println("无已加载的记忆文件")`;否则按行打印 files
4. `async def handle_permission(ui)`:`ui.println(ui.mode().value)`
5. `async def handle_session(ui)`:`ui.println(f"Session: {ui.session_id()}\nPath: {ui.session_path()}")`

**验证**：`python -c "import forgecode.command.builtin_local"` 通过;后续 T8 的 test_command_builtins 会覆盖

### T6: 实现 5 条影响界面命令**文件**：`src/forgecode/command/builtin_ui.py`
**依赖**：T1、T4
**步骤**：
1. `async def handle_exit(ui)`: `ui.quit()`
2. `async def handle_plan(ui)`: `ui.set_mode(Mode.PLAN); ui.println("已切换到 PLAN 模式")`
3. `async def handle_compact(ui)`: `if not ui.idle(): ui.error("请等待当前任务完成"); return`;`ui.force_compact()`
4. `async def handle_resume(ui)`: `if not ui.idle(): ui.error("请等待当前任务完成"); return`;`ui.open_resume_menu()`
5. `async def handle_clear(ui)`: `ui.clear_and_new_session(); ui.println("已清空当前会话,开启新 session")`

**验证**：`python -c "import forgecode.command.builtin_ui"` 通过

### T7: 实现 2 条提示词命令**文件**：`src/forgecode/command/builtin_prompt.py`
**依赖**：T1、T4
**步骤**：
1. 模块级 `REVIEW_DIRECTIVE = "请审查当前上下文中的代码变更/已读取的文件,指出潜在 bug、可读性问题和可简化处。"`
2. `async def handle_do(ui)`: `ui.set_mode(Mode.DEFAULT); ui.inject_and_send("/do", prompt.EXECUTE_DIRECTIVE)` (import `from forgecode import prompt`)
3. `async def handle_review(ui)`: `ui.inject_and_send("/review", REVIEW_DIRECTIVE)`

**验证**：`python -c "import forgecode.command.builtin_prompt"` 通过

### T8: register_builtins + 12 条命令一次性注册**文件**：`src/forgecode/command/builtins.py`、`tests/test_command_builtins.py`
**依赖**：T5、T6、T7
**步骤**：
1. `def register_builtins(reg: Registry) -> None`:按字典序注册 12 条 `Command(...)` 字面量(name 全部小写,description 一句中文,kind 按设计,aliases 留默认空 list,hidden=False);`/help` 的 handler 通过 `make_help_handler(reg)` 工厂注入
2. test_command_builtins.py 写:
   - `test_register_builtins_all_registered`(注册后 `reg.visible()` 长度=12、含所有 12 个名字)
   - `test_register_builtins_no_collision`(直接调 register_builtins 不抛)
   - `test_register_builtins_handlers_run_on_nop_ui`(用 `pytest.mark.asyncio` 把 NopUI 传给每个命令的 handler,`await` 后断言不抛)
3. 升级为可观测桩:新增 `RecordingUI` 类继承 NopUI,记录 `println/error/set_mode/inject_and_send` 调用;至少 3 个行为断言:
   - `test_handle_status_prints_all_keys` — handle_status 调用 println 一次且文本含 6 个 key(Mode/Tokens/Tools/Memories/Model/Directory)
   - `test_handle_compact_blocks_when_busy` — handle_compact 在 `idle()==False` 时调 error 不调 force_compact
   - `test_handle_do_sets_mode_and_injects` — handle_do 调 `set_mode(Mode.DEFAULT)` + `inject_and_send("/do", ...)`

**验证**：`pytest tests/test_command_builtins.py -v` 全绿;`ruff check src/forgecode/command/` 无告警

### T8.5: App 属性铺垫**文件**：`src/forgecode/tui/app.py`
**依赖**：T8
**步骤**：
1. `ForgeCodeApp` 在原 `tool_registry: tool.Registry` 属性之后增 `cmd_registry: Registry | None = None`、`completion: CompletionMenu`、`_pending_println: list[str] = []`(注:Python 中 RichLog 可同步写,不像 Go 的 `tea.Cmd` 需要缓冲,但保留 list 以便 dispatch_slash 内统一收集 + 渲染时刷新)四个属性
2. 在 `__init__` 中初始化(`completion = CompletionMenu()`,`_pending_println = []`;registry 通过 T9c 注册)

**验证**：`python -m forgecode` 在合法配置下能启动(空壳启动不被影响)

### T9a: TUI App 实现 UI 只读查询方法**文件**：`src/forgecode/tui/commands.py`(在该文件已被清空旧 handler 后重写)
**依赖**：T8.5
**步骤**：
1. 删除旧文件 `src/forgecode/tui/commands.py` 全部内容(`builtin_commands` dict、`dispatch_command` 函数、`handle_exit`/`handle_plan`/`handle_do`/`handle_compact`/`handle_unknown`、`format_compact_notice` 全部移除)
2. 给 `ForgeCodeApp` 实现 UI Protocol 的所有只读方法(直接定义在 `app.py` 中也可,推荐放 `commands.py` 作为 mixin/方法集):
   - `def mode(self) -> Mode` → `return self._mode`
   - `def usage_in(self) -> int` / `usage_out(self) -> int` → 返回 `self._usage_in` / `self._usage_out`
   - `def model_name(self) -> str` → `return self.provider.model if self.provider else ""`
   - `def cwd(self) -> str` → 返回 `self._cwd`(若 App 上没有此属性,从启动参数拷一份)
   - `def tool_count(self) -> int` → `return self.tool_registry.count()`
   - `def memory_files(self) -> list[str]` → 调 `self.mem_mgr.list_files()` 然后 `return project + user`
   - `def session_path(self) -> str` → `return self.writer.path if self.writer else ""`
   - `def session_id(self) -> str` → `return self.runtime.session.session_id if self.runtime and self.runtime.session else ""`
   - `def idle(self) -> bool` → `return self.state == SessionState.IDLE`

**验证**：`python -c "from forgecode.tui.app import ForgeCodeApp"` 通过

### T9b: TUI App 实现 UI 写入方法**文件**：`src/forgecode/tui/commands.py`
**依赖**：T9a
**步骤**：
1. `def println(self, msg: str) -> None` → `self._pending_println.append(msg)` (原始字符串,render 时再用 `notice_block` 包)
2. `def error(self, msg: str) -> None` → `self._pending_println.append(f"ERROR\x00{msg}")` (用前缀编码区分 notice/error,render 时按前缀分流)
3. `def set_mode(self, m: Mode) -> None` → `self._mode = m`
4. `def quit(self) -> None` → `self.exit()` (Textual App 内置异步退出)
5. `def force_compact(self) -> None` → 复用原 handle_compact 内构造的协程,`asyncio.create_task(self._run_force_compact())`
6. `def open_resume_menu(self) -> None` → 直接调 T10 提供的方法体(本步骤仅声明,实现在 T10 在 resume.py 提供,本步骤不在 commands.py 中重新定义)
7. `def clear_and_new_session(self) -> None` — 步骤:
   a. `self.writer.close()` (如非 None)
   b. `try: new_ses_ctx = compact.new_session_context(self._cwd)`;`except Exception as e: self.error(str(e)); return`。注意签名:`compact.new_session_context(workspace: str) -> SessionContext`,内部在 `<workspace>/.forgecode/sessions/<id>/tool-results` 下建好目录
   c. `try: new_writer = session.open_writer(new_ses_ctx.session_dir)`;`except Exception as e: self.error(str(e)); return` (沿用 ch09 既有的 `open_writer` 入口,不要新写一个 `Writer` 构造器)
   d. `self.writer = new_writer`
   e. 重新构造 `self.conv = Conversation(on_append=on_append, on_replace=on_replace)`,on_append/on_replace 闭包捕获 `new_writer` 与新的 `is_first = [True]`(可变标志)
   f. `self.runtime.reset_for_new_session(new_ses_ctx)`
   g. `self.iter = 0; self._usage_in = 0; self._usage_out = 0`
   h. 调 `self.query_one("#log", RichLog).clear()` (Textual 接口) 完成重绘
8. `def inject_and_send(self, label: str, preset: str) -> None` — `self.conv.add_user(preset)`;`asyncio.create_task(self.begin_turn(user_block(label)))`

建议:把 conv 闭包构造抽成 `def _bind_conversation(self, writer: Writer) -> Conversation` 让 `__init__` 和 `clear_and_new_session` 共用,避免漂移

**验证**：`python -c "from forgecode.tui.app import ForgeCodeApp"` 通过

### T9c: dispatch_slash 入口 + 注册中心构造**文件**：`src/forgecode/tui/commands.py`、`src/forgecode/tui/app.py`
**依赖**：T9b
**步骤**：
1. commands.py 新增 `async def dispatch_slash(self, text: str) -> bool`:
   a. `name, is_slash = parse(text)`;若 `not is_slash`: `return False`
   b. 清 `self._pending_println`(不再缓冲后期 cmd,因为 Python 直接 await/create_task)
   c. `cmd = self.cmd_registry.lookup(name)`
   d. `cmd is None` → `self._pending_println.append(notice_block("未知命令: 输入 /help 查看可用命令"))` (注:parse 返回 `("", True)` 即退化输入(纯 `/` 或 `/<空白>`)时,提示文案不要拼 `"/+name"` 避免出现 `"未知命令: /, ..."` 这种悬空斜杠)
   e. `cmd is not None and cmd.kind in (Kind.UI, Kind.PROMPT) and self.state != SessionState.IDLE` → `self._pending_println.append(error_block("请等待当前任务完成"))`
   f. 否则 `try: await cmd.handler(self)`;`except Exception as exc: self._pending_println.append(error_block(str(exc)))`
   g. 把 `self._pending_println` 内每条按前缀分流后写入 `self.query_one("#log", RichLog).write(...)`,清空 `_pending_println`,`return True`
2. app.py `__init__` 中加:`reg = Registry(); register_builtins(reg); self.cmd_registry = reg`

**验证**：`python -m forgecode`(合法配置)能启动且 `/help` 已可触发(肉测);`ruff check .` 无告警

### T10: open_resume_menu — handle_resume 重构进 UI Protocol**文件**：`src/forgecode/tui/resume.py`
**依赖**：T9
**步骤**：
1. 把现有 `handle_resume(app: ForgeCodeApp)` 函数体迁移到 `ForgeCodeApp.open_resume_menu(self)`:把"state guard"那一段已经在 builtin_ui 的 handle_resume 处理;剩下"构造 session items 列表、设置 `self.resume_list`、切换 `self.state = SessionState.RESUMING`"放进 open_resume_menu;Textual 异步动作直接 `asyncio.create_task(...)` 即可。同时移除 open_resume_menu 内部对 `self.state != IDLE` 的判断和提示(guard 已在 dispatch_slash 按 Kind 统一处理)
2. 如果 handle_resume 老函数还被引用,删除引用;否则直接整段移除
3. `update_resuming`、`do_resume_session`、`resume_session_msg` 保持不变(它们由 Textual 事件调度,不属于命令系统)

**验证**：`python -c "from forgecode.tui.resume import *"` 通过;肉测 `/resume` 仍弹历史列表

### T11: CompletionMenu 状态机 + 渲染**文件**：`src/forgecode/tui/complete.py`(新)
**依赖**：T2
**步骤**：
1. 定义 `@dataclass class CompletionMenu`: `items: list[Command]`、`cursor: int = 0`、`offset: int = 0`、`active: bool = False`
2. 模块级 `MAX_ROWS = 8`
3. `def update(self, input_text: str, reg: Registry) -> None`:`input_text` 去前后空白;若不以 `/` 开头则 `self.active = False` 并 return;否则 `self.items = reg.prefix_match(input_text)`;若 `len(items)==0` 仍 `active = True`(显示"无匹配");`cursor` / `offset` 在 items 长度变化时夹紧
4. `def move_up(self) / def move_down(self)`:cursor 夹在 `[0, len(items)-1]`;offset 跟随 cursor,使 cursor 始终在可见窗口内
5. `def selected(self) -> Command | None`:items 非空时返回 `items[self.cursor]`,否则 None
6. `def hide(self) -> None`:`active=False; items=[]; cursor=0; offset=0`
7. `def render(self, width: int) -> str`:`active=False` 返回 `""`;否则用 `rich.text.Text` 渲染一个左对齐的多行块:每行 `/{name}  {description}`,name 列做对齐填充;高亮 cursor 行(`style="reverse"` 或背景色);上下溢出时显示 `↑ N more` / `↓ N more` 提示行;整块宽度不超 width。返回 markup 字符串供 Static widget 直接写入
8. `def _handle_completion_key(self: ForgeCodeApp, event: events.Key) -> bool` (作为 App 方法,定义在 complete.py 但在 app.py 中绑定):if `not self.completion.active: return False`;match `event.key`:
   - `"up"`: `self.completion.move_up(); event.stop(); return True`
   - `"down"`: `self.completion.move_down(); event.stop(); return True`
   - `"escape"`: `self.completion.hide(); event.stop(); return True`
   - `"enter"` / `"tab"`: `sel = self.completion.selected();` `if sel is not None: await self._execute_selected(sel); event.stop(); return True`;`else: self.completion.hide(); event.stop(); return True`
   - 其他:`return False`(透传 TextArea)
   `_execute_selected(sel)`:`self.input_area.text = "/" + sel.name; await self.submit(); self.completion.hide();`(submit 内部已会清空 TextArea)
9. `def _sync_completion_from_input(self: ForgeCodeApp) -> None`:取 `self.input_area.text`,调 `self.completion.update(value, self.cmd_registry)`(注意是 `cmd_registry` 不是 `tool_registry`)

**验证**：`python -c "from forgecode.tui.complete import CompletionMenu"` 通过;先用 `ruff check src/forgecode/tui/` 看类型错误

### T12: TUI App 集成补全键位**文件**：`src/forgecode/tui/app.py`
**依赖**：T9c、T10、T11
**步骤**：
1. App 属性已在 T8.5 加好(`cmd_registry`、`completion`、`_pending_println`);本任务不重新声明
2. `__init__`:`cmd_registry` 的构造已在 T9c step 2 完成;本任务不重复
3. `on_key(self, event: events.Key)` 在 `state == SessionState.IDLE` 分支处理时:
   - 先调 `if await self._handle_completion_key(event): return`(消费即提前 return)
   - 否则继续原 TextArea key 处理路径
4. 注册 `on_text_area_changed(self, event: TextArea.Changed)` 事件:`if event.text_area.id == "input": self._sync_completion_from_input()`
5. `on_key` 中对 Enter 键的处理保持现状(由 submit() 处理);submit() 内的命令分发改动放 T13

**验证**：`python -m forgecode` 启动后键入 `/` 应弹补全菜单(肉测);`ruff check .` 无告警

### T13: stream.submit 接入 dispatch_slash + view 渲染补全菜单**文件**：`src/forgecode/tui/stream.py`、`src/forgecode/tui/view.py`
**依赖**：T12
**步骤**：
1. stream.py: `submit()` 中把现有的 `handler, is_cmd = dispatch_command(text); if is_cmd: await handler(self)` 整段替换为:
   ```python
   if await self.dispatch_slash(text):
       self.input_area.text = ""
       self.completion.hide()
       return
   ```
2. view.py: 在 `compose` 中,定位到 TextArea 渲染块之后、状态栏之前;插入 `yield Static("", id="completion")`
3. view.py: 在 App 的 `_render_completion` helper(或直接在补全菜单状态变化处)写:`self.query_one("#completion", Static).update(self.completion.render(self.size.width) if self.completion.active else "")`
4. view.py: 不要动状态栏 / `mode_label` / `mode_status_style` 函数

**验证**：`python -m forgecode` 整体跑通;`pytest tests/test_tui.py -k slash -v` 期待红(下一任务迁移测试)

### T14: 迁移测试 + READY_HINT 调整**文件**：`tests/test_tui.py`、`src/forgecode/prompt.py`、`tests/test_prompt.py`
**依赖**：T13
**步骤**：
1. `tests/test_tui.py`: 把 `test_tui_slash_compact_routes_to_command` 改为构造 App + 注册 builtins 后,`await app.dispatch_slash("/compact")`、断言返回 `True`、断言未调 `conv.add_user`(用 `monkeypatch` / `MagicMock`)
2. `test_tui_unknown_slash_command_friendly` 改为调 `await app.dispatch_slash("/foobar")`、断言返回 `True`、断言 `app._pending_println` 含"未知命令"
3. 新增 `test_tui_dispatch_case_insensitive` 测 `/Help` 与 `/help` 同效;`test_tui_dispatch_help_lists_all_builtins` 测 `/help` 输出含 12 个命令名
4. prompt.py: `READY_HINT` 字符串由现有 "/plan, /do, /exit" 列表改为类似 `"已就绪,输入 /help 查看可用命令。"`(具体文本含 /help 引导即可)
5. test_prompt.py: 跟随调整断言

**验证**：`pytest -q` 全绿;`ruff check .` 无告警;`ruff format --check .` 通过

### T15: 端到端验证(tmux 实跑)**文件**：无(运行可执行文件)
**依赖**：T14
**步骤**：
1. `cd /Users/codemelo/forgecode && uv sync`(或 `pip install -e ".[dev]"`)
2. `tmux new-session -d -s mewspec 'uv run forgecode'` 启动会话(或 `python -m forgecode`)
3. 按 checklist.md 的"端到端场景(tmux 实跑)"逐项发送按键并截屏:
   - 启动后键入 `/` 看补全菜单是否弹出且含 12 条
   - 键入 `/s` 看是否过滤为 /session、/status
   - 选中 /status 回车验证 6 字段输出
   - 依次跑 /help、/memory、/permission、/session、/review、/clear,逐一观测输出
   - 验证 /plan 切到 plan 模式后状态栏徽章变化
   - 验证 /do 切回 default + 触发 AI 回复
   - 验证 /resume 列表能看到 /clear 之前的旧会话
   - 验证未知命令 /foobar 提示
   - 验证启动期冲突检测:临时给某条命令多注册一遍同名,启动应抛 RuntimeError 退出,看错误信息
4. 全部通过后 `tmux kill-session -t mewspec`

**验证**：按 checklist.md 全部勾选;期间出错则修复后从失败点重跑

## 执行顺序

```
T0a, T0b, T0c (并行) → T1 → (T2, T3, T4 并行) → (T5, T6, T7 并行) → T8 → T8.5 → T9a → T9b → T9c → T10 → T11 → T12 → T13 → T14 → T15
```

- T0a/T0b/T0c 是底层 helper 铺垫(memory.list_files、session.Writer.path、runtime.reset_for_new_session、tool.Registry.count),互不依赖可并行
- T1/T2/T3/T4 是 command 包基础,T1→T2 是结构依赖,T2/T3/T4 互不依赖可并行
- T5/T6/T7 三组命令实现互不依赖,可并行
- T8 必须在 T5+T6+T7 后
- T8.5 给 App 加属性,作为 T9a 前置
- T9a→T9b→T9c 拆分原 T9:只读方法 → 写入方法 → dispatch_slash 与注册中心,严格串行
- T10 替换 open_resume_menu;T11(CompletionMenu)仅依赖 T2,放在 T10 后接入 UI 也可
- T12 把 on_key 接入补全键位;T13 把 stream/view 接入;T14 是测试与 READY_HINT 调整,T15 是端到端验证