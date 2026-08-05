# Worktree 隔离 Tasks## 文件清单

| 操作 | 文件 | 职责 |
|------|------|------|
| 新建 | `src/forgecode/worktree/__init__.py` | 公开导出 Manager / validate_slug / 错误类型 |
| 新建 | `src/forgecode/worktree/slug.py` | validate_slug + flat_slug |
| 新建 | `tests/test_worktree_slug.py` | Slug 校验单测 |
| 新建 | `src/forgecode/worktree/session.py` | WorktreeSession + JSON 原子持久化 |
| 新建 | `src/forgecode/worktree/git.py` | _run_git + _has_worktree_changes + _resolve_head_sha_from_fs |
| 新建 | `tests/test_worktree_git.py` | git helper 单测 |
| 新建 | `src/forgecode/worktree/manager.py` | Manager 类型 + 构造 + list/get/current_session |
| 新建 | `src/forgecode/worktree/create.py` | create + 快速恢复 + post-creation setup A/B/C/D |
| 新建 | `tests/test_worktree_create.py` | create + setup 单测 |
| 新建 | `src/forgecode/worktree/lifecycle.py` | enter / exit / remove / auto_cleanup |
| 新建 | `tests/test_worktree_lifecycle.py` | 生命周期单测 |
| 新建 | `src/forgecode/worktree/sweep.py` | sweep_stale + 三层过滤 |
| 新建 | `tests/test_worktree_sweep.py` | sweep_stale 单测 |
| 新建 | `tests/test_worktree_manager.py` | Manager 构造 + session 持久化测试 |
| 新建 | `src/forgecode/tool/ctx.py` | with_cwd / cwd_from_ctx / resolve_path |
| 新建 | `tests/test_tool_ctx.py` | resolve_path 单测 |
| 修改 | `src/forgecode/tool/read_file.py` | 用 resolve_path 解析 path |
| 修改 | `src/forgecode/tool/write_file.py` | 用 resolve_path 解析 path |
| 修改 | `src/forgecode/tool/edit_file.py` | 用 resolve_path 解析 path |
| 修改 | `src/forgecode/tool/glob.py` | 用 resolve_path 解析 root |
| 修改 | `src/forgecode/tool/grep.py` | 用 resolve_path 解析 path |
| 修改 | `src/forgecode/tool/bash.py` | 子进程 cwd=resolve_path("") |
| 修改 | `src/forgecode/subagent/definition.py` | Definition 加 isolation 字段 |
| 修改 | `src/forgecode/subagent/parser.py` | 解析 isolation: frontmatter |
| 修改 | `tests/test_subagent_parser.py` | 增加 isolation 单测 |
| 新建 | `src/forgecode/agent/agent_worktree.py` | _execute_with_worktree + build_worktree_notice |
| 修改 | `src/forgecode/agent/agent_tool.py` | 增加 worktree_mgr 字段 + isolation 分支 |
| 新建 | `tests/test_agent_worktree.py` | _execute_with_worktree 单测(用 stub Manager) |
| 修改 | `src/forgecode/command/ui.py` | 加 WorktreeAccessor 协议 + WorktreeSummary |
| 新建 | `src/forgecode/command/builtin_worktree.py` | /worktree handler + 子命令解析 |
| 修改 | `src/forgecode/command/builtins.py` | 注册 /worktree |
| 修改 | `tests/test_command_builtins.py` | 加 worktree 注册测试 |
| 新建 | `src/forgecode/tui/worktree_adapter.py` | 实现 WorktreeAccessor 适配 worktree.Manager |
| 修改 | `src/forgecode/tui/app.py` | worktree_mgr / active_cwd 字段 + 注入 ctx |
| 修改 | `src/forgecode/cli.py` | 构造 Manager + 注入 AgentTool / App + sweep_stale |
| 修改 | `.gitignore` | 追加 .forgecode/worktrees/ + worktree_session.json |

## T1: Slug 校验**文件:** `src/forgecode/worktree/slug.py` + `tests/test_worktree_slug.py`
**依赖:** 无
**步骤:**
1. 创建子包 `forgecode.worktree`,加 `__init__.py`(暂时空导出,后续 T 步骤补)
2. 实现 `validate_slug(name: str) -> None`,规则:非空、长度 ≤ 64、按 `/` 切段后每段匹配 `^[a-zA-Z0-9._-]+$` 且不能是 `.` 或 `..`、无连续 `//`、无首末 `/`;失败抛 `ValueError(<具体原因>)`
3. 实现 `flat_slug(name: str) -> str`:`name.replace("/", "+")`
4. 写测试覆盖合法/非法 case:`alice`、`team/alice`、`v1.0`、`a_b`(合法);空、超长、`..`、`./x`、`a//b`、`/x`、`a/`、`a b`、`a;b`(非法,断言 `pytest.raises(ValueError)`)

**验证:** `pytest tests/test_worktree_slug.py -v`

## T2: WorktreeSession 持久化**文件:** `src/forgecode/worktree/session.py`
**依赖:** T1
**步骤:**
1. 定义 `WorktreeSession` dataclass,字段按 spec F3,JSON 序列化用 `dataclasses.asdict + json.dumps`
2. 实现 `load_session(path: Path) -> WorktreeSession | None`:文件不存在返回 None;内容为 `null` 或空返回 None;JSON 解析失败抛异常
3. 实现 `save_session(path: Path, session: WorktreeSession | None) -> None`:session=None 时写 `null`;原子写——先写 `path.with_suffix(path.suffix + ".tmp")` 再 `os.replace`
4. 实现 `clear_session(path: Path)`(等同 `save_session(path, None)`)

**验证:** 在 test_worktree_manager.py T9 中覆盖

## T3: Git helper**文件:** `src/forgecode/worktree/git.py` + `tests/test_worktree_git.py`
**依赖:** 无
**步骤:**
1. 实现 `async def _run_git(work_dir: str, *args: str) -> str`:用 `asyncio.create_subprocess_exec("git", *args, cwd=work_dir, env=..., stdin=DEVNULL, stdout=PIPE, stderr=PIPE)`,env 注入 `GIT_TERMINAL_PROMPT=0` + `GIT_ASKPASS=""`(在 `os.environ` 副本基础上),`await proc.communicate()`,返回 stdout decode 并 rstrip 换行;失败抛 `RuntimeError(stderr)`
2. 实现 `async def _has_worktree_changes(wt_path: str, base_commit: str) -> bool`:① `git -C status --porcelain` 非空 ② `git -C rev-list --count <base_commit>..HEAD` >0;任一 git 命令本身出错 fail-closed 返回 True
3. 实现 `_resolve_head_sha_from_fs(wt_path: str) -> str | None`:读 `wt_path/.git` 取 `gitdir: <path>`,读 `<gitdir>/HEAD`,若是 `ref: refs/heads/<name>`,读 `<gitdir>/<refpath>` 拿 SHA;失败返回 None
4. 测试:用一个临时 git 仓库做真实 Worktree,断言上述函数行为(可用 `pytest.fixture` + `subprocess.run` 准备 fixture)

**验证:** `pytest tests/test_worktree_git.py -v`

## T4: Manager 构造**文件:** `src/forgecode/worktree/manager.py` + `tests/test_worktree_manager.py`
**依赖:** T2, T3
**步骤:**
1. 定义 `Manager` 类(spec F4 字段) + 模块常量 `DEFAULT_SYMLINK_DIRS = ["node_modules", ".venv", "vendor"]`
2. 实现 `Manager.__init__(self, repo_root: str)`:
   - `self.repo_root = str(Path(repo_root).resolve())`
   - 同步跑 `subprocess.run(["git", "-C", repo_root, "rev-parse", "--show-toplevel"], capture_output=True, text=True)`,输出与 repo_root 不匹配则抛 `ValueError("not a git repo root")`
   - 初始化 `worktree_dir`、`session_file`、`active = {}`、`lock = asyncio.Lock()`
   - `Path(worktree_dir).mkdir(parents=True, exist_ok=True)`
   - 调 `load_session(session_file)`;若 session 非 None 但其 worktree_path 不存在,清空 session 并 stderr 警告
   - 扫描 `worktree_dir` 子目录,对每个非空目录用 `_resolve_head_sha_from_fs` 填 `active`(快速恢复路径,不调 git)
3. 实现 `list() -> list[Worktree]`(按 name 排序)、`get(name) -> Worktree | None`、`current_session() -> WorktreeSession | None`
4. 测试:在临时 git 仓库构造 Manager,断言 worktree_dir 创建、空 session 时 current_session()=None、预放 session 文件能被加载、Worktree 目录不存在时 session 被清空

**验证:** `pytest tests/test_worktree_manager.py -v`

## T5: create + 快速恢复 + 创建后设置**文件:** `src/forgecode/worktree/create.py` + `tests/test_worktree_create.py`
**依赖:** T4
**步骤:**
1. 实现 `async def create(self, name, base_ref, manual) -> Worktree`(挂在 Manager 上,可用 mixin 或 import 后绑定):
   - `validate_slug(name)` 不通过即抛 ValueError
   - `async with self.lock:`;`active[name]` 存在即抛 ValueError
   - 算 `flat = flat_slug(name)`、`wt_path = self.worktree_dir / flat`、`branch = f"worktree-{flat}"`
   - 若 `wt_path.exists()`,用 `_resolve_head_sha_from_fs` 取 sha,构造 Worktree 放 active,**直接返回**(快速恢复,跳过 setup)
   - 否则跑 `await _run_git(self.repo_root, "worktree", "add", "-B", branch, str(wt_path), base_ref)`
   - 失败时:`shutil.rmtree(wt_path, ignore_errors=True)`,重新抛异常
   - 调 `await _perform_post_creation_setup(self.repo_root, wt_path, self.symlink_dirs)`,内部每个子步骤 try/except 仅 stderr 警告
   - 跑 `head_sha = await _run_git(wt_path, "rev-parse", "HEAD")` 拿 head SHA
   - 构造 Worktree(`name, path=str(wt_path), branch, based_on=base_ref, head_commit=head_sha, created=datetime.now(), manual`)放 active,返回
2. 实现 `async def _perform_post_creation_setup(repo_root, wt_path, symlink_dirs)`:四个子函数:
   - `copy_local_configs(repo_root, wt_path)`:对 `.forgecode/config.yaml` / `.forgecode/settings.local.yaml`,若主仓存在且 Worktree 不存在,`shutil.copy`
   - `setup_git_hooks(repo_root, wt_path)`:优先 `.husky/`,回退 `git -C <repo_root> config --get core.hooksPath` 拿主仓配置,若有值跑 `git -C <wt_path> config core.hooksPath <绝对路径>`
   - `symlink_large_dirs(repo_root, wt_path, symlink_dirs)`:对每个目录若主仓存在且 Worktree 不存在,`os.symlink(Path(repo_root)/dir, Path(wt_path)/dir)`
   - `copy_included_ignored(repo_root, wt_path)`:读 `.worktreeinclude` 模式;跑 `git -C <repo_root> ls-files --others --ignored --exclude-standard --directory` 列出忽略文件;每个文件用 `fnmatch.fnmatch` 对模式;命中则 `shutil.copy` 到 Worktree
   - 每个子函数 try/except 失败只往 stderr 写一行 `worktree: setup <step>: <err>` 警告,继续下个步骤
3. 测试:在临时 git 仓库覆盖:create 成功后目录存在、分支存在、设置 A 复制 settings.local.yaml、设置 C 软链 node_modules、设置 D 按 .worktreeinclude 复制 .env;快速恢复路径不调 git(可用 monkeypatch 替换 `_run_git` 断言未被调用)

**验证:** `pytest tests/test_worktree_create.py -v`

## T6: enter / exit / remove / auto_cleanup**文件:** `src/forgecode/worktree/lifecycle.py` + `tests/test_worktree_lifecycle.py`
**依赖:** T5
**步骤:**
1. 实现 `ExitAction`(str Enum)、`ExitOptions`、`ExitReport`、`AutoCleanupReport` 类型与 `WorktreeHasChangesError`
2. 实现 `async def enter(self, name) -> WorktreeSession`:
   - `async with self.lock:`,取 `active[name]`
   - `original_cwd = str(Path.cwd())`
   - `original_branch = await _run_git(self.repo_root, "rev-parse", "--abbrev-ref", "HEAD")` 与 `original_head = await _run_git(self.repo_root, "rev-parse", "HEAD")`(try/except 失败用空字符串兜底)
   - 生成 `session_id = secrets.token_hex(8)`(保证唯一)
   - 写 `self.current_session` 字段,持久化 `save_session`
3. 实现 `async def exit(self, name, action, opts) -> ExitReport`:
   - `async with self.lock:`;校验 `current_session` 非空且 `worktree_name == name`;否则抛 ValueError
   - 取 `active[name]`;若 None 抛 ValueError
   - `action=REMOVE` 且 `not opts.discard_changes`:调 `_has_worktree_changes`,True 则抛 `WorktreeHasChangesError`
   - `os.chdir(current_session.original_cwd)` 兜底(`contextlib.suppress(OSError)` 包住)
   - `self.current_session = None`,`save_session(session_file, None)`
   - `action=REMOVE`:`await _run_git(self.repo_root, "worktree", "remove", "--force", wt.path)`,`await asyncio.sleep(0.1)`,`await _run_git(self.repo_root, "branch", "-D", wt.branch)`,`del active[name]`
   - 返回 `ExitReport(removed=action==REMOVE, path=wt.path, branch=wt.branch)`
4. 实现 `async def remove(self, name, opts)`:类似 exit 的 remove 分支,但允许非当前 session;变更保护同
5. 实现 `async def auto_cleanup(self, name) -> AutoCleanupReport`:
   - 取 `active[name]`;`manual=True` 直接 `AutoCleanupReport(kept=True, path=wt.path, branch=wt.branch)`
   - `_has_worktree_changes` 为 False 调 `remove(name, ExitOptions(discard_changes=True))`,返回 `AutoCleanupReport(kept=False)`
   - 有变更:`AutoCleanupReport(kept=True, path=wt.path, branch=wt.branch)`
6. 测试:enter 不改进程 cwd、exit 切回 cwd、exit remove 变更保护、auto_cleanup manual/无变更/有变更三种分支(用 `pytest.mark.asyncio`)

**验证:** `pytest tests/test_worktree_lifecycle.py -v`

## T7: sweep_stale**文件:** `src/forgecode/worktree/sweep.py` + `tests/test_worktree_sweep.py`
**依赖:** T6
**步骤:**
1. 在 sweep.py 定义 `EPHEMERAL_PATTERN = re.compile(r"^agent-a[0-9a-f]{7}$")`
2. 实现 `async def sweep_stale(self, cutoff: datetime) -> list[str]`:
   - 遍历 `Path(self.worktree_dir).iterdir()`
   - 对每个目录:不匹配 pattern 跳过;`datetime.fromtimestamp(p.stat().st_mtime) > cutoff` 跳过;`current_session.worktree_path == str(p)` 跳过
   - 跑 `await _has_worktree_changes(p, "HEAD")`(base 用 HEAD 比较是否有自己提交的 commit——README 说要查未提交修改 + 未推送 commit;这里 base 用 head 等价于只查 status,unpushed 单独跑)
   - 实际实现:① status --porcelain 非空跳过 ② `git rev-list --max-count=1 HEAD --not --remotes` 非空跳过
   - 通过的:调 `remove(name, ExitOptions(discard_changes=True))`,记 removed.append(name)
3. 实现 `random_agent_name() -> str`(返回 `"agent-a" + secrets.token_hex(4)[:7]`)
4. 测试:构造三个目录(匹配模式无变更、匹配模式有变更、不匹配模式),sweep_stale 只删第一个

**验证:** `pytest tests/test_worktree_sweep.py -v`

## T8: tool ctx**文件:** `src/forgecode/tool/ctx.py` + `tests/test_tool_ctx.py`
**依赖:** 无(并行 T1-T7)
**步骤:**
1. 在 `src/forgecode/tool/ctx.py` 定义 `_ctx_cwd: ContextVar[str | None] = ContextVar("cwd", default=None)`
2. 实现 `with_cwd(directory: str)` 作为 `@contextmanager`:`directory==""` 时直接 yield 不变;否则 `token = _ctx_cwd.set(directory); try yield finally _ctx_cwd.reset(token)`
3. 实现 `cwd_from_ctx() -> str | None`(返回 `_ctx_cwd.get()`)
4. 实现 `resolve_path(p: str) -> str`:
   - `base = _ctx_cwd.get() or str(Path.cwd())`
   - `p` 为空:返回 base
   - `Path(p).is_absolute()`:返回 `str(Path(p))`
   - 否则:返回 `str(Path(base) / p)`
5. 测试:覆盖三种 path、ctx 无 cwd 时回落到进程 cwd、空字符串返回 cwd 本身

**验证:** `pytest tests/test_tool_ctx.py -v`

## T9: 改造 6 个核心工具**文件:** `src/forgecode/tool/{bash,read_file,write_file,edit_file,glob,grep}.py`
**依赖:** T8
**步骤:**
1. `read_file.py`:在 `Path(args.path).stat()` / `read_text()` 前 `abs_path = resolve_path(args.path)`,后续用 `Path(abs_path)`
2. `write_file.py`:同样改造 path 参数;若需要 `mkdir(parents=True)` 时也用 abs
3. `edit_file.py`:同样
4. `glob.py`:`root = args.path or "."`;然后 `root = resolve_path(root)`;`Path(root).rglob(...)` 用 abs root;返回路径仍按相对 root 输出(保持现有行为)
5. `grep.py`:与 glob 同
6. `bash.py`:在 `asyncio.create_subprocess_exec / subprocess.Popen` 调用上设 `cwd=resolve_path("")`(空字符串解析为 cwd 本身)
7. 不改 schema(`Tool.parameters` 不变),不改 description
8. 单测:构造 `with with_cwd(tmp_dir):` 到临时目录,在临时目录里准备文件,调工具断言读到对应内容

**验证:** `pytest tests/test_tool*.py -v`

## T10: subagent.Definition.isolation**文件:** `src/forgecode/subagent/{definition,parser}.py` + `tests/test_subagent_parser.py`
**依赖:** 无
**步骤:**
1. `definition.py`:`Definition` dataclass 加 `isolation: str = ""` 字段
2. `parser.py`:frontmatter 字典中 `raw = fm.get("isolation", "")`,合法值 `""` / `"worktree"`,非法值 stderr 警告并回落 `""`,把结果填到 `definition.isolation`
3. `tests/test_subagent_parser.py`:增加测试覆盖 `isolation: worktree` 解析成功、`isolation: gibberish` 警告并回落空(用 `capsys` 断言 stderr 内容)

**验证:** `pytest tests/test_subagent_parser.py -v`

## T11: _execute_with_worktree**文件:** `src/forgecode/agent/agent_worktree.py` + `tests/test_agent_worktree.py`
**依赖:** T6, T8, T10
**步骤:**
1. 新建 `agent_worktree.py`,顶部 `from forgecode.worktree import Manager, random_agent_name`(worktree 包不依赖 agent,无导入循环)
2. 实现 `build_worktree_notice(parent_cwd: str, wt_path: str) -> str`(按 spec F22 模板)
3. 实现 `async def _execute_with_worktree(manager: Manager, definition, sub_agent, sub_conv, prompt: str, events) -> str`:
   - `name = random_agent_name()`
   - `wt = await manager.create(name, "HEAD", manual=False)`
   - `cwd = str(Path.cwd())`
   - `notice = build_worktree_notice(cwd, wt.path)`
   - `task_text = notice + "\n\n" + prompt`
   - `with with_cwd(wt.path):`
   - `    final_text = await sub_agent.run_to_completion(sub_conv, task_text, events)`
   - `report = await manager.auto_cleanup(name)`
   - 若 `report.kept`,把保留信息追加到 `final_text`
   - 返回 `final_text`
4. 单测:用一个真实临时 git 仓库构造 worktree.Manager;sub_agent 用 mock provider(返回空文本即结束);断言 wt.path 被传到 ctx(可在 run_to_completion 内打桩读 cwd_from_ctx)、auto_cleanup 被调用

**验证:** `pytest tests/test_agent_worktree.py -v`

## T12: AgentTool 接入 isolation 分支**文件:** `src/forgecode/agent/agent_tool.py`
**依赖:** T11
**步骤:**
1. AgentTool 加属性 `worktree_mgr: Manager | None`
2. `__init__(self, catalog, task_mgr, parent, bg_enabled, worktree_mgr=None)`——签名末尾追加 worktree_mgr(允许 None 表示不启用)
3. 在 execute 内 `definition.isolation == "worktree"` 时:
   - 若 `self.worktree_mgr is None`,返回 `ToolResult(is_error=True, content="worktree manager not configured")`
   - 若 `background == True`:本期最小实现——**isolation:worktree 时强制前台同步**(忽略 background 字段);AgentTool 在 `definition.isolation == "worktree"` 时即使 background=True 也走 inline 分支;tool_result 返回最终文本
4. 在 inline 路径前,若 `definition.isolation == "worktree"`,调 `_execute_with_worktree(self.worktree_mgr, definition, sub_agent, sub_conv, args.prompt, events)` 替代直接 `run_to_completion`
5. 改 `src/forgecode/cli.py` 的 `AgentTool` 构造调用,传入 `worktree_mgr`

**验证:** `pytest tests/test_agent_tool.py tests/test_agent_worktree.py -v`

## T13: command 包加 WorktreeAccessor + /worktree handler**文件:** `src/forgecode/command/ui.py` + `src/forgecode/command/builtin_worktree.py` + `src/forgecode/command/builtins.py` + `tests/test_command_builtins.py`
**依赖:** T6
**步骤:**
1. `ui.py`:加 `WorktreeSummary` dataclass + `WorktreeAccessor` Protocol(spec F24-F28 所列方法);`UI` Protocol 加 `worktree_accessor() -> WorktreeAccessor | None`;`nop_ui` 实现返回 None
2. `builtin_worktree.py`:实现 `async def handle_worktree(ui, args: str) -> None`——args 是 `/worktree` 后面的全部尾随字符串;split 子命令 + 其余参数
   - `create <slug>` → `await ui.worktree_accessor().create(slug)`,输出 `Worktree 已创建: <path> (分支 <branch>)`
   - `list` → 遍历 `list()`,按格式输出
   - `enter <slug>` → `await enter(slug)`,输出 `已进入 <slug>: <path>`
   - `exit [--remove] [--discard]` → 解析 flag,调 `exit`
   - `remove <slug> [--discard]` → 调 `remove`
   - 未知子命令报错
3. `builtins.py`:注册 `Command(name="worktree", kind=KindLocal, args_handler=handle_worktree)`——给 `Command` 加可选字段 `args_handler: Callable[[UI, str], Awaitable[None]] | None`,Registry.dispatch 时若命中支持 args 的命令则走 args_handler;dispatcher 在解析 `/worktree create foo` 时,把 head=`worktree`、tail=`create foo` 传给 args_handler
4. **最小改动机制:** 修改 `command/parse.py`(或 dispatch 入口):在解析输入时,若命令名命中已注册命令,把尾随字符串作为 args 透传;`Command` 区分 `handler` (无参) 与 `args_handler` (带 args)
5. 测试:测试 handle_worktree 分发逻辑(用 stub UI / stub Accessor)

**验证:** `pytest tests/test_command_builtins.py -v -k worktree`

## T14: TUI 适配 + 注入 ctx**文件:** `src/forgecode/tui/worktree_adapter.py` + `src/forgecode/tui/app.py`
**依赖:** T11, T13
**步骤:**
1. `worktree_adapter.py`:实现 `WorktreeAdapter(WorktreeAccessor)`,内部持 `worktree.Manager` 与一个 `set_active_cwd: Callable[[str], None]` 回调,把方法转发并组装 `WorktreeSummary` 列表;`enter` 内部既调 `Manager.enter`,又调 `set_active_cwd(session.worktree_path)`
2. `app.py`:`forgecodeApp` 加属性 `worktree_mgr: worktree.Manager | None`、`active_cwd: str = ""`(空表示进程 cwd)
3. `forgecodeApp.__init__` 接收 `worktree_mgr`;构造时若 `manager.current_session()` 非 None,设 `self.active_cwd = session.worktree_path`
4. 实现 `worktree_accessor()` 方法返回 WorktreeAdapter 实例(传 lambda 设置 self.active_cwd)
5. 在主 Agent Run 调用入口(找 app.py 里 `self.agent.run(conv, mode)` 调用点),前置 `with with_cwd(self._effective_cwd()):` 包住整个 run 协程
6. `_effective_cwd()`:若 `self.active_cwd` 非空返回 active_cwd,否则返回 `str(Path.cwd())`

**验证:** `python -m forgecode` 可启动;`/worktree create x` + `/worktree enter x` + Read file(相对路径) 在 worktree 内成功

## T15: 主 cli 接入**文件:** `src/forgecode/cli.py` + `.gitignore`
**依赖:** T4-T14 全部
**步骤:**
1. `cli.py`:在 `subagent_catalog = load_subagent_catalog(root)` 后加:
   ```python
   try:
       worktree_mgr = worktree.Manager(root)
   except Exception as exc:
       print(f"Worktree 管理器降级: {exc}", file=sys.stderr)
       worktree_mgr = None
   else:
       asyncio.get_event_loop().create_task(
           worktree_mgr.sweep_stale(datetime.now() - timedelta(hours=24))
       )
   ```
2. `AgentTool` 构造末尾追加 `worktree_mgr=worktree_mgr`
3. `forgecodeApp` 构造新增 `worktree_mgr=worktree_mgr`
4. `.gitignore` 追加:
   ```
   # ch14: Worktree 隔离副本(仅供 SubAgent 与手动管理使用)
   .forgecode/worktrees/
   .forgecode/worktree_session.json
   ```

**验证:** `python -m forgecode` 可启动、`pytest` 全过、`ruff check` 通过

## T16: 端到端 tmux 验证**文件:** 无代码修改,运行测试
**依赖:** T15
**步骤:**
1. `uv sync` 装好依赖(或 `pip install -e .`)
2. 准备项目级自定义 Agent `.forgecode/agents/worktree-writer.md`(详见 checklist 场景 1)
3. tmux 启动 `python -m forgecode`,跑 checklist 端到端场景
4. 通过即标记 T16 完成

**验证:** 见 checklist.md 场景 1-6

## 执行顺序

```
T1 (slug)
  ↓
T2 (session) — T3 (git helper) — T8 (tool/ctx)
                                    ↓
T4 (manager construct)          T9 (改造 6 tools)
  ↓
T5 (create + setup)
  ↓
T6 (lifecycle)
  ↓
T7 (sweep)
  ↓
T10 (subagent.isolation)
  ↓
T11 (agent_worktree + _execute_with_worktree)
  ↓
T12 (AgentTool 接入)
  ↓
T13 (/worktree command) — T14 (TUI 接入)
                              ↓
T15 (cli.py + .gitignore)
  ↓
T16 (tmux 端到端)
```

T1/T2/T3/T8 之间可并行;其余按依赖顺序。