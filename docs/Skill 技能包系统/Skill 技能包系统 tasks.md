# Skill 技能包系统 Tasks## 文件清单

| 操作 | 文件 | 职责 |
|------|------|------|
| 新建 | `src/forgecode/skills/__init__.py` | 导出 `Catalog` / `ActiveSkills` / `Executor` / `SkillSource` 等 |
| 新建 | `src/forgecode/skills/types.py` | `SkillMeta` / `Skill` / `SkillSource` / `ToolSpec` / `ActiveEntry` |
| 新建 | `src/forgecode/skills/parser.py` | `parse_skill_dir`, `parse_frontmatter_and_body`, `parse_tool_json` |
| 新建 | `tests/test_skills_parser.py` | 解析路径单测 |
| 新建 | `src/forgecode/skills/catalog.py` | `Catalog`: `load / reload / get / list / names / validate_tools` |
| 新建 | `tests/test_skills_catalog.py` | 三层覆盖单测 |
| 新建 | `src/forgecode/skills/active.py` | `ActiveSkills` 列表 |
| 新建 | `src/forgecode/skills/render.py` | `render_body`（`$ARGUMENTS` + allowed_tools 提示） |
| 新建 | `src/forgecode/skills/adapter.py` | `to_prompt_items` / `to_prompt_entries` |
| 新建 | `src/forgecode/skills/install.py` | `install_from_url` + zip-slip 防护 |
| 新建 | `tests/test_skills_install.py` | zip-slip / 正常 zip 解压单测 |
| 新建 | `src/forgecode/skills/executor.py` | `Executor.execute`（inline / fork 分支） |
| 新建 | `src/forgecode/skills/builtin/__init__.py` | 空包标识，供 `importlib.resources` 寻址 |
| 新建 | `src/forgecode/skills/builtin/commit/SKILL.md` | 内置 commit Skill |
| 新建 | `src/forgecode/skills/builtin/review/SKILL.md` | 内置 review Skill |
| 新建 | `src/forgecode/skills/builtin/test/SKILL.md` | 内置 test Skill |
| 修改 | `src/forgecode/tool/registry.py` | `is_system` 标记 + `definitions_filtered` + `register_skill_tool` |
| 新建 | `src/forgecode/tool/skill_tool.py` | `ToolSpec` 适配为 Tool 实现（asyncio subprocess） |
| 新建 | `src/forgecode/tool/load_skill.py` | LoadSkill 工具实现 |
| 新建 | `src/forgecode/tool/install_skill.py` | InstallSkill 工具实现 |
| 修改 | `src/forgecode/prompt/modules.py` | active-skills → skills-catalog 槽位 |
| 修改 | `src/forgecode/prompt/prompt.py` | `build_system_prompt` 增 catalog 参数 |
| 新建 | `src/forgecode/prompt/skills_block.py` | `render_skills_catalog` / `render_active_skills_block` + 桥接类型 |
| 修改 | `tests/test_prompt.py` | 同步 `build_system_prompt` 签名变更 |
| 修改 | `src/forgecode/command/ui.py` | UI Protocol 新增 4 方法 + NopUI 实现 |
| 修改 | `src/forgecode/command/builtins.py` | 删 /review、改 `handle_clear`、加 /skill 注册 |
| 新建 | `src/forgecode/command/builtin_skill.py` | `handle_skill`（KindLocal 列表输出） |
| 新建 | `src/forgecode/command/skills.py` | `register_skills_as_commands` / `remove_skill_commands` |
| 修改 | `src/forgecode/command/registry.py` | 按命令标记筛选移除入口 |
| 修改 | `src/forgecode/agent/runtime.py` | `SessionRuntime.active_skills` 字段 |
| 修改 | `src/forgecode/agent/agent.py` | `with_catalog` + `run()` 拼装 sys/env + `activate_skill`/`clear_active_skills` |
| 修改 | `src/forgecode/tui/app.py` | App 持有 catalog/executor + 4 个 UI 方法实现 |
| 修改 | `src/forgecode/cli.py` | 启动期接线 |
| 修改 | `pyproject.toml` | 增 `httpx` 依赖；hatch include `**/SKILL.md` 资源 |

## T1: skills 包数据结构**文件**：`src/forgecode/skills/types.py`、`src/forgecode/skills/__init__.py`
**依赖**：无
**步骤**：
1. 定义 `SkillSource(Enum)` 枚举：`BUILTIN / USER / PROJECT`，`value` 分别为 `"builtin" / "user" / "project"`，`__str__` 返回 `self.value`
2. 定义 `@dataclass class SkillMeta` 含 6 个字段（`name`、`description`、`allowed_tools: list[str]=field(default_factory=list)`、`mode: Literal["inline","fork"]="inline"`、`fork_context: Literal["none","recent","full"]="none"`、`model: str | None = None`）
3. 添加 `is_fork(self) -> bool` 方法（`self.mode == "fork"`）
4. 定义 `@dataclass class ToolSpec`（`name`、`description`、`input_schema: dict`、`command: list[str]`、`base_dir: Path`）
5. 定义 `@dataclass class Skill`（`meta`、`prompt_body`、`source_dir: Path`、`source: SkillSource`、`tool_specs: list[ToolSpec]`）
6. 定义 `@dataclass class ActiveEntry`（`name`、`body`）
7. `__init__.py` 暴露上述类型与后续 `Catalog` / `ActiveSkills` / `Executor`（占位 import，后续任务填充）

**验证**：`python -c "from forgecode.skills import SkillMeta, Skill, SkillSource"` 能 import；`ruff check src/forgecode/skills/` 无告警。

## T2: SKILL.md 与 tool.json 解析**文件**：`src/forgecode/skills/parser.py`
**依赖**：T1，需要 `pyyaml`（已在 pyproject 依赖）
**步骤**：
1. `def parse_skill_dir(dir_path: Path, source: SkillSource) -> Skill`：
   - 读 `<dir>/SKILL.md`，找不到抛 `FileNotFoundError(f"no SKILL.md in {dir_path}")`
   - 调 `_parse_frontmatter_and_body(data)` → `(meta_dict, body)`
   - `meta = SkillMeta(**meta_dict)`（用 `dataclasses.fields` 过滤未知键，或显式提取已知键）
   - 校验 `meta.name` 匹配正则 `^[a-z][a-z0-9-]*$` 且长度 1-32
   - 校验 `meta.description` 非空
   - 校验 `meta.mode` 为 `""/"inline"/"fork"`；其它值改 `"inline"` 并 `warnings.warn(...)` 或 `print(..., file=sys.stderr)`
   - 校验 `meta.fork_context` 为 `""/"none"/"recent"/"full"`
   - 读 `<dir>/tool.json`（不存在则跳过），调 `_parse_tool_json` 解析 → `list[ToolSpec]`，`base_dir = dir_path.resolve()`
   - 返回 `Skill(meta, body, dir_path.resolve(), source, tool_specs)`
2. `def _parse_frontmatter_and_body(data: str) -> tuple[dict, str]`：
   - 校验起始是 `---\n`
   - 找下一个 `---\n`，frontmatter = 两者之间，body = 之后
   - `yaml.safe_load(frontmatter)` → dict
3. `def _parse_tool_json(data: bytes, base_dir: Path) -> list[ToolSpec]`：
   - `json.loads` 一个 `{"tools": [{name, description, input_schema, command}, ...]}` 结构
   - 校验每条 name 满足命名规则、command 非空

**验证**：`python -c "from forgecode.skills.parser import parse_skill_dir"` 通过；`ruff check` 无告警。

## T3: 解析单测**文件**：`tests/test_skills_parser.py`
**依赖**：T2
**步骤**：
1. `test_parse_skill_dir_minimal`：用 `tmp_path` 写一个最简 SKILL.md（name+description），expect 解析成功
2. `test_parse_skill_dir_invalid_name`：name 含大写字母 expect `pytest.raises(ValueError)`
3. `test_parse_skill_dir_with_tool_json`：含合法 tool.json，expect `tool_specs` 解析到位
4. `test_parse_skill_dir_no_skill_md`：缺 SKILL.md 抛 `FileNotFoundError`

**验证**：`pytest tests/test_skills_parser.py -v`，所有用例通过。

## T4: Catalog 三层加载与覆盖**文件**：`src/forgecode/skills/catalog.py`
**依赖**：T1, T2
**步骤**：
1. 定义 `class Catalog`，成员：`_lock = threading.RLock()`、`_by_name: dict[str, Skill]`、`_order: list[str]`
2. `def __init__(self)` 构造空
3. `def register(self, s: Skill)`：加锁覆盖、维护 `_order` 不重复（覆盖时位置不变；新增时按 name 字典序插入或追加后排序）
4. `def get(self, name) -> Skill | None`：读锁
5. `def list(self) -> list[Skill]`：读锁，按 `_order` 输出
6. `def names(self) -> list[str]`：读锁
7. `@classmethod def load(cls, work_dir: Path) -> "Catalog"`：
   - 构造空 catalog
   - `_load_builtin_into(catalog)` → 通过 `importlib.resources` 加载（T5 完成 builtin 后接入；本任务先留一个 TODO 桩，跳过 builtin）
   - `_load_dir_into(catalog, Path.home() / ".forgecode" / "skills", SkillSource.USER)`
   - `_load_dir_into(catalog, work_dir / ".forgecode" / "skills", SkillSource.PROJECT)`
8. `def _load_dir_into(c: Catalog, base_dir: Path, source: SkillSource)`：
   - `base_dir.is_dir() is False` 静默跳过
   - 遍历直接子目录，每个调 `parse_skill_dir` 后 `c.register`；解析失败 `print(..., file=sys.stderr)` 跳过
9. `def reload(self, work_dir: Path) -> None`：构造新 catalog，原子替换内部 `_by_name`/`_order`
10. `@dataclass class ValidationIssue { skill_name: str; tool_name: str }`
11. `def validate_tools(self, reg: "ToolRegistry") -> list[ValidationIssue]`：遍历所有 skill 的 `allowed_tools`，逐项查 `reg.get`；未找到记录并 issue。**注意**：把 `load_skill` 与 `install_skill` 视为允许引用（与系统工具豁免逻辑一致）

**验证**：`python -c "from forgecode.skills.catalog import Catalog; print(Catalog().names())"` 通过；先不要在 `load` 中接入 builtin。

## T5: 内置三个 Skill 的资源文件与 importlib.resources**文件**：
- `src/forgecode/skills/builtin/__init__.py`
- `src/forgecode/skills/builtin/commit/SKILL.md`
- `src/forgecode/skills/builtin/review/SKILL.md`
- `src/forgecode/skills/builtin/test/SKILL.md`
- `src/forgecode/skills/embed_builtin.py`
- `pyproject.toml`（增 hatch include）

**依赖**：T4
**步骤**：
1. 写三个 SKILL.md，frontmatter 内容：
   - commit: `name=commit`, `description=分析 git diff 并生成规范的 commit`, `allowed_tools=[bash, read_file, grep]`, `mode=inline`
   - review: `name=review`, `description=客观审查代码变更与潜在问题`, `allowed_tools=[read_file, grep, glob, bash]`, `mode=fork`, `fork_context=none`
   - test: `name=test`, `description=运行项目测试并分析失败原因`, `allowed_tools=[bash, read_file, grep, glob]`, `mode=inline`
   正文按 README 描述的 SOP 写：步骤、注意事项、`$ARGUMENTS` 占位符
2. 新建 `embed_builtin.py`：
   ```python
   from importlib.resources import files
   def _iter_builtin_skill_dirs():
       base = files("forgecode.skills.builtin")
       for entry in base.iterdir():
           if entry.is_dir() and entry.joinpath("SKILL.md").is_file():
               yield entry
   ```
3. 实现 `def _load_builtin_into(c: Catalog) -> None`：
   - 遍历 `_iter_builtin_skill_dirs()`
   - 对每个把资源内容（SKILL.md，如有 `tool.json` / `references/`）写到 `Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "forgecode" / "builtin-skills" / <name>/`
   - 解压完后调 `parse_skill_dir(<cache_dir>, SkillSource.BUILTIN)` 加载
4. 在 `Catalog.load` 中调 `_load_builtin_into`
5. `pyproject.toml` 增加（hatch 后端）：
   ```toml
   [tool.hatch.build.targets.wheel.force-include]
   "src/forgecode/skills/builtin" = "forgecode/skills/builtin"
   ```
   或在 `[tool.hatch.build]` 段配 `include = ["src/forgecode/skills/builtin/**/SKILL.md", ...]` 保证资源进 wheel

**验证**：
- `python -c "from forgecode.skills.catalog import Catalog; from pathlib import Path; print(Catalog.load(Path('.')).names())"` 输出 `['commit', 'review', 'test']`（字典序）
- `uv build` 后 `unzip -l dist/forgecode-*.whl | grep SKILL.md` 能看到三条

## T6: Catalog 单测**文件**：`tests/test_skills_catalog.py`
**依赖**：T4, T5
**步骤**：
1. `test_load_catalog_builtin_only`：用空 `tmp_path` 当 work_dir 跑 `Catalog.load`，期望 `names() == ['commit', 'review', 'test']`
2. `test_load_catalog_user_override`：在 `monkeypatch.setenv('HOME', str(tmp_home))` 下放 `commit` 目录，期望该目录的 description 覆盖 builtin
3. `test_load_catalog_project_override`：在 `tmp_work_dir/.forgecode/skills` 放 `commit` 目录，期望覆盖 user
4. `test_validate_tools_missing_tool`：定义一个 skill 用 `NotExist` 工具，期望返回 1 个 issue

**验证**：`pytest tests/test_skills_catalog.py -v`，全部通过。

## T7: ActiveSkills 列表**文件**：`src/forgecode/skills/active.py`
**依赖**：T1
**步骤**：
1. 定义 `class ActiveSkills`，成员 `_lock = threading.Lock()`、`_entries: list[ActiveEntry]`、`_index: dict[str, int]`
2. `def __init__(self)` 初始化空
3. `def activate(self, name: str, body: str) -> None`：加锁；若 name 已存在则更新 body（保持位置不变）；否则追加
4. `def clear(self) -> None`：加锁清空两个字段
5. `def snapshot(self) -> list[ActiveEntry]`：加锁拷贝（list + 元素）
6. `def names(self) -> list[str]`

**验证**：写一个简单单测覆盖 `activate/clear/snapshot` 路径，`pytest tests/test_skills_active.py` 通过。

## T8: Render 渲染**文件**：`src/forgecode/skills/render.py`
**依赖**：T1
**步骤**：
1. `def render_body(s: Skill, args: str) -> str`：
   - `body = s.prompt_body`
   - 若 `len(s.meta.allowed_tools) > 0`：在 body 前插入"建议工具"提示行（格式见 plan.md F27），用 `\n\n---\n\n` 分隔
   - 若 `"$ARGUMENTS" in body`: `body = body.replace("$ARGUMENTS", args)`
   - 否则若 `args.strip() != ""`: `body += "\n\n## User Request\n\n" + args`
   - 返回 body
2. 单测：覆盖 4 种组合（有/无 placeholder × 有/无 args）

**验证**：`pytest tests/test_skills_render.py -v` 通过。

## T9: prompt 包适配器**文件**：`src/forgecode/skills/adapter.py`
**依赖**：T4, T7
**步骤**：
1. 在 skills 包定义 `@dataclass(frozen=True) class PromptItem(name, description)` 与 `@dataclass(frozen=True) class PromptEntry(name, body)`（避免反向依赖 prompt 包）
2. `def catalog_to_prompt_items(c: Catalog) -> list[PromptItem]`：按 `_order` 输出
3. `def active_to_prompt_entries(a: ActiveSkills) -> list[PromptEntry]`：按 `snapshot` 顺序输出

**验证**：`ruff check src/forgecode/skills/` 无告警。

## T10: prompt 模块槽位重命名**文件**：`src/forgecode/prompt/modules.py`
**依赖**：无
**步骤**：
1. 把 `PRIO_ACTIVE_SKILLS = 90` 重命名为 `PRIO_SKILLS_CATALOG = 90`
2. `optional_modules(instructions, memory)` 改签名为 `optional_modules(instructions, memory, skills_catalog)`
3. 模块名由 `"active-skills"` 改为 `"skills-catalog"`，content 取 `skills_catalog` 参数

**验证**：`ruff check src/forgecode/prompt/modules.py` 通过；`prompt.py` 调用处的报错留到 T12 修复。

## T11: prompt 新增 Skill 渲染函数**文件**：`src/forgecode/prompt/skills_block.py`
**依赖**：T10
**步骤**：
1. 定义 `@dataclass(frozen=True) class SkillCatalogItem(name, description)` 与 `@dataclass(frozen=True) class ActiveSkillEntry(name, body)`
2. `def render_skills_catalog(items: list[SkillCatalogItem]) -> str`：items 空返回 `""`；否则输出：
   ```
   ## Available Skills

   - <name>: <description>
   ...

   Call the LoadSkill tool with {"name": "<skill_name>"} to activate a skill's full SOP and specialized tools before executing it.
   ```
3. `def render_active_skills_block(entries: list[ActiveSkillEntry]) -> str`：entries 空返回 `""`；否则输出：
   ```
   ## Active Skills

   ### Skill: <name>

   <body>

   ### Skill: <name>

   <body>
   ```

**验证**：`python -c "from forgecode.prompt.skills_block import render_skills_catalog; print(render_skills_catalog([]))"` 输出空串。

## T12: build_system_prompt 签名更新**文件**：`src/forgecode/prompt/prompt.py`
**依赖**：T10, T11
**步骤**：
1. `build_system_prompt(instructions, memory)` 改为 `build_system_prompt(instructions, memory, skills_catalog)`
2. 内部把第三参数传给 `optional_modules`

**验证**：`python -c "import forgecode.prompt"` 通过；`ruff check src/forgecode/prompt/` 通过。

## T13: prompt 单测同步**文件**：`tests/test_prompt.py`
**依赖**：T12
**步骤**：
1. 所有 `build_system_prompt(X, Y)` 调用替换为 `build_system_prompt(X, Y, "")`（或必要场景传入非空 catalog 文本，新增 1 个用例覆盖）
2. 新增 `test_render_skills_catalog_non_empty / _empty` 与 `test_render_active_skills_block_non_empty / _empty`

**验证**：`pytest tests/test_prompt.py -v`，全部通过。

## T14: ToolRegistry 系统工具支持**文件**：`src/forgecode/tool/registry.py` + 内置 6 工具与 MCP 工具
**依赖**：无
**步骤**：
1. `Tool` Protocol 新增 `is_system: bool` 属性（也可用 `@property`，默认 False）；6 个内置工具与 MCP 适配器各加一行 `is_system: bool = False`（dataclass 字段）或 `@property def is_system(self): return False`
2. `Registry.definitions_filtered(allowed: list[str]) -> list[ToolDefinition]`：按 order 遍历，name 在 allowed 集合内 OR `tool.is_system` 为 True 时纳入
3. `Registry.register_skill_tool(t: Tool) -> None` —— 重复名静默覆盖（不维护 order 中重名）

**验证**：`pytest tests/test_tool_registry.py -v`（如已有）通过；原 6 个工具与 MCP 适配编译通过。

## T15: ToolSpec 适配为 Tool**文件**：`src/forgecode/tool/skill_tool.py`
**依赖**：T1, T14
**步骤**：
1. 定义 `def new_skill_tool(name: str, description: str, input_schema: dict, command: list[str], base_dir: Path) -> Tool`：
   - 返回一个实现了 Tool 协议的对象
   - `name / description / parameters / read_only(False) / is_system(False)` / `async def execute(...)`
   - `execute`：用 `json.dumps(args).encode()` 作为 stdin；`asyncio.create_subprocess_exec(*command, cwd=base_dir, stdin=PIPE, stdout=PIPE, stderr=PIPE)`；`asyncio.wait_for(proc.communicate(input=...), timeout=30)`；读 stdout 当结果文本；`returncode != 0` 视失败
2. 因 tool 包不应反向依赖 skills 包，这里把 `ToolSpec` 字段直接打散到工厂函数参数

**验证**：写最小单测，模拟一个 `echo "ok"` 的 shell 脚本，验证 `await execute(...)` 返回 "ok"。

## T16: LoadSkill 工具**文件**：`src/forgecode/tool/load_skill.py`
**依赖**：T4, T7, T14, T15
**步骤**：
1. 定义 `class LoadSkillTool` 接受 `catalog`、`active`、`registry` 三个字段
2. `name = "load_skill"`，`description` 写明用途
3. `parameters` 返回 `{"type":"object","properties":{"name":{"type":"string","description":"Skill name to activate"}},"required":["name"]}`
4. `read_only` 属性返回 `True`（只动 Agent 自己状态，无外部副作用）；`is_system` 返回 `True`
5. `async def execute(self, ctx, args: dict) -> ToolResult`：
   - `name = args["name"]`
   - `skill = self.catalog.get(name)`；不存在返回 `ToolResult(text=f"unknown skill: {name}", is_error=True)`
   - 从磁盘 `<skill.source_dir>/SKILL.md` 重读，更新 body；失败回退到 `skill.prompt_body` 并打 warning
   - `self.active.activate(skill.meta.name, fresh_body)`
   - 注册 `skill.tool_specs`：`self.registry.register_skill_tool(new_skill_tool(...))`
   - 返回 `ToolResult(text=f"Skill {name} activated. SOP pinned to env context. {len(skill.tool_specs)} specialized tools registered.")`

**验证**：`ruff check src/forgecode/tool/load_skill.py` 无告警；`pytest tests/test_tool_load_skill.py` 通过基础用例。

## T17: InstallSkill 工具**文件**：`src/forgecode/tool/install_skill.py`
**依赖**：T18
**步骤**：
1. 定义 `class InstallSkillTool` 接受 `catalog`、`work_dir` 两个字段
2. `name = "install_skill"`，`description` 写明用途与限制
3. `parameters`：`{"type":"object","properties":{"source":{"type":"string","description":"URL of a Skill zip"}},"required":["source"]}`
4. `read_only = False`；`is_system = False`（受权限模式约束）
5. `async def execute(...)`：`await install_from_url(args["source"], self.catalog, self.work_dir)`，返回成功消息 `Skill <name> installed to ~/.forgecode/skills/<name>.`

**验证**：`ruff check` 通过；本工具的功能在 T18 跑完后再做集成测试。

## T18: install_from_url 与 zip-slip 防护**文件**：`src/forgecode/skills/install.py`
**依赖**：T4
**步骤**：
1. `async def install_from_url(source: str, catalog: Catalog, work_dir: Path) -> str`：
   - `async with httpx.AsyncClient(timeout=60.0) as client:` 流式下载到 `tempfile.NamedTemporaryFile`，累计 byte 数 >50MB 抛 `ValueError("zip too large")`
   - `zipfile.ZipFile(tmp.name)` 打开
   - 计算顶层目录名 = 所有条目共同前缀的第一段；校验匹配 `^[a-z][a-z0-9-]*$`
   - 遍历条目：
     - 拒绝 `..` in `Path(name).parts`
     - 拒绝 `Path(name).is_absolute()`
     - 拒绝 symlink：`zip_info.external_attr >> 16 & 0o170000 == 0o120000`
   - 解压到 `Path.home() / ".forgecode" / "skills" / <top_dir>/`（用 `ZipFile.extract`，但要事先校验绝对路径未逃逸）
   - 调 `catalog.reload(work_dir)`
   - 返回 `top_dir`
2. 单测 `test_install_from_url_zip_slip`：构造恶意 zip 含 `../../bad`，期望 `ValueError` 含 "unsafe path"
3. 单测 `test_install_from_url_happy`：用 `pytest-httpserver` 或 `aiohttp.test_utils` 起一个返回正常 zip 的 server，期望 `catalog.get(top_dir)` 在调用后能拿到

**验证**：`pytest tests/test_skills_install.py -v` 通过。

## T19: Skill Executor (inline + fork)**文件**：`src/forgecode/skills/executor.py`
**依赖**：T7, T8, T14
**步骤**：
1. 定义 `class Executor` 持有 `catalog`、`active`、`registry`、`provider`、`eng`、`version`、`runtime`
2. `def __init__(...)` 构造
3. `async def execute(self, ctx, ui, name: str, args: str) -> None`：
   - `skill = self.catalog.get(name)`；为 None → `ui.error(f"skill not found: {name}")`，返回
   - 重读 SKILL.md 更新 body（失败回退）
   - `rendered = render_body(skill, args)`
   - if `not skill.meta.is_fork()`: `await ui.inject_and_send(f"/{name}", rendered)`；返回
   - else (fork)：
     - 构造子 Conversation：按 `fork_context`（`"none"` / `"recent"` / `"full"`）
       - none: 仅 user 消息 = rendered
       - recent: 调 `ui.recent_messages(5)`（新增 UI 方法）拷贝再追加 user 消息
       - full: 暂用 recent 行为 + warning（`fork_context=full` 留个 TODO 后续 compact 摘要管道接入）。或本期实现简单版：复制 `ui.all_messages()` 用 ch09 现成的 compactor 压缩（如果改动太大，按 recent 行为兜底，并 stderr warning 提示用户）。**本期决议**：full 与 recent 等价处理，并打 warning，留待 ch12+ 真正接入
     - 选 provider：默认 `self.provider`；`skill.meta.model` 非空时 `llm.new_provider(model)` 重新构造（cli 已有相同代码可复用）
     - 子 registry 通过 `self.registry.definitions_filtered(skill.meta.allowed_tools)` → 但 `run()` 内部用的还是 `self.registry`；我们把过滤前置：用 `agent.with_filtered_registry(allowed: list[str])` 选项（新增）让子 Agent 在选 defs 时调 filtered
     - **简化方案**：本期 fork Agent 直接 `agent.create(prov, self.registry, self.version, self.eng, runtime=fork_runtime)`，不做工具过滤（与 inline 模式一致，靠 SOP 提示约束）。这与 spec F28 中"按 allowed_tools 过滤工具集"相违；选简单实现并在 plan/spec 中记录此简化项
     - **回到决议**：本期 fork Agent 用 `self.registry.definitions_filtered(...)` 的封装版（通过 `agent.with_filtered_registry` 选项），保持 fork 模式真过滤的 spec 承诺
     - 起子 Conversation：`fork_conv = Conversation.new()`；填入构造好的初始消息
     - `fork_agent = agent.create(provider, self.registry, self.version, self.eng, runtime=fork_runtime, allowed_tools=skill.meta.allowed_tools)`
     - 起一条 `await fork_agent.run(ctx, fork_conv, permission.Mode.DEFAULT)`，遍历异步事件流；累积 usage、提取最终 assistant text；最大 25 轮兜底
     - usage 累加到主 runtime
     - `final_text = 末尾 assistant 文本`；若失败：`f"[skill {name} failed: {reason}]"`
     - `await ui.append_assistant_message(final_text)`
4. 新增 `agent.with_filtered_registry(allowed: list[str])` 选项；在 `run()` 的 defs 选取处，若 allowed 非空，调 `self.registry.definitions_filtered(allowed)` 代替 `self.registry.definitions()`

**验证**：`pytest tests/test_skills_executor.py -v`（mock provider + ui）；后续端到端 tmux 跑通 `/review`。

## T20: command UI Protocol 扩展**文件**：`src/forgecode/command/ui.py`
**依赖**：无（在 T19 前可独立完成）
**步骤**：
1. UI Protocol 新增 5 个方法：
   ```python
   def list_catalog_skills(self) -> list[SkillSummary]: ...
   def list_active_skills(self) -> list[str]: ...
   def clear_active_skills(self) -> None: ...
   async def append_assistant_message(self, text: str) -> None: ...
   def recent_messages(self, n: int) -> list[Message]: ...   # fork ForkContext=recent 用
   def all_messages(self) -> list[Message]: ...              # fork ForkContext=full 用
   ```
2. 定义 `@dataclass class SkillSummary(name, description, source, mode)`（放在 command 包，避免 skills 依赖 command）
3. `NopUI` 提供零值实现：`list_catalog_skills→[]`；`list_active_skills→[]`；`clear_active_skills→no-op`；`append_assistant_message→no-op`；`recent_messages→[]`；`all_messages→[]`

**验证**：`ruff check src/forgecode/command/` 通过；`pytest tests/test_command_ui.py` 通过。

## T21: command/builtins.py 改动**文件**：`src/forgecode/command/builtins.py`
**依赖**：T20
**步骤**：
1. 删除 `name="review"` 的整段 `reg.register` 块（与对应的 `handle_review` 函数文件——如有，标记 TODO 或一并清理）
2. 修改 `handle_clear`：在 `await ui.clear_and_new_session()` 之后追加一行 `ui.clear_active_skills()`
3. 新增 `reg.register` 块：
   ```python
   reg.register(Command(
       name="skill", description="列出已加载的 Skill",
       kind=CommandKind.LOCAL, handler=handle_skill,
   ))
   ```

**验证**：`pytest tests/test_command.py -v` 通过；如果有 review 单测，要么更新要么删除。

## T22: handle_skill 实现**文件**：`src/forgecode/command/builtin_skill.py`
**依赖**：T20
**步骤**：
1. `async def handle_skill(ctx, ui) -> None`：
   - `skills = ui.list_catalog_skills()`
   - 空时 `ui.println("No skills loaded.")`
   - 否则：
     - 先 `ui.println(f"Available skills ({len(skills)}):")`
     - 再按 name 字典序逐条 `ui.println(f"  /{name:<20} {description}")`（每条独立 println 避免 notice_block 多行渲染产生空白）
     - 末尾 `ui.println("Type /<skill-name> to invoke a skill.")`
   - 不展示 source / mode 元信息——本期保持精简，开发者需要时直接读 SKILL.md

**验证**：`pytest tests/test_command_builtin_skill.py`（如果新增了相应单测）。

## T23: register_skills_as_commands**文件**：`src/forgecode/command/skills.py`
**依赖**：T20, T22
**步骤**：
1. 定义命令的 meta 标记机制：在 `Command` dataclass 新增字段 `is_skill: bool = False`（也可单独维护一个 set，但加字段最简）。修改 ch10 `command.py` 中 `Command` 数据类增加这个字段
2. `def register_skills_as_commands(reg, items: list[SkillSummary], executor: SkillRunner)`：
   - `SkillRunner` Protocol：`async def execute(ctx, ui, name, args) -> None`
   - 遍历 items，每个 register 一个 `Command(name=item.name, description=item.description + " [skill]", kind=CommandKind.PROMPT, is_skill=True, handler=...)`
   - 用 `functools.partial(_run_skill, executor=executor, name=item.name)` 或 `lambda _ctx, _ui, _name=item.name: executor.execute(_ctx, _ui, _name, "")` **显式绑定 name**（Python 闭包变量是后期绑定，循环里必须用默认参数或 partial 拷贝）
3. `def remove_skill_commands(reg) -> None`：遍历 reg 内部 dict，删除 `is_skill=True` 的条目

注：Registry 内部存储要支持 iter/del 操作；可能需要扩展 ch10 的 `registry.py`（T24）。

**验证**：`pytest tests/test_command_skills.py` 通过。

## T24: command.Registry 删除 API**文件**：`src/forgecode/command/registry.py`
**依赖**：T23
**步骤**：
1. 检查 ch10 现有 Registry 是否暴露足够 API；如未提供按条件删除，新增：
   - `def remove_if(self, pred: Callable[[Command], bool]) -> None`：按谓词删除（同时清 `_by_name` + `_by_alias` + list 序）
2. 在 `remove_skill_commands` 中调 `reg.remove_if(lambda c: c.is_skill)`

**验证**：`pytest tests/test_command_registry.py -v` 通过。

## T25: SessionRuntime active_skills 字段**文件**：`src/forgecode/agent/runtime.py`
**依赖**：T7
**步骤**：
1. `SessionRuntime` 增加字段 `active_skills: ActiveSkills`
2. `new_session_runtime()` 初始化 `active_skills=ActiveSkills()`
3. `reset_for_new_session` 增加一行 `if self.active_skills is not None: self.active_skills.clear()`
4. 由于 agent 包反向引入 skills 包会有依赖循环（`skills.Executor` 依赖 `agent.SessionRuntime`）；解决方法：把 `ActiveSkills` 类型放到 agent 包下；或定义在 skills 包，agent 包 import 它（agent 已可以 import skills 包，没有循环——只要 skills 包不 import agent 包）。为简单起见，`Executor` 需要的 runtime 字段单独通过函数参数传递，不直接 import `agent.SessionRuntime`；让 `skills.Executor` 持有 `ActiveSkills` 而非 `SessionRuntime`

**重新设计**：
- skills 包不 import agent
- `agent.SessionRuntime` 持有 `active_skills: ActiveSkills` 字段
- `skills.Executor` 通过 `ActiveSkills` 操作激活态（不直接持有 `SessionRuntime`）

**验证**：`python -c "from forgecode.agent.runtime import SessionRuntime"` 通过。

## T26: Agent 拼装 sys / env 改动**文件**：`src/forgecode/agent/agent.py`
**依赖**：T9, T12, T25
**步骤**：
1. 新增 `with_catalog(c: Catalog) -> AgentOption`：设置 `self._catalog`
2. 新增 `with_filtered_registry(allowed: list[str]) -> AgentOption`：设置 `self._allowed_tools`
3. Agent 增加字段：`_catalog: Catalog | None`、`_allowed_tools: list[str] | None`
4. 新增方法 `def activate_skill(self, name, body)`，调 `self._runtime.active_skills.activate(...)`
5. 新增方法 `def clear_active_skills(self)`
6. `run()` 内每轮重建：
   ```python
   catalog_text = ""
   if self._catalog is not None:
       items = [SkillCatalogItem(p.name, p.description) for p in catalog_to_prompt_items(self._catalog)]
       catalog_text = prompt.render_skills_catalog(items)
   sys = prompt.build_system_prompt(self._instruction_text, self._memory_text, catalog_text)

   env_base = prompt.gather_environment(...).render()
   env_skills = ""
   if self._runtime is not None and self._runtime.active_skills is not None:
       entries = [ActiveSkillEntry(e.name, e.body) for e in active_to_prompt_entries(self._runtime.active_skills)]
       env_skills = prompt.render_active_skills_block(entries)
   env_text = env_base
   if env_skills:
       env_text += "\n\n" + env_skills
   ```
7. defs 选择：
   ```python
   defs = self._registry.definitions()
   if mode == permission.Mode.PLAN:
       defs = self._registry.read_only_definitions()
   if self._allowed_tools:
       defs = self._registry.definitions_filtered(self._allowed_tools)
   ```

**验证**：`pytest tests/test_agent.py -v` 通过；既有单测通过。

## T27: TUI App 与 UI 实现**文件**：`src/forgecode/tui/app.py` + 相关
**依赖**：T20, T25
**步骤**：
1. `App` 持有 `catalog: Catalog`、`executor: Executor`
2. `create_app` 工厂接受 catalog/executor 参数
3. 实现 UI Protocol 的新方法：
   - `list_catalog_skills()`：从 catalog 转换
   - `list_active_skills()`：从 `runtime.active_skills.names()`
   - `clear_active_skills()`：`runtime.active_skills.clear()`
   - `append_assistant_message(text)`：追加到当前 conversation 与会话存档
   - `recent_messages(n) / all_messages()`：从当前 conversation 取
4. 注意：`UI.inject_and_send` 已有，不重写

**验证**：`pytest tests/test_tui.py` 通过；`python -m forgecode` 能起来。

## T28: src/forgecode/cli.py 接线**文件**：`src/forgecode/cli.py`
**依赖**：T1-T27
**步骤**：
1. `from forgecode.skills import Catalog, ActiveSkills, Executor`
2. 构造 `catalog = Catalog.load(work_dir)`
3. 构造 `ActiveSkills` 后 attach 到 `SessionRuntime`
4. 注册 `LoadSkillTool` / `InstallSkillTool` 到 `ToolRegistry`
5. 调 `issues = catalog.validate_tools(tool_reg)`；遍历 issues 打 stderr 并把不合格 skill 从 catalog 移除
6. 构造 `executor = Executor(catalog, active_skills, tool_reg, provider, eng, version, ...)`
7. 调 `command.register_builtins(cmd_reg)`（已有，删 `/review` 后内置 11 条）
8. 调 `command.register_skills_as_commands(cmd_reg, catalog 转换的 summary, executor)`
9. `tui.create_app(... catalog, executor)`
10. Agent 构造时附 `agent.with_catalog(catalog)`

**验证**：`python -m forgecode` 全包跑起来；`ruff check src/forgecode/` 无新增告警。

## T29: 启动冒烟**文件**：无
**依赖**：T28
**步骤**：
1. 在 tmux 内：`python -m forgecode`，期望启动 banner 正常、状态栏正常
2. 键入 `/help`，期望输出含 `/skill` 行、不含独立 `/review` 行、含 `/commit [skill]` `/review [skill]` `/test [skill]` 三行
3. 键入 `/skill`，期望输出三行（commit/review/test，source=builtin）
4. ctrl+c 退出

**验证**：观察输出符合上述期望；任何异常或缺失都修正后重测。

## T30: 端到端验证场景

按 checklist.md 中端到端场景章节，在 tmux 里实跑全套流程。

## 执行顺序

```
T1 → T2 → T3
  → T4 (依赖 T1,T2) → T5 (依赖 T4) → T6 (依赖 T4,T5)
  → T7 (依赖 T1) → T8 (依赖 T1) → T9 (依赖 T4,T7)

T10 → T11 (依赖 T10) → T12 (依赖 T10,T11) → T13 (依赖 T12)

T14 → T15 (依赖 T1,T14) → T16 (依赖 T4,T7,T14,T15) → T17 (依赖 T18)
T18 (依赖 T4)

T20 → T21 (依赖 T20) → T22 (依赖 T20) → T23 (依赖 T20,T22) → T24 (依赖 T23)

T25 (依赖 T7) → T26 (依赖 T9,T12,T25) → T27 (依赖 T20,T25)

T19 (依赖 T7,T8,T14) → T28 (依赖 T1-T27)

T29 (依赖 T28) → T30
```

可并行：T1-T9 内部链；T10-T13 链；T14-T18 链；T20-T24 链 —— 这四条链彼此独立直到 T25 起开始合流。但本期由单一会话顺序执行，避免合并冲突。