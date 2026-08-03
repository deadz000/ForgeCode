# SubAgent 机制 Tasks

> 包名：`forgecode`(Python 3.12+)。源码位于 `src/forgecode/`,内部模块以 `forgecode.xxx` 导入。

## 文件清单

| 操作 | 文件 | 职责 |
|------|------|------|
| 新建 | `src/forgecode/subagent/__init__.py` | 包公共导出 |
| 新建 | `src/forgecode/subagent/definition.py` | `Definition` / `Source` 类型 |
| 新建 | `src/forgecode/subagent/parser.py` | `parse_frontmatter_and_body` + `validate_meta` |
| 新建 | `tests/subagent/test_parser.py` | 解析与字段校验单测 |
| 新建 | `src/forgecode/subagent/catalog.py` | `Catalog` + `load_catalog` / `resolve` / `list` / `fork_definition` |
| 新建 | `tests/subagent/test_catalog.py` | 多来源加载与覆盖测试 |
| 新建 | `src/forgecode/subagent/embed.py` | `importlib.resources` 读取 builtin/*.md + `builtin_definitions()` |
| 新建 | `src/forgecode/subagent/builtin/general-purpose.md` | 内置 general-purpose 定义 |
| 新建 | `src/forgecode/subagent/builtin/explore.md` | 内置 Explore 定义 |
| 新建 | `src/forgecode/subagent/builtin/plan.md` | 内置 Plan 定义 |
| 新建 | `tests/subagent/test_launch.py` | `launch_fork` 流程测试 |
| 新建 | `src/forgecode/task/__init__.py` | 包公共导出 |
| 新建 | `src/forgecode/task/manager.py` | `Manager` + `BackgroundTask` + `launch` / `adopt_running` / `stop` / `send_message` / `subscribe_done` |
| 新建 | `tests/task/test_manager.py` | 后台任务全生命周期测试 |
| 新建 | `src/forgecode/task/tools.py` | 4 个内置工具 `TaskListTool` / `TaskGetTool` / `TaskStopTool` / `SendMessageTool` |
| 新建 | `tests/task/test_tools.py` | 4 个工具的单测 |
| 新建 | `src/forgecode/agent/run_to_completion.py` | `run_to_completion` 方法实现(挂到 `Agent` 上) |
| 新建 | `tests/agent/test_run_to_completion.py` | `run_to_completion` / `dont_ask` / `max_turns` 测试 |
| 新建 | `src/forgecode/agent/fork.py` | `build_forked_messages` + `is_fork_context` + `FORK_BOILERPLATE` |
| 新建 | `tests/agent/test_fork.py` | Fork 消息构造与上下文识别测试 |
| 新建 | `src/forgecode/agent/agent_tool.py` | `AgentTool` + `execute` |
| 新建 | `tests/agent/test_agent_tool.py` | Agent 工具调用、嵌套阻断、超时切后台测试 |
| 新建 | `src/forgecode/agent/permission_upgrade.py` | `ApprovalUpgrader` 类型 + `default_upgrader` |
| 新建 | `src/forgecode/agent/launch.py` | `launch_fork` 公共启动函数(供 skill_fork 调用) |
| 新建 | `src/forgecode/tool/filter.py` | `ALL_AGENT_DISALLOWED` / `ASYNC_AGENT_ALLOWED` / `apply_agent_tool_filter` |
| 新建 | `tests/tool/test_filter.py` | 过滤多层防线测试 |
| 新建 | `src/forgecode/tui/tasks.py` | `_consume_task_done` + `build_task_notification` + ESC 切后台辅助 |
| 修改 | `src/forgecode/agent/agent.py` | 加 system_prompt / max_turns / permission_mode / dont_ask / approval_upgrader 字段;`run` 抽 `_run_iter`;`_run_guarded` 加 `dont_ask` 短路 + `approval_upgrader` 升级 |
| 修改 | `tests/agent/test_agent.py` | 不破坏既有测试 |
| 修改 | `src/forgecode/tool/registry.py` | 不动(过滤逻辑在 `filter.py`) |
| 修改 | `src/forgecode/tui/app.py` | `ForgeCodeApp` 加 `task_mgr` / `subagent_catalog`;`on_mount` 起 `_consume_task_done`;Agent 工具注册后 `set_parent` |
| 修改 | `src/forgecode/tui/stream.py` | `_consume_stream` 加 ESC → `adopt_running` 分支 |
| 修改 | `src/forgecode/tui/skill_fork.py` | 改造为调 `agent.launch_fork` |
| 修改 | `tests/tui/test_tui.py` | 补 ESC 切后台、task-notification 注入测试 |
| 修改 | `src/forgecode/config.py` | 加 `enable_subagent_background: bool | None`(默认视为 True) |
| 修改 | `src/forgecode/cli.py` | `load_catalog` / `Manager` / 4 个 task 工具注册 / Agent 工具注册 + `set_parent`;`task_mgr` / `subagent_catalog` 传给 `ForgeCodeApp` |

## T1: subagent 包的 Definition 与 Source 类型**文件:** `src/forgecode/subagent/definition.py`
**依赖:** 无
**步骤:**
1. 新建包 `forgecode.subagent`,加 `definition.py`,声明 `Source(IntEnum)` 与四个常量:
   - `BUILTIN = 0`
   - `USER = 1`
   - `PROJECT = 2`
   - `PLUGIN = 3`(占位)
2. `Source.__str__` 返回 `"builtin" / "user" / "project" / "plugin"`,越界返回 `"unknown"`
3. 声明 `Definition` `@dataclass`,字段如 plan.md 所述:`name / description / tools / disallowed_tools / model / max_turns / permission_mode / dont_ask / background / system_prompt / file_path / source`
4. docstring 标注每个字段语义,引用 spec F4
5. `Definition.is_fork()` 返回 `self.name == "__fork__"`(便于 `fork_definition` 判别)

**验证:** `python -c "from forgecode.subagent.definition import Definition, Source"` 导入无误

## T2: subagent 解析器**文件:** `src/forgecode/subagent/parser.py`
**依赖:** T1
**步骤:**
1. 新建 `parser.py`,从 `skills/parser.py` 复制 `parse_frontmatter_and_body` 与 `UTF8_BOM` 常量(几乎不变,改为 `forgecode.subagent` 包内调用)
2. 声明 `AGENT_NAME_REGEX = re.compile(r"^[A-Za-z][A-Za-z0-9\-_]{0,31}$")`(大小写都允许,与 ch13 README 的 `Explore` / `Plan` 一致)
3. 实现 `parse_definition(data: bytes, file_path: str, source: Source) -> Definition`:
   - 调 `parse_frontmatter_and_body` 拿 frontmatter dict + body
   - YAML 已 `safe_load` 成 `dict[str, Any]`,字段映射:
     ```python
     name = str(fm.get("name", "")).strip()
     description = str(fm.get("description", "")).strip()
     tools = list(fm.get("tools") or [])
     disallowed_tools = list(fm.get("disallowedTools") or [])
     model_str = str(fm.get("model") or "").strip()
     max_turns = int(fm.get("maxTurns") or 0)
     permission_mode_str = str(fm.get("permissionMode") or "").strip()
     background = bool(fm.get("background") or False)
     ```
   - 校验 name 非空且匹配 `AGENT_NAME_REGEX`
   - 校验 description 非空
   - 校验 model:空 / `"inherit"` / `"haiku"` / `"sonnet"` / `"opus"` 之一,其它 stderr 警告并改为 `"inherit"`
   - 解析 permission_mode:`"dontAsk"` 单独识别 → `Definition.dont_ask=True`, `Definition.permission_mode=PermissionMode.DEFAULT`;否则调 `PermissionMode.parse`,失败 stderr 警告并改为 `DEFAULT`
   - 把 fm 字段映射到 Definition 字段(`system_prompt = body`,`file_path = file_path`,`source = source`)
4. 实现 `parse_file(path: str, source: Source) -> Definition`:`pathlib.Path(path).read_bytes()` + `parse_definition`

**验证:** `pytest tests/subagent/test_parser.py -v` 通过(对应 T3 的测试)

## T3: subagent 解析器测试**文件:** `tests/subagent/test_parser.py`
**依赖:** T2
**步骤:**
1. 参数化测试(`pytest.mark.parametrize`):正常完整 frontmatter / 仅必填 / model 非法 → 警告 fallback / `permissionMode=dontAsk` → `dont_ask=True` / 缺 name 抛 ValueError / 缺 description 抛 ValueError / frontmatter 未关闭 → 抛错
2. body 区段提取:验证 `---` 后的内容(去 BOM 去前导换行)被完整取到 `system_prompt`
3. 测试 `parse_file` 读取一个 `tests/subagent/testdata/*.md` 文件
4. 用 `capsys` 捕获 stderr 验证 fallback 时的警告输出

**验证:** `pytest tests/subagent/test_parser.py -v` 全部通过

## T4: 内置 Agent 定义文件**文件:** `src/forgecode/subagent/builtin/{general-purpose,explore,plan}.md`
**依赖:** 无
**步骤:**
1. 创建目录 `src/forgecode/subagent/builtin/`
2. `general-purpose.md`:
   ```yaml
   ---
   name: general-purpose
   description: 通用子 Agent,拥有全部工具,用于需要完整能力但独立上下文的场景
   maxTurns: 30
   ---

   你是 ForgeCode 的通用 Agent。根据用户的消息,使用可用工具完成任务。
   把任务做完,不要过度设计,但也不要做一半就停。
   完成后用简洁的报告回复:做了什么、关键发现。
   调用方会把结果转述给用户,所以只需要包含要点。
   ```
3. `explore.md`:
   ```yaml
   ---
   name: Explore
   description: 只读代码探索 Agent,适合搜索、阅读、理清调用链;不能修改文件
   disallowedTools:
     - write_file
     - edit_file
   model: haiku
   maxTurns: 30
   ---

   你是一个文件搜索专家。这是一个只读探索任务。
   严禁:创建文件、修改文件、删除文件、执行任何改变系统状态的命令。
   工具策略:Glob 做文件模式匹配、Grep 搜索文件内容、Read 读取已知路径、Bash 仅用于只读操作(ls、git log、find、cat)。
   尽可能并行发起多个工具调用。高效完成搜索请求,清晰报告发现。
   ```
4. `plan.md`:
   ```yaml
   ---
   name: Plan
   description: 计划 Agent,分析需求、制定执行计划,但不直接执行;主 Agent 拿到计划后逐步执行
   disallowedTools:
     - write_file
     - edit_file
     - Agent
   maxTurns: 15
   permissionMode: plan
   ---

   你是一个软件架构师和规划专家。这是一个只读规划任务。
   严禁:创建文件、修改文件、删除文件、执行任何改变系统状态的命令。
   工作流程:① 理解需求 ② 用搜索工具充分探索代码库 ③ 设计方案 ④ 输出分步实现计划。
   回复末尾必须列出 3-5 个对实现最关键的文件路径。
   ```
5. 在 `pyproject.toml` 的 `[tool.hatch.build.targets.wheel]` 或 `[tool.setuptools.package-data]` 中确保 `*.md` 被打包进 wheel(hatch 默认包含同包目录下任意文件,通常不需要额外配置)

**验证:** 三个 `.md` 文件存在,frontmatter 合法;`parse_file` 测试不报错

## T5: subagent embed 与内置加载**文件:** `src/forgecode/subagent/embed.py`
**依赖:** T2, T4
**步骤:**
1. 新建 `embed.py`,导入:
   ```python
   from importlib.resources import files
   ```
2. 实现 `builtin_definitions() -> list[Definition]`:
   - `pkg = files("forgecode.subagent.builtin")`
   - 遍历 `pkg.iterdir()`,过滤 `name.endswith(".md")`
   - 对每个文件:`data = (pkg / name).read_bytes()` + `parse_definition(data, f"builtin:{name}", Source.BUILTIN)`
   - 解析失败 raise(代码 bug,启动期失败即灾难)
3. 返回按 `name` 升序的 list

**验证:** `pytest tests/subagent/test_catalog.py::test_builtin -v` 通过(T7)

## T6: Catalog 与三层加载**文件:** `src/forgecode/subagent/catalog.py`
**依赖:** T1, T2, T5
**步骤:**
1. 新建 `catalog.py`,声明 `Catalog` 类(见 plan.md)
2. 实现 `load_catalog(root: str) -> Catalog`:
   ```python
   c = Catalog()
   c._add_all(builtin_definitions(), Source.BUILTIN)
   c._add_all(_load_from_dir(Path.home() / ".forgecode/agents", Source.USER), Source.USER)
   c._add_all(_load_from_dir(Path(root) / ".forgecode/agents", Source.PROJECT), Source.PROJECT)
   return c
   ```
3. 实现 `_load_from_dir(dir: Path, source: Source) -> list[Definition]`:
   - 目录不存在 → 返回 `[]`
   - 遍历 `dir.glob("*.md")`,逐个 `parse_file`;失败 stderr 警告并跳过
   - 返回 list
4. 实现 `Catalog._add_all(defs: list[Definition], source: Source)`:
   - 同名时高优先级覆盖(因为按 builtin → user → project 顺序加载,后加的优先级更高)
   - 同时往 `self._by_source[source]` 追加
5. 实现 `resolve(name: str) -> Definition | None`
6. 实现 `list() -> list[Definition]`(按 name 升序)
7. 实现 `list_by_source(s: Source) -> list[Definition]`
8. 实现 `fork_definition() -> Definition`:
   ```python
   return Definition(
       name="__fork__",
       description="Fork-based subagent",
       model="inherit",
       max_turns=25,
       permission_mode=PermissionMode.DEFAULT,
       # tools / disallowed_tools 留空 -> 工具集继承父
   )
   ```

**验证:** `pytest tests/subagent/test_catalog.py -v` 通过

## T7: Catalog 测试**文件:** `tests/subagent/test_catalog.py`
**依赖:** T6
**步骤:**
1. 测试 `builtin_definitions` 返回 3 个 def(general-purpose / Explore / Plan)
2. 测试三层覆盖:用 `tmp_path` fixture 造一个项目 root 与一个 HOME 路径(用 `monkeypatch.setenv("HOME", ...)`),分别放 `explore.md`
3. 验证 `resolve("Explore")` 在三种情形下返回的 `source` 正确(都有 → project;只有 user+builtin → user;只有 builtin → builtin)
4. 测试 `fork_definition` 返回 `is_fork() is True`
5. 测试加载错误处理:放一个非法 frontmatter 文件,加载后该文件 *被跳过*,其他文件仍正常(用 `capsys` 验证 stderr 警告)

**验证:** `pytest tests/subagent/ -v` 全部通过

## T8: 工具过滤多层防线**文件:** `src/forgecode/tool/filter.py`
**依赖:** 无
**步骤:**
1. 新建 `filter.py`,声明三个全局常量:
   ```python
   ALL_AGENT_DISALLOWED_TOOLS: list[str] = ["Agent"]
   CUSTOM_AGENT_DISALLOWED_TOOLS: list[str] = []
   ASYNC_AGENT_ALLOWED_TOOLS: list[str] = [
       "read_file", "write_file", "edit_file",
       "glob", "grep",
       "bash",
       "load_skill", "install_skill",
   ]
   ```
2. 声明 `FilterParams` `@dataclass`:
   ```python
   @dataclass
   class FilterParams:
       all: list[str]                    # registry 的全部工具名
       source: int                       # 1=builtin, 2=user, 3=project, 4=plugin(与 subagent.Source 对齐)
       background: bool
       allowed: list[str] = field(default_factory=list)   # Agent 定义的 tools 白名单
       disallowed: list[str] = field(default_factory=list)  # Agent 定义的 disallowedTools 黑名单
   ```
3. 实现 `apply_agent_tool_filter(p: FilterParams) -> list[str]`:
   按 spec F30 顺序:
   - 起点 = `p.all` 副本
   - 过滤 1:去除 `ALL_AGENT_DISALLOWED_TOOLS`
   - 过滤 2:若 `p.source >= 2`(非 builtin),再去除 `CUSTOM_AGENT_DISALLOWED_TOOLS`(本期为空,跳过)
   - 过滤 3:若 `p.background`,与 `ASYNC_AGENT_ALLOWED_TOOLS + is_mcp_or_skill(name)` 取交集
   - 过滤 4:去除 `p.disallowed`
   - 过滤 5:若 `len(p.allowed) > 0`,与之取交集
4. 辅助函数 `is_mcp_or_skill(name: str) -> bool`:`name.startswith("mcp__")`(对 skill 工具的识别本期暂不接入,Registry 不区分,先按名字前缀 + 内置基础工具白名单兜底)

**验证:** `python -c "from forgecode.tool.filter import apply_agent_tool_filter"` 导入无误

## T9: 工具过滤测试**文件:** `tests/tool/test_filter.py`
**依赖:** T8
**步骤:**
1. 参数化测试 `apply_agent_tool_filter` 覆盖各组合:
   - 默认:无后台、无白名单、无黑名单 → 去 Agent 即可
   - 后台:取 `ASYNC_AGENT_ALLOWED_TOOLS` 交集
   - 黑名单:`disallowed=["bash"]` → 不含 bash
   - 白名单:`allowed=["read_file", "grep"]` → 仅这两个
   - 黑 + 白:白名单先收窄,黑名单再剔除
   - 后台 + MCP 工具:MCP 工具(`mcp__xxx`)被保留(白名单 OK)
2. 单独测试 `is_mcp_or_skill` 边界

**验证:** `pytest tests/tool/test_filter.py -v` 通过

## T10: Agent 类扩展 - 新增构造参数**文件:** `src/forgecode/agent/agent.py`
**依赖:** 无
**步骤:**
1. 在 `Agent.__init__` 加关键字参数(与默认值):
   ```python
   def __init__(
       self,
       ...,  # 原有
       system_prompt: str | None = None,
       max_turns: int = 0,                                  # 0 = 用全局 MAX_ITERATIONS
       permission_mode: PermissionMode | None = None,        # None = 用 TUI 运行时模式
       dont_ask: bool = False,
       approval_upgrader: ApprovalUpgrader | None = None,
       provider: Provider | None = None,                     # None = 用默认 provider
   ) -> None:
       self.system_prompt = system_prompt
       self.max_turns = max_turns
       self.permission_mode = permission_mode
       self.dont_ask = dont_ask
       self.approval_upgrader = approval_upgrader
       if provider is not None:
           self.provider = provider
   ```
2. 在 docstring 解释每个选项语义
3. 注意 `permission_mode is None` 与 `dont_ask=False` 都表示"未设置";`permission_mode` 一旦 != None 表示子 Agent 显式指定,覆盖 TUI 运行时模式

**验证:** `python -c "from forgecode.agent.agent import Agent; Agent.__init__"` 无 TypeError

## T11: ApprovalUpgrader 类型**文件:** `src/forgecode/agent/permission_upgrade.py`
**依赖:** T10
**步骤:**
1. 新建文件,声明:
   ```python
   from typing import Awaitable, Callable
   from forgecode.permission import PermissionOutcome
   from forgecode.agent.approval import ApprovalRequest

   ApprovalUpgrader = Callable[
       [ApprovalRequest],
       Awaitable[tuple[PermissionOutcome, bool]],
   ]
   ```
2. docstring 解释:子 Agent 把审批请求升级到父 TUI 的回调;返回 `(outcome, ok)`——`ok=False` 时调用方应走默认 emit Approval 路径

**验证:** `python -c "from forgecode.agent.permission_upgrade import ApprovalUpgrader"` 导入无误

## T12: Fork 路径辅助函数**文件:** `src/forgecode/agent/fork.py`
**依赖:** 无(纯函数)
**步骤:**
1. 新建 `fork.py`,声明常量:
   ```python
   FORK_BOILERPLATE_TAG = "<fork_boilerplate>"

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
   ```
2. 实现 `build_forked_messages(parent_msgs: list[Message], task: str) -> list[Message]`:
   - 深拷贝 `parent_msgs`(用 `copy.deepcopy` 或者手动 `Message(...)` 复制)
   - 扫描末尾 assistant 消息的 `tool_calls`:对于每个未配对的 `tool_call_id`,在 cloned 末尾追加 RoleTool 消息(每个 ID 一条 placeholder `ToolResult(content="[forked, skipped]", is_error=True)`)
     - 配对检查:看看 cloned 后续是否有 RoleTool 消息消费这些 ID
   - 追加最后一条 user 消息:`content = FORK_BOILERPLATE + task`
3. 实现 `is_fork_context(msgs: list[Message]) -> bool`:
   - 遍历 msgs,若 user / tool / assistant 消息内容含 `FORK_BOILERPLATE_TAG` → 返回 True
   - 默认 False

**验证:** `pytest tests/agent/test_fork.py -v` 通过(T13)

## T13: Fork 辅助函数测试**文件:** `tests/agent/test_fork.py`
**依赖:** T12
**步骤:**
1. 测试 `build_forked_messages` 空 parent → 返回单条 user 消息含 Boilerplate + task
2. 测试 parent 末尾有完整 assistant + tool_result 配对:cloned 末尾 == parent 末尾 + 一条 user
3. 测试 parent 末尾 assistant 有 2 个 tool_use 没配对:cloned 中追加 1 条 RoleTool(2 个 placeholder tool_result)再追加 1 条 user
4. 测试 `is_fork_context`:消息中含 Boilerplate → True;不含 → False

**验证:** `pytest tests/agent/test_fork.py -v` 通过

## T14: `_run_guarded` 加 dont_ask 短路与 approval_upgrader**文件:** `src/forgecode/agent/agent.py`
**依赖:** T10, T11
**步骤:**
1. 修改 `_run_guarded`,在 `case PermissionDecision.ASK` 分支里:
   ```python
   if decision is PermissionDecision.ASK:
       # 子 Agent dontAsk 模式:直接 Allow
       if self.dont_ask:
           return await self._run_tool(c), True

       # 子 Agent 升级到父 TUI 审批
       if self.approval_upgrader is not None:
           req = ApprovalRequest(
               name=c.name,
               args=args_preview(c.input),
               reason=reason,
               respond=None,  # upgrader 内部处理 respond
           )
           outcome, ok = await self.approval_upgrader(req)
           if ok:
               match outcome:
                   case PermissionOutcome.ALLOW_ONCE:
                       return await self._run_tool(c), True
                   case PermissionOutcome.ALLOW_FOREVER:
                       self.engine.persist_local_allow(c)
                       return await self._run_tool(c), True
                   case _:
                       return deny_result(c.id, "用户拒绝了本次调用"), True

       # 默认路径:emit Approval event(主 Agent inline / Skill fork 都走此)
       outcome, ok = await self._request_approval(c, reason, queue)
       ...
   ```
2. 修改 `check` 调用前,如果子 Agent 设了 `permission_mode`(`self.permission_mode is not None`),用 `self.permission_mode` 覆盖入参 mode
3. 修改 `_stream_loop` 拿 defs 处的 `allowed_tools` 逻辑(已有,无须改)

**验证:** `pytest tests/agent/ -v` 现有测试不破

## T15: run_to_completion 实现**文件:** `src/forgecode/agent/run_to_completion.py`
**依赖:** T10, T14
**步骤:**
1. 新建文件,实现挂到 `Agent` 上的方法:
   ```python
   async def run_to_completion(
       self,
       conv: Conversation,
       task: str,
       events: asyncio.Queue | None = None,
   ) -> str: ...
   ```
2. 逻辑:
   - 把 task 作为 user 消息:`if task: conv.add_user(task)`(注意 conv 可能已经被 Fork 路径预装填)
   - 计算 max_turns:`turns = self.max_turns or MAX_ITERATIONS`
   - 复用 `run` 的循环逻辑:但不用队列返回事件,直接内部消费;改为返回 final_text + raise
   - 拆出 helper `_run_iter(conv, mode, iter_idx, defs, sys, env_text, reminder, events_queue) -> tuple[text, calls, done]` 让 `run` 和 `run_to_completion` 都调
   - `run` 改造为调 `_run_iter` 逐轮;`run_to_completion` 也是
   - 子 Agent 用模式:`mode = self.permission_mode or PermissionMode.DEFAULT`
3. 退出条件:`done=True`(模型不再调工具)→ 返回 final_text;触达 turns → raise `MaxTurnsReached(final_text)`;`asyncio.CancelledError` → 透传(`raise`);出错 → raise(由 launch 协程的 try/except 兜底)
4. 在每轮内继续做 hook 调度(PreToolUse / PostToolUse / Stop 等),但 SubAgent 不触发 memory update
5. events 队列转发:把 Tool / Text / Approval 事件 `put_nowait` 进去(供 TaskManager / TUI 接收)

**验证:** `pytest tests/agent/test_run_to_completion.py -v` 通过(T16)

## T16: run_to_completion 测试**文件:** `tests/agent/test_run_to_completion.py`
**依赖:** T15
**步骤:**
1. 用 mock provider(已有 test helpers)模拟一个回合返回纯文本的子 Agent → `run_to_completion` 返回 `"ok"`,无异常
2. 模拟一个回合返回 tool_use(已知工具),下一轮返回纯文本 → 工具被执行、final_text 正确
3. 模拟模型一直调工具不出文本,触达 max_turns=3 → raise `MaxTurnsReached`
4. 测试 dont_ask:子 Agent 设 `dont_ask=True` + 模型调一个 Ask 级工具(如 bash) → 工具被自动放行执行
5. 测试 approval_upgrader 回调被命中:子 Agent 设了 upgrader,Ask 时 upgrader 被调用(用 mock upgrader 验证)
6. 测试 events 队列转发:运行子 Agent 时把 events 收集到 list,断言含 Tool / Text 事件

**验证:** `pytest tests/agent/test_run_to_completion.py -v` 全部通过

## T17: Agent 工具实现**文件:** `src/forgecode/agent/agent_tool.py`
**依赖:** T8, T12, T15
**步骤:**
1. 新建文件,声明:
   ```python
   from typing import Protocol

   class AgentCatalog(Protocol):
       def resolve(self, name: str) -> Definition | None: ...
       def fork_definition(self) -> Definition: ...
       def list(self) -> list[Definition]: ...

   class TaskManager(Protocol):
       async def launch(self, ag: "Agent", conv: "Conversation",
                        name: str, task: str) -> str: ...
       async def adopt_running(self, ag: "Agent", conv: "Conversation",
                               name: str, events: asyncio.Queue,
                               handle: asyncio.Task, partial: PartialState) -> str: ...
       async def upgrade_approval(self, req: ApprovalRequest) -> tuple[PermissionOutcome, bool]: ...

   @dataclass
   class AgentArgs:
       prompt: str
       description: str
       subagent_type: str = ""
       model: str = ""
       run_in_background: bool = False
       name: str = ""

   class AgentTool(Tool):
       def __init__(self, catalog: AgentCatalog, task_mgr: TaskManager,
                    parent: "Agent | None", bg_enabled: bool) -> None: ...
   ```
2. **解决循环依赖**:agent 包要引用 subagent 包,但 subagent 不应反过来。检查 `subagent.Definition` 是否引用 agent 包——目前 `Definition` 只引用 `permission` 包,没问题。直接 `from forgecode.subagent import Definition`(或用 Protocol 解耦)
3. **AgentTool 接口实现**:
   - `name` 属性 = `"Agent"`
   - `description()` 动态:基础描述 + `"subagent_type 可选值: " + ", ".join(d.name for d in catalog.list())`
   - `parameters()`:按 spec F1 写 JSON Schema dict
   - `read_only` 属性 = `False`
   - `async def execute(self, args: dict, ctx: ToolContext) -> ToolResult`
4. **execute 主流程**:
   ```python
   a_args = AgentArgs(**args)
   if not a_args.prompt:
       return ToolResult(is_error=True, content="prompt is required")
   if not a_args.description:
       return ToolResult(is_error=True, content="description is required")

   # 防嵌套
   if is_sub_agent_context(ctx):
       return ToolResult(is_error=True, content="subagent cannot spawn Agent")
   parent_conv = get_parent_conv(ctx)
   if parent_conv is not None and is_fork_context(parent_conv.messages()):
       return ToolResult(is_error=True,
                         content="Fork subagent cannot spawn Agent (boilerplate detected)")

   # resolve 定义
   if a_args.subagent_type:
       defi = self.catalog.resolve(a_args.subagent_type)
       if defi is None:
           return ToolResult(is_error=True,
                             content=f"unknown subagent_type: {a_args.subagent_type}")
   else:
       defi = self.catalog.fork_definition()

   # 决定后台
   background = defi.background or a_args.run_in_background or defi.is_fork()
   if background and not self.bg_enabled:
       return ToolResult(is_error=True, content="background mode is disabled by config")

   # 工具过滤
   allowed = apply_agent_tool_filter(FilterParams(
       all=registry_all_names(self.parent.registry),
       source=int(defi.source),
       background=background,
       allowed=defi.tools,
       disallowed=defi.disallowed_tools,
   ))

   # provider(model 字段切换 provider 的逻辑暂从简:本期不实现按模型切换,后续完善)
   provider = self.parent.provider

   # 构造子 Agent
   sub_runtime = SessionRuntime(200_000)
   sub_agent = Agent(
       provider=provider,
       registry=self.parent.registry,
       version=self.parent.version,
       engine=self.parent.engine,
       runtime=sub_runtime,
       allowed_tools=allowed,
       system_prompt=defi.system_prompt,
       max_turns=defi.max_turns,
       permission_mode=defi.permission_mode,
       dont_ask=defi.dont_ask,
       approval_upgrader=self.task_mgr.upgrade_approval,
       hook_engine=self.parent.hook_engine,
   )
   # 标记子 Agent 上下文(让递归 Agent 工具调用被拦截)
   child_ctx = with_sub_agent_context(ctx)

   # 子 conv
   sub_conv = Conversation()
   if defi.is_fork():
       parent_msgs = get_parent_conv_messages(ctx, self.parent)
       forked = build_forked_messages(parent_msgs, a_args.prompt)
       sub_conv = Conversation.from_messages(forked)

   # 后台路径
   if background:
       task_id = await self.task_mgr.launch(sub_agent, sub_conv,
                                            a_args.name, a_args.prompt)
       return ToolResult(content=json.dumps(
           {"task_id": task_id, "status": "async_launched"}))

   # 前台路径
   events: asyncio.Queue = asyncio.Queue(maxsize=32)
   partial = PartialState()
   aggregator = asyncio.create_task(aggregate_partial(events, partial))
   try:
       final_text = await asyncio.wait_for(
           sub_agent.run_to_completion(sub_conv, a_args.prompt, events),
           timeout=AUTO_BACKGROUND_SECONDS,
       )
   except asyncio.TimeoutError:
       running = asyncio.create_task(
           sub_agent.run_to_completion(sub_conv, "", events))
       task_id = await self.task_mgr.adopt_running(
           sub_agent, sub_conv, a_args.name, events, running, partial,
       )
       return ToolResult(content=json.dumps(
           {"task_id": task_id, "status": "timed_out_to_background"}))
   except Exception as e:
       return ToolResult(is_error=True, content=f"subagent error: {e}")
   finally:
       aggregator.cancel()
       await events.put(None)  # 触发 aggregator 收尾

   return ToolResult(content=final_text)
   ```
5. 实现辅助函数:`is_sub_agent_context / with_sub_agent_context / get_parent_conv_messages / aggregate_partial`
6. 提供 `set_parent(self, ag: "Agent") -> None` 让 cli 在 `ForgeCodeApp` 构造之后回填 parent 引用

**验证:** `pytest tests/agent/test_agent_tool.py -v` 通过(T18)

## T18: Agent 工具测试**文件:** `tests/agent/test_agent_tool.py`
**依赖:** T17
**步骤:**
1. 测试 missing prompt → 返回错误
2. 测试 unknown subagent_type → 返回错误
3. 测试 known subagent_type(用一个 mock catalog 注入)→ 子 Agent 跑动并返回结果
4. 测试 `run_in_background=True` → 返回 `async_launched` JSON
5. 测试嵌套:用 `with_sub_agent_context` 包 ctx 后调 `execute` → 返回错误
6. 测试 `is_fork_context` 兜底:用 forked sub_conv 调,Agent 工具拦截
7. 测试 `enable_subagent_background=False` 时 background 路径报错

**验证:** `pytest tests/agent/test_agent_tool.py -v` 全部通过

## T19: task 包基础结构**文件:** `src/forgecode/task/manager.py`
**依赖:** T10, T15
**步骤:**
1. 新建包 `forgecode.task`,加 `__init__.py` 与 `manager.py`
2. 声明 `Status(IntEnum)` 与四个常量:`RUNNING / COMPLETED / FAILED / CANCELLED`
3. 声明 `Usage` `@dataclass`(对齐 `agent.Usage`)
4. 声明 `BackgroundTask` `@dataclass`(字段如 plan.md)
5. 声明 `PartialState` `@dataclass`
6. 声明 `Manager` 类:`_lock: asyncio.Lock; _tasks: dict[str, BackgroundTask]; _by_name: dict[str, str]; _done: asyncio.Queue[str]; _counter: int`
7. 实现 `__init__`:`self._done = asyncio.Queue(maxsize=32)`,counter=0
8. 实现 `_next_id() -> str`:`self._counter += 1` 后格式化为 `"task_" + secrets.token_hex(4)`(或 `f"{time.time_ns() ^ self._counter:08x}"` 取低 4 字节即可)
9. 实现 `get(id)` / `list()` / `subscribe_done()` 等查询方法

**验证:** `python -c "from forgecode.task.manager import Manager"` 导入无误

## T20: Manager.launch 实现**文件:** `src/forgecode/task/manager.py`
**依赖:** T19
**步骤:**
1. 实现:
   ```python
   async def launch(self, ag: Agent, conv: Conversation,
                    name: str, task_text: str) -> str:
       task_id = self._next_id()
       bt = BackgroundTask(
           id=task_id, name=name, sub_agent=ag, conv=conv, task=task_text,
           status=Status.RUNNING, start_time=time.monotonic(),
       )

       async with self._lock:
           self._tasks[task_id] = bt
           if name:
               self._by_name[name] = task_id  # 后启动覆盖前

       events: asyncio.Queue = asyncio.Queue(maxsize=64)
       aggregator = asyncio.create_task(self._aggregate_task_events(events, bt))

       async def runner() -> None:
           try:
               text = await ag.run_to_completion(conv, task_text, events)
               bt.result = text
               bt.status = Status.COMPLETED
           except asyncio.CancelledError:
               bt.status = Status.CANCELLED
               raise
           except BaseException as e:
               bt.status = Status.FAILED
               bt.err = e
           finally:
               bt.end_time = time.monotonic()
               aggregator.cancel()
               try:
                   self._done.put_nowait(task_id)
               except asyncio.QueueFull:
                   print(f"task manager: done queue full, dropping notification for {task_id}",
                         file=sys.stderr)

       bt.handle = asyncio.create_task(runner())
       return task_id
   ```
2. 实现 `_aggregate_task_events(queue: asyncio.Queue, bt: BackgroundTask)`:每个 Tool PhaseStart 累加 `tool_count` + 更新 `last_activity`;每个 Usage 累加到 `bt.usage`

**验证:** `pytest tests/task/test_manager.py::test_launch -v` 通过(T22)

## T21: Manager.stop / adopt_running / send_message / upgrade_approval**文件:** `src/forgecode/task/manager.py`
**依赖:** T20
**步骤:**
1. 实现 `async def stop(self, task_id: str) -> bool`:查 `_tasks` → 调 `bt.handle.cancel()`;返回是否找到
2. 实现 `async def adopt_running(...)`:与 `launch` 类似但接收已存在的 `ag` / `conv` / `events` / `handle` / `partial`;创建 `BackgroundTask`,把 `PartialState` 字段复制进去,起协程继续消费 events 并跑动(注意此时 `ag.run_to_completion` 已经在前台启动;前台超时后子协程仍然在跑;adopt 实际上是注册 BackgroundTask 状态、聚合事件、等 events 队列关闭后写终态、push done)
   - 简化方案:adopt 不重新调 `run_to_completion`(因为已在前台启动);只是注册 BackgroundTask 状态、聚合事件、等 events 队列收到 sentinel 后写终态、push done
   - `handle` 是 `asyncio.create_task` 返回的 Task,stop 时 `handle.cancel()`
3. 实现 `async def send_message(self, name: str, message: str) -> str`:
   - 查 `_by_name` → task_id
   - 查 `get(task_id)` → bt;`bt.status != COMPLETED` → raise `TaskBusy`
   - `bt.conv.add_user(message)`;`bt.status = Status.RUNNING`;`start_time` / `end_time` 不重置
   - 重新起协程跑 `run_to_completion`(同样的 ag / conv);跑完逻辑同 launch
   - 返回 task_id
4. 实现 `async def upgrade_approval(self, req: ApprovalRequest) -> tuple[PermissionOutcome, bool]`:把 req 转发到一个全局队列(`self._approval_q: asyncio.Queue[ApprovalRequest]`);TUI 消费;返回 `(_, False)` 时调用方走默认路径
   - 简化:本期 `upgrade_approval` 直接返回 `(PermissionOutcome.DENY_ONCE, False)`——让 Approval 走到子 Agent 自己的 events 队列,TUI 通过 events 转发感知

**验证:** `pytest tests/task/test_manager.py::test_stop -v` 通过

## T22: task 包测试**文件:** `tests/task/test_manager.py`
**依赖:** T20, T21
**步骤:**
1. 用 mock provider + mock agent 模拟一个 sub_agent → `launch` → 等 `subscribe_done().get()` → 验证 `status=COMPLETED`, `result` 正确
2. 用一个故意抛异常的 mock agent → `launch` → done 收到 → `status=FAILED`,`err` 非空
3. `stop`:`launch` 后立刻 `stop` → done 收到 → `status=CANCELLED`
4. `send_message`:`launch` + 等 `COMPLETED` → `send_message` 重新跑 → 拿到新结果
5. `_by_name` 覆盖:`launch` 两次同 name → 后启动覆盖

**验证:** `pytest tests/task/test_manager.py -v` 全部通过

## T23: 4 个后台任务工具**文件:** `src/forgecode/task/tools.py`
**依赖:** T19, T20, T21
**步骤:**
1. 实现 `TaskListTool(Tool)`:
   - `name = "TaskList"`,`read_only = True`,`parameters()` 空对象
   - `execute`:返回 JSON 形如 `[{"id":"...","name":"...","status":"running","tool_count":3,"last_activity":"bash"}, ...]`
2. 实现 `TaskGetTool(Tool)`:
   - `name = "TaskGet"`,`parameters()` 含 `task_id` required
   - `execute`:`get(id)` → 全字段 JSON;找不到 → `is_error=True`
3. 实现 `TaskStopTool(Tool)`:
   - `name = "TaskStop"`,`parameters()` 含 `task_id` required
   - `execute`:`await m.stop(id)` → `{"status":"cancellation_requested"}` 或 错误
4. 实现 `SendMessageTool(Tool)`:
   - `name = "SendMessage"`,`parameters()` 含 `name` / `message` required
   - `execute`:`await m.send_message(ctx, name, msg)` → `{"task_id":"...","status":"resumed"}` 或 错误
5. 所有工具实现 `is_system` 属性(返回 True),让它们在子 Agent 工具列表中默认豁免

**验证:** `pytest tests/task/test_tools.py -v` 通过(T24)

## T24: 4 个工具的单测**文件:** `tests/task/test_tools.py`
**依赖:** T23
**步骤:**
1. TaskList:`launch` 几个任务后调 → 返回 JSON 含所有
2. TaskGet:已知 id → 返回完整字段
3. TaskGet:未知 id → `is_error=True`
4. TaskStop:`stop` 一个 running task → 返回成功 + task 状态变 `CANCELLED`
5. SendMessage:`launch` 一个任务跑完 → `send_message` → 返回新 status

**验证:** `pytest tests/task/ -v` 全部通过

## T25: TUI 加 task_mgr / subagent_catalog wiring**文件:** `src/forgecode/tui/app.py`
**依赖:** T6, T19, T23
**步骤:**
1. 在 `ForgeCodeApp.__init__` 加形参:
   ```python
   def __init__(self, ..., task_mgr: task.Manager,
                subagent_catalog: subagent.Catalog) -> None:
       super().__init__()
       self.task_mgr = task_mgr
       self.subagent_catalog = subagent_catalog
   ```
2. 在 `on_mount()` 内:
   - 启动 `asyncio.create_task(self._consume_task_done())`
3. 在 `Agent` 构造之后(单 provider 路径):
   - 主 Agent 也应该携带 `approval_upgrader`(其实主 Agent 不需要;但 Agent 工具构造时需要 `approval_upgrader` 给子 Agent 用)
   - Agent 工具的 parent 通过 `set_parent(self.main_agent)` 回填

**验证:** `python -c "from forgecode.tui.app import ForgeCodeApp"` 导入无误

## T26: task notification 注入**文件:** `src/forgecode/tui/tasks.py`
**依赖:** T19, T25
**步骤:**
1. 新建文件,实现:
   ```python
   async def consume_task_done(self) -> None:
       q = self.task_mgr.subscribe_done()
       while True:
           task_id = await q.get()
           bt = self.task_mgr.get(task_id)
           if bt is None:
               continue
           notif = build_task_notification(bt)
           if self.runtime is not None:
               self.runtime.append_reminders([notif])
   ```
2. 实现 `build_task_notification(bt: BackgroundTask) -> str`:
   ```
   <task-notification>
   Task <id> (name="<name>"): <status>
   Result: <result 或 错误>
   </task-notification>
   ```
3. docstring 解释行为(F19)
4. 把方法 `_consume_task_done` 挂到 `ForgeCodeApp` 上(单独文件模块化,然后在 `app.py` `from .tasks import consume_task_done`)

**验证:** `python -c "from forgecode.tui.tasks import build_task_notification"` 导入无误

## T27: ESC 切后台**文件:** `src/forgecode/tui/stream.py`
**依赖:** T19, T25
**步骤:**
1. 在 `ForgeCodeApp` 类挂 Textual binding:
   ```python
   BINDINGS = [("escape", "esc_pressed", "Cancel / send to background")]

   async def action_esc_pressed(self) -> None:
       if self.state is SessionState.STREAMING and self.foreground_sub_agent is not None:
           # 移交后台
           task_id = await self.task_mgr.adopt_running(
               self.foreground_sub_agent.agent,
               self.foreground_sub_agent.conv,
               self.foreground_sub_agent.name,
               self.foreground_sub_agent.events,
               self.foreground_sub_agent.handle,
               self.foreground_sub_agent.partial,
           )
           self.foreground_sub_agent = None
           # 显示一条通知
           self.notify(f"[esc] 子 Agent 切到后台 (task={task_id})")
   ```
2. 增加 `foreground_sub_agent` 字段到 `ForgeCodeApp` 跟踪当前前台子 Agent;Agent 工具开始前台跑动时设置,跑完清除
3. 注意:前台子 Agent 的跑动其实是在 Agent 工具的 `execute` 内 `await` 阻塞的,主 TUI 此时是 "等 tool_result" 状态。这意味着 ESC 拦截需要在 Agent 工具的 `execute` 内通过 `self.foreground_sub_agent` 共享状态

**简化方案:** 由于前台子 Agent 在 Agent 工具同步 `await` 阻塞内,ESC 切后台需要工具内监听 cancellation。本期实现保守版:Agent 工具的前台路径只支持「超时自动切后台」,不支持 ESC 切后台;ESC 切后台留待后续 ch14+ 完善。在 plan.md 与 spec.md 里要标注这一变更。

**重要变更:** F17/AC11 调整为:本期 ESC 切后台**不实现**,只实现「超时自动切后台」与「显式 run_in_background」。spec.md 已写出,checklist 跳过 ESC 场景。

修改方向:跳过 T27 的 ESC 部分,只保留 `foreground_sub_agent` 字段供未来扩展。

**验证:** `python -c "import forgecode.tui.stream"` 导入无误

## T28: Skill fork 改造**文件:** `src/forgecode/tui/skill_fork.py`
**依赖:** T15
**步骤:**
1. 现有 `run_sub_agent` 内部已经在用 `sub_agent.run`;改造为用 `run_to_completion`:
   ```python
   async def run_sub_agent(self, conv: Conversation,
                           opts: skills.ForkOptions) -> str:
       if self.provider is None:
           raise SubAgentNoProvider()

       prov = self.provider
       # (model 切换逻辑保留)

       sub_runtime = SessionRuntime(200_000)
       sub_agent = Agent(
           provider=prov,
           registry=self.registry,
           version=self.version,
           engine=self.engine,
           runtime=sub_runtime,
           allowed_tools=opts.allowed_tools,
           hook_engine=self.hook_engine,
       )

       # 直接调 run_to_completion(events=None,前台同步)
       return await sub_agent.run_to_completion(conv, "", events=None)
       # conv 末尾已含 user task,task="" 触发 run_to_completion 跳过 add_user
   ```
2. **注意**:现有 `skills.Executor` 调用前已经把任务作为 user 消息装填到 conv(`_build_fork_conversation` 末尾 `conv.add_user(rendered)`)。新版 `run_to_completion` 内部又会 `conv.add_user(task)`;若 task="" 会追加空消息。**改 `run_to_completion` 为允许 task="" 时不追加**(`if task: conv.add_user(task)`),或者改 `skills.Executor` 不再装填 user 消息让 `run_to_completion` 装填
3. 选第一种方案——`run_to_completion` 加 if 判断

**验证:** `pytest tests/skills/ tests/tui/ -v` 现有测试不破

## T29: Agent 工具注册到 registry**文件:** `src/forgecode/cli.py`
**依赖:** T17, T20, T23, T25
**步骤:**
1. 在 `cli.main` 适当位置(`skills.load_catalog` 之后):
   ```python
   subagent_catalog = subagent.load_catalog(root)
   task_mgr = task.Manager()

   # 4 个 task 工具
   registry.register(task.TaskListTool(task_mgr))
   registry.register(task.TaskGetTool(task_mgr))
   registry.register(task.TaskStopTool(task_mgr))
   registry.register(task.SendMessageTool(task_mgr))

   # Agent 工具(parent 暂为 None,稍后 set_parent)
   agent_tool = AgentTool(subagent_catalog, task_mgr, parent=None,
                          bg_enabled=cfg.effective_enable_subagent_background())
   registry.register(agent_tool)
   ```
2. `ForgeCodeApp(...)` 构造时传入 `task_mgr` / `subagent_catalog`:
   ```python
   app = ForgeCodeApp(
       ...,
       writer=writer,
       mem_mgr=mem_mgr,
       instruction_text=instruction_text,
       memory_text=memory_text,
       sessions_dir=sessions_dir,
       catalog=catalog,
       hook_engine=hook_engine,
       task_mgr=task_mgr,
       subagent_catalog=subagent_catalog,
   )
   ```
3. `ForgeCodeApp` 构造后回填 parent:
   ```python
   if app.main_agent is not None:
       agent_tool.set_parent(app.main_agent)
   ```
4. `ForgeCodeApp` 加 `main_agent` 属性返回 `self.agent`

**验证:** `python -m forgecode --help` 不报错;`ruff check src/forgecode/cli.py` 无告警

## T30: config 加 enable_subagent_background**文件:** `src/forgecode/config.py`
**依赖:** 无
**步骤:**
1. 在 `Config` `@dataclass` 加字段:
   ```python
   enable_subagent_background: bool | None = None  # YAML key: enableSubAgentBackground
   ```
2. 加 `effective_enable_subagent_background()` 方法:
   ```python
   def effective_enable_subagent_background(self) -> bool:
       if self.enable_subagent_background is None:
           return True
       return self.enable_subagent_background
   ```
3. docstring 说明:默认 True;False 时所有 SubAgent 强制前台,Fork 路径会报错

**验证:** `pytest tests/test_config.py -v` 通过

## T31: agent.launch_fork 公用 wiring**文件:** `src/forgecode/agent/launch.py`
**依赖:** T6, T15, T17
**步骤:**
1. 新建 `launch.py`,实现:
   ```python
   @dataclass
   class ForkLaunchOpts:
       allowed_tools: list[str]
       model: str
       conv: Conversation       # 已装填的子对话
       system_prompt: str
       background: bool
       events_sink: asyncio.Queue | None
       provider: Provider
       registry: Registry
       engine: PermissionEngine
       version: str
       hook_engine: HookEngine

   async def launch_fork(opts: ForkLaunchOpts) -> str: ...
   ```
2. 实现细节:
   - 构造 `SessionRuntime` / `Agent`(类似 `agent_tool` 的前台路径)
   - 调 `run_to_completion(opts.conv, "", events=opts.events_sink)`(conv 已含 task)
   - 返回 final_text(异常透传)
3. **避免循环依赖**:本来 plan 设想 `subagent.launch_fork` 引用 agent 包;但 `agent_tool` 又 import subagent → 形成循环依赖
4. **最终方案**(在文件结构里也已对齐):
   - `Definition` 类型放在 `forgecode.subagent`
   - `launch_fork` 放在 `forgecode.agent`(因为它要构造 `Agent`)
   - `AgentTool` 也放 `forgecode.agent`(已有)
   - `tui/skill_fork.py` 调 `forgecode.agent.launch_fork`(把 `Definition` 或裸参数传入)

**重新调整文件结构:**
- 删除 `src/forgecode/subagent/launch.py`(本任务取消)
- 新建 `src/forgecode/agent/launch.py` 实现 `launch_fork`
- skills 的 fork 回调改为调 `agent.launch_fork`

**验证:** 见 T28 验证

## T32: 集成测试 - 完整路径**文件:** `tests/agent/test_agent_tool_integration.py`(新增)
**依赖:** T17, T20, T29
**步骤:**
1. 端到端 mock:构造一个 mock provider 让主 Agent 调 Agent 工具(`subagent_type="Explore"`),子 Agent 也跑回纯文本
2. 验证 tool_result 包含子 Agent 的 final_text
3. 验证子 Agent 工具调用没看到 Agent 工具(过滤生效)
4. 验证后台路径:`run_in_background=True` → 立即返回 `async_launched` JSON,主 Agent 继续

**验证:** `pytest tests/agent/test_agent_tool_integration.py -v` 通过

## T33: 编译与综合测试**依赖:** T1-T32
**步骤:**
1. `uv sync`(确保依赖装好)
2. `ruff check src/forgecode/`
3. `ruff format --check src/forgecode/`
4. `mypy src/forgecode/`(可选)
5. `pytest tests/ -v`

**验证:** 全部命令通过,无失败用例

## 执行顺序

```
T1 → T2 → T3
       ↘
        T5 → T6 → T7
       ↗
       T4
T8 → T9
T10 → T11 → T14
T10 → T12 → T13
T14, T15 → T16
T8, T12, T15 → T17 → T18
T19 → T20 → T21 → T22
T19 → T20 → T23 → T24
T6, T19, T23 → T25 → T26
T25 → T27(本期跳过 ESC)
T15 → T28
T30 → T29
T29 → T32
所有 → T33
```