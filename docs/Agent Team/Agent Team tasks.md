# Agent Team Tasks## 文件清单

| 操作 | 文件 | 职责 |
|------|------|------|
| 新建 | `src/forgecode/team/__init__.py` | 包导出 |
| 新建 | `src/forgecode/team/types.py` | Team / TeammateInfo / BackendType 等类型 |
| 新建 | `src/forgecode/team/persistence.py` | sanitize、原子写、reload_from_disk_locked |
| 新建 | `src/forgecode/team/manager.py` | Manager.create/get/delete/add_member/set_member_active/remove_member |
| 新建 | `tests/test_team_manager.py` | Manager 单测 |
| 新建 | `src/forgecode/team/spawn.py` | spawn_teammate 主流程 |
| 新建 | `tests/test_team_spawn.py` | spawn 单测(in-process 路径) |
| 新建 | `src/forgecode/team/feature.py` | FORK_TEAMMATE flag 读取 |
| 新建 | `src/forgecode/team/mailbox/__init__.py` | Box.read/write/mark_read + Message 类型 |
| 新建 | `src/forgecode/team/mailbox/lock.py` | 文件锁机制 |
| 新建 | `src/forgecode/team/mailbox/message.py` | Message / MessageType |
| 新建 | `tests/test_team_mailbox.py` | 并发与 stale 锁测试 |
| 新建 | `src/forgecode/team/registry/__init__.py` | AgentNameRegistry |
| 新建 | `tests/test_team_registry.py` | 注册/解析/反查测试 |
| 新建 | `src/forgecode/team/tasks/__init__.py` | Task / Store / Filter / Patch |
| 新建 | `tests/test_team_tasks.py` | CRUD + 依赖关系测试 |
| 新建 | `src/forgecode/team/backend/__init__.py` | Backend Protocol + SpawnRequest + new_backend |
| 新建 | `src/forgecode/team/backend/detect.py` | detect() |
| 新建 | `tests/test_team_backend_detect.py` | 检测逻辑测试 |
| 新建 | `src/forgecode/team/backend/tmux.py` | Tmux Backend |
| 新建 | `tests/test_team_backend_tmux.py` | tmux 命令构造测试 |
| 新建 | `src/forgecode/team/backend/iterm2.py` | iTerm2 Backend |
| 新建 | `tests/test_team_backend_iterm2.py` | iterm2 命令构造测试 |
| 新建 | `src/forgecode/team/backend/inprocess.py` | InProcess Backend |
| 新建 | `tests/test_team_backend_inprocess.py` | in-process spawn 集成测试 |
| 新建 | `src/forgecode/team/tools/team_create.py` | TeamCreate 工具 |
| 新建 | `src/forgecode/team/tools/team_delete.py` | TeamDelete 工具 |
| 新建 | `src/forgecode/team/tools/task_create.py` | TaskCreate 工具 |
| 新建 | `src/forgecode/team/tools/task_get.py` | TaskGet 工具 |
| 新建 | `src/forgecode/team/tools/task_list.py` | TaskList 工具 |
| 新建 | `src/forgecode/team/tools/task_update.py` | TaskUpdate 工具 |
| 新建 | `src/forgecode/team/tools/send_message.py` | SendMessage 工具 |
| 新建 | `src/forgecode/team/tools/teammate_filter.py` | 队员专属工具白名单 |
| 新建 | `tests/test_team_tools.py` | 工具单测 |
| 新建 | `src/forgecode/coordinator/__init__.py` | is_enabled/allowed_tools/system_prompt_suffix |
| 新建 | `tests/test_coordinator.py` | 双锁测试 |
| 新建 | `src/forgecode/agent/team_hook.py` | TeamHook Protocol + TeammateContext |
| 修改 | `src/forgecode/agent/agent_tool.py` | 增加 team_name 参数 + TeamHook 委托 + with_team_hook 构造选项 |
| 新建 | `src/forgecode/agent/team_mailbox.py` | Loop 头部注入 incoming-messages reminder |
| 修改 | `src/forgecode/task/manager.py` | 加 on_task_done 回调;改用 registry.AgentNameRegistry |
| 修改 | `src/forgecode/tool/filter.py` | 新增 TEAMMATE_ALLOWED_TOOLS,扩展 FilterParams 加 teammate bool |
| 新建 | `src/forgecode/command/builtin_team.py` | /team list/info/delete/kill 4 个命令 |
| 修改 | `src/forgecode/tui/app.py` 与相关文件 | 接收 team_mgr、coordinator 标签 |
| 修改 | `src/forgecode/config/__init__.py` | Features 字段新增 coordinator_mode 与 fork_teammate |
| 修改 | `src/forgecode/cli/__init__.py` | wire team.Manager / coordinator,注册 7 个工具 |
| 新建 | `src/forgecode/cli/team_member.py` | --team-member 自治循环 |
| 修改 | `.forgecode/config.yaml.example` | 加示例 features 段(可选,不强制) |

## T1: 基础类型 — `src/forgecode/team/types.py`**文件:** `src/forgecode/team/types.py`
**依赖:** 无
**步骤:**
1. 定义 `BackendType(StrEnum)` 含 `TMUX` / `ITERM2` / `IN_PROCESS`
2. 定义 `@dataclass class Team`(F1):字段含 `_lock: asyncio.Lock`、`name`、`sanitized_name`、`lead_agent_id`、`backend`、`description`、`created_at`、`members`、派生路径字段(`config_dir`/`config_path`/`tasks_path`/`mailbox_dir`,序列化时跳过)
3. 定义 `@dataclass class TeammateInfo`(F2),字段对应 json key(下划线命名)
4. 定义异常类 `TeamNotFoundError` / `TeamHasActiveMembersError` / `MemberExistsError` / `MemberNotFoundError` / `InProcessTeammateNoSpawnError`,统一基类 `TeamError`

**验证:** `python -c "from forgecode.team.types import Team, TeammateInfo, BackendType"` 不报错;`ruff check src/forgecode/team/types.py` 通过

## T2: sanitize 与原子写 — `src/forgecode/team/persistence.py`**文件:** `src/forgecode/team/persistence.py`
**依赖:** T1
**步骤:**
1. 实现 `sanitize(name: str) -> str`——只保留 `[a-zA-Z0-9._-]`,其他字符替换为 `-`,首尾去 `-`,空字符串返回 `""`(用 `re.sub`)
2. 实现 `atomic_write_json(path: str | Path, value: Any) -> None`——`json.dumps(indent=2)` → 写 `<path>.tmp` → `os.replace`
3. 实现 `read_json(path: str | Path) -> Any`——`Path.read_text()` + `json.loads`,文件不存在抛 `FileNotFoundError`

**验证:** 单测断言 `sanitize("foo bar/baz")=="foo-bar-baz"`;`atomic_write_json` 写入后 `read_json` 取回相等

## T3: Manager 与持久化 — `src/forgecode/team/manager.py`**文件:** `src/forgecode/team/manager.py`
**依赖:** T1, T2
**步骤:**
1. 定义 `class Manager`(F3)
2. 实现 `Manager.__init__(home_dir, project_root, wt_mgr, task_mgr, reg)`(F4)
   - 创建 `<home_dir>/.forgecode/teams/` 目录
   - 扫描子目录,逐个读 `config.json`(失败 stderr 警告并跳过)
   - 反序列化后填充派生路径字段
3. 实现 `Manager.get(name: str) -> Team | None`
4. 实现 `Manager.list_() -> list[Team]`(按创建时间排序)
5. 实现 `async Manager.create(name, description)`(F5)
   - sanitize + 同名冲突 `-2`/`-3` 后缀
   - 取 `detect()`(暂时硬编码 `BackendType.IN_PROCESS`,后面 T11 接 detect)
   - 创建 `config_dir`、`mailbox_dir`
   - 注册 Lead 成员
   - `atomic_write_json`
6. 实现 `async Manager.delete(name, force)`(F7 + F66):
   - 持锁、找到 Team、(force=False 时)校验全员 is_active=False
   - 对每个非 lead 成员:用 `backend.new_backend(mem.backend_type)` 解析后端,调 `await backend.kill(mem.pane_id, mem.agent_id)` 杀 pane(tmux/iterm2)或 cancel asyncio task(in-process)
   - 调 `_cleanup_member_resources` 删 session 目录与 worktree(best-effort)
   - `shutil.rmtree(team.config_dir)` 删整个 Team 目录
   - 从 in-memory dict 移除
   - 没注入 backend deps 的测试场景跳过 kill,fallback 只清磁盘资源

**验证:** 写单测覆盖 create/get/delete 基本流程;`pytest tests/test_team_manager.py` 通过;tmux 实跑后 `/team delete --force` 看 pane 真的被杀(`tmux list-panes` 只剩 Lead)

## T3b: Team.Manager 跨进程并发兜底 — 继续 `src/forgecode/team/manager.py` + `src/forgecode/team/persistence.py`**文件:** `src/forgecode/team/manager.py`(为 add_member / set_member_active 加 reload-before-modify)、`src/forgecode/team/persistence.py`(增加 `reload_from_disk_locked`)
**依赖:** T3
**步骤:**
1. `persistence.py` 增 `async def reload_from_disk_locked(team: Team) -> None`——调用方持锁;从 `team.config_path` `read_json`,把 `members` 字段覆盖到 in-memory(失败静默回退到内存现状)
2. `Team.add_member` 与 `Team.set_member_active`(以及任何会修改 members 后 save 的方法)在加锁后**先**调 `await reload_from_disk_locked(self)` 再操作内存 + save
3. 不是为了 asyncio 内的并发——in-process 早就有 `_lock` 保护;**是为了跨进程**:Pane 后端的 Lead 与子进程是两个独立进程,各持一份内存中的 Team。如果不 reload,会出现"子进程读 config 时 Lead 的 add_member 还没写入,子进程修改自己内存 Team 没看见自己,set_member_active 静默 no-op"的丢更新

**验证:** 单测构造时序:t1 = read_json 得到无 alice 的 Team A;t2 在 disk 上写带 alice 的 Team B;t3 调 `await team.set_member_active("alice", False)` 应该成功(走 reload 路径)而非静默 no-op

## T4: Team 成员操作 — 继续 `src/forgecode/team/manager.py`**文件:** `src/forgecode/team/manager.py`(同 T3)
**依赖:** T3
**步骤:**
1. 实现 `async Team.add_member(info)`(F8)——加锁后**先 reload_from_disk_locked**(见 T3b),检查重名;加入 members;持久化
2. 实现 `async Team.set_member_active(name, active)`(F9)——加锁后**先 reload_from_disk_locked**;遍历 members 找到 name 改 is_active 字段;持久化
3. 实现 `async Team.remove_member(name)`(F10)
4. 实现 `Team.member_by_name(name) -> TeammateInfo | None` / `Team.member_by_agent_id(id_) -> TeammateInfo | None` 工具方法

**验证:** 单测覆盖 add → set_active → remove 三步流程,读回 config.json 校验字段

## T5: mailbox 文件锁 — `src/forgecode/team/mailbox/lock.py`**文件:** `src/forgecode/team/mailbox/lock.py`
**依赖:** 无
**步骤:**
1. 实现 `async def acquire_lock(lock_path: str) -> AsyncContextManager[None]`——
   - 循环 10 次:`os.open(lock_path, O_CREAT|O_EXCL|O_WRONLY, 0o644)` 抢锁
   - 失败时 `Path(lock_path).stat()`,若 `time.time() - st_mtime > 10` 则 `os.unlink(lock_path)` 后立即重试一次
   - 失败时 `await asyncio.sleep(random.uniform(0.005, 0.1))` 抖动后继续
   - context manager 退出时:`os.unlink(lock_path)`
2. 内部常量 `LOCK_MAX_RETRIES = 10` / `LOCK_STALE_AFTER = 10.0` / `LOCK_BACKOFF_MIN = 0.005` / `LOCK_BACKOFF_MAX = 0.1`

**验证:** 单测 `test_acquire_lock_serial`(两次抢锁,中间 release)、`test_acquire_lock_stale`(故意创建 11 秒前的锁——`os.utime(lock_path, (now-11, now-11))`,断言能拿到)

## T6: mailbox Message 与 Box — `src/forgecode/team/mailbox/__init__.py` + `message.py`**文件:** `src/forgecode/team/mailbox/__init__.py`、`src/forgecode/team/mailbox/message.py`
**依赖:** T5
**步骤:**
1. `message.py` 定义 `MessageType(StrEnum)` 与 4 个常量(F32)
2. `message.py` 定义 `@dataclass class Message`(F32),提供 `to_dict()` / `from_dict()`(注意 `from_` 字段对应 json key `"from"`)
3. `__init__.py` 定义 `class Box`,字段 `_dir: str`
4. 实现 `Box.__init__(dir_)`——`Path(dir_).mkdir(parents=True, exist_ok=True)`
5. 实现 `async Box.write(agent_id, msg)`(F33)
   - `lock_path = f"{self._dir}/{agent_id}.lock"`
   - `async with acquire_lock(lock_path):`
   - 读 `<dir>/<agent_id>.json`(不存在视为 `{"messages":[]}`)
   - 追加 msg(若 timestamp=0 设为 `int(time.time())`)
   - `atomic_write_json`
6. 实现 `async Box.read(agent_id) -> list[Message]`
7. 实现 `async Box.read_unread(agent_id) -> tuple[list[int], list[Message]]`——返回 unread 消息的 indices 与消息本身
8. 实现 `async Box.mark_read(agent_id, indices)`——按 indices 把对应消息 `read=True`

**验证:** 单测覆盖 write/read/mark_read;并发测试 10 个 asyncio task 写同一 agent_id,断言读回 10 条无丢失

## T7: AgentNameRegistry — `src/forgecode/team/registry/__init__.py`**文件:** `src/forgecode/team/registry/__init__.py`
**依赖:** 无
**步骤:**
1. 定义 `class AgentNameRegistry`
2. 实现 `__init__()`
3. 实现 `register(name, agent_id)`——若 name 已存在覆盖(取出旧 agent_id,从 `_by_id` 删旧映射);若 agent_id 已有其他 name,先反向 unregister
4. 实现 `unregister(name)`
5. 实现 `unregister_by_agent_id(agent_id)`
6. 实现 `resolve(name_or_id) -> str | None`——先按 name 查,再按 agent_id 反向查
7. 实现 `name_of(agent_id) -> str | None`
8. 实现 `list_() -> dict[str, str]`

**验证:** 单测覆盖 register/unregister/resolve/name_of;包括「同名覆盖」和「不同名指向同一 agent_id」边界

## T8: tasks Store — `src/forgecode/team/tasks/__init__.py`**文件:** `src/forgecode/team/tasks/__init__.py`
**依赖:** T5(用 mailbox 的 lock)
**步骤:**
1. 定义 `Status(StrEnum)` / `Task` / `Filter` / `Patch` 类型(F30)
2. 定义 `class Store`,字段 `_path: str`, `_lock: asyncio.Lock`
3. 实现 `__init__(path)`
4. 实现 `async create(t) -> str`——生成 `task_<6 位 hex>` ID(`secrets.token_hex(3)`);read-modify-write `tasks.json`(用 lock 文件,路径 `<path>.lock`,复用 mailbox 的 `acquire_lock`——把它提到 `forgecode.team.filelock` 共用包,或直接在 tasks 包内复制小段实现)
5. 实现 `async get(id_) -> Task`
6. 实现 `async list_(f: Filter) -> list[Task]`——按 `status` 过滤,返回时附加 `is_ready` 字段(检查 blocked_by 中所有任务是否 completed);为简化可在 list_ 输出时计算 ready 标记,不存盘
7. 实现 `async update(id_, p: Patch)`——支持 title/description/status/assignee/add_blocks/add_blocked_by/remove_blocks/remove_blocked_by 字段
8. `add_blocked_by=[X]` 同时给 X 任务 `blocks` 加上当前任务 id(双向维护)

**注意:** 为减小循环依赖,把 `acquire_lock` 提到独立 `forgecode.team.filelock` 模块,mailbox 与 tasks 共用。

**验证:** 单测覆盖 create/get/update;特别测 add_blocked_by 的双向更新

## T9: 共用 filelock 模块(从 mailbox 抽出)**文件:** `src/forgecode/team/filelock.py`(把 T5 实现迁过来)
**依赖:** 无
**步骤:**
1. 把 T5 的 `acquire_lock` 实现迁到 `forgecode.team.filelock`,签名保持 `async def acquire(lock_path) -> AsyncContextManager[None]`
2. 在 `mailbox/lock.py` 改为 `from forgecode.team.filelock import acquire`,删除本地实现
3. 在 `tasks/__init__.py` 也 import `filelock`

**验证:** `pytest tests/test_team_*.py` 全过

## T10: backend Protocol — `src/forgecode/team/backend/__init__.py`**文件:** `src/forgecode/team/backend/__init__.py`
**依赖:** T1
**步骤:**
1. 定义 `@dataclass class SpawnRequest`(F13)——其中 `sub_agent` / `conv` / `task_mgr` 字段类型为 `Any`,避免 backend 反向依赖 agent 包
2. 定义 `Backend` Protocol(F12):`type() -> BackendType`、`async spawn(req) -> tuple[str, str]`(返回 `(pane_id, agent_id)`)、`async wake(pane_id, agent_id) -> None`、`async kill(pane_id, agent_id) -> None`
3. 定义 `def new_backend(t: BackendType, **deps) -> Backend` 工厂——按类型分发(暂时只占位,具体实现在 T12-T14)

**验证:** `python -c "from forgecode.team.backend import Backend, SpawnRequest, new_backend"` 通过

## T11: detect_backend — `src/forgecode/team/backend/detect.py`**文件:** `src/forgecode/team/backend/detect.py`
**依赖:** T10
**步骤:**
1. 实现 `def detect() -> BackendType`(F14):
   - `os.environ.get("TMUX")` → `TMUX`
   - `os.environ.get("TERM_PROGRAM") == "iTerm.app"` 且 `shutil.which("it2")` → `ITERM2`
   - `shutil.which("tmux")` → `TMUX`
   - 否则 `IN_PROCESS`

**验证:** 写 test 用 `monkeypatch.setenv` 控制环境变量 + monkeypatch.setattr 替换 `shutil.which`,断言不同组合的返回值

## T12: tmux backend — `src/forgecode/team/backend/tmux.py`**文件:** `src/forgecode/team/backend/tmux.py`
**依赖:** T10
**步骤:**
1. 定义 `class TmuxBackend`
2. 实现 `__init__()` 与 `type()` 返回 `BackendType.TMUX`
3. 实现 `async spawn(req)`(F15):
   - 在 `$TMUX` 内:`tmux split-window -h -P -F "#{pane_id}" -- <cmd>`
   - 在 `$TMUX` 外但 `tmux` 二进制可用:`tmux new-session -d`(detached 新会话)走外部 session(F16)
   - `cmd` 构造:`python -m forgecode --team-member --team <team_name> --member <member_name> --agent-id <agent_id> --session-dir <session_dir> --worktree <wt_path> [--agent-type <type>] [--model <model>] [--plan-mode]`(可用 `shlex.quote` 转义)
   - `--agent-id` 必须传——子进程不需要读 Lead 还没写完的 `config.json` 找自己
   - `initial_prompt` **不**走命令行,由 `team.spawn_teammate`(T18)在 `backend.spawn` 之前预写入 alice mailbox
   - 用 `await asyncio.create_subprocess_exec("tmux", ...)` 跑 tmux,捕获 stdout 作为 pane_id
4. 实现 `async wake(pane_id, agent_id)`:`tmux send-keys -t <pane_id> "" Enter`(子进程 stdin reader 读到回车,立刻去 mailbox 轮询)
5. 实现 `async kill(pane_id, agent_id)`:`tmux kill-pane -t <pane_id>`,忽略 pane not found 错误

**注意:** spawn 启动的 forgecode CLI 需要支持 `--team-member` flag;这部分留给 T21(cli/__init__.py 改造)+ T29(team_member.py 新建)

**验证:** 单测断言命令字符串构造正确(用 monkeypatch.setattr 替换 `asyncio.create_subprocess_exec` 收 args);集成测试在 CI 跳过(需要 tmux)

## T13: iterm2 backend — `src/forgecode/team/backend/iterm2.py`**文件:** `src/forgecode/team/backend/iterm2.py`
**依赖:** T10
**步骤:**
1. 实现 `Iterm2Backend.spawn`:`it2 split --new-pane --command "<cmd>"`(实际 it2 CLI 命令以官方为准;先按 README 描述实现,实测可能要调);`<cmd>` 同 T12 格式,含 `--agent-id`,`initial_prompt` 走 mailbox 预写
2. 实现 `wake`:`it2 send-text --pane <pane_id> ""`
3. 实现 `kill`:`it2 close-pane --pane <pane_id>`

**注意:** iterm2 后端无法在 CI 中实跑,实现以构造正确的命令字符串为准

**验证:** 单测断言命令构造正确

## T14: in-process backend — `src/forgecode/team/backend/inprocess.py`**文件:** `src/forgecode/team/backend/inprocess.py`
**依赖:** T10,需要 `agent`、`task`、`conversation` 包
**步骤:**
1. 定义 `class InProcessBackend`,字段 `_task_mgr: task.Manager`
2. 实现 `async spawn(req)`(F18):
   - 从 `req.sub_agent` / `req.conv` 取已构造好的对象
   - 调 `await task_mgr.launch(sub_agent, conv, req.member_name, req.initial_prompt)` 起 asyncio task
   - 返回 `("", task_id)`——in-process 用 agent_id 作为目标 id,pane_id 为空
3. 实现 `async wake(pane_id, agent_id)`:no-op,直接 return
4. 实现 `async kill(pane_id, agent_id)`:`await task_mgr.stop(agent_id)`

**Backend Protocol 签名统一**(回 T10 调整):
```python
class Backend(Protocol):
    def type(self) -> BackendType: ...
    async def spawn(self, req: SpawnRequest) -> tuple[str, str]: ...   # (pane_id, agent_id)
    async def wake(self, pane_id: str, agent_id: str) -> None: ...
    async def kill(self, pane_id: str, agent_id: str) -> None: ...
```
Pane 后端用 pane_id,in-process 用 agent_id;Protocol 统一传两者,各自取需要的。

**验证:** 单测:构造 fake task_mgr,spawn 一个 noop 子 Agent,断言 asyncio task 启动

## T15: feature flag — `src/forgecode/team/feature.py`**文件:** `src/forgecode/team/feature.py`
**依赖:** 无
**步骤:**
1. 实现 `def fork_teammate_enabled(cfg: Config) -> bool`——读 `cfg.features.fork_teammate`

**验证:** 单测覆盖 True/False 两种 cfg

## T16: TeammateContext — `src/forgecode/agent/team_hook.py`**文件:** `src/forgecode/agent/team_hook.py`
**依赖:** 无
**步骤:**
1. 定义 `TeamHook` Protocol(plan.md 已给签名)
2. 定义 `@dataclass class TeamSpawnRequest`(把 Agent 工具参数传过去)
3. 定义 `@dataclass class TeammateContext`——`team_name`、`member_name`、`agent_id`、`mailbox_dir`、`send_message_wake: Callable[[str], Awaitable[None]]` 等
4. 提供 `WITH_TEAMMATE_KEY = "teammate"` + `with_teammate_context(ctx, tc) -> dict` + `teammate_context_from_ctx(ctx) -> TeammateContext | None`(用 dict 作为 ctx 容器或 `contextvars.ContextVar` 也行)

**验证:** `python -c "from forgecode.agent.team_hook import TeamHook, TeammateContext"` 通过

## T17: 队员专属工具白名单 — `src/forgecode/tool/filter.py` 扩展**文件:** `src/forgecode/tool/filter.py`(修改)
**依赖:** 无
**步骤:**
1. 新增常量:
   ```python
   TEAMMATE_EXTRA_TOOLS: list[str] = [
       "TaskCreate", "TaskGet", "TaskList", "TaskUpdate", "SendMessage",
   ]
   ```
2. 扩展 `FilterParams` dataclass 加 `teammate: bool = False` 字段
3. 在 `apply_agent_tool_filter` 中:若 `teammate=True`,把 `TEAMMATE_EXTRA_TOOLS` 加到允许集合(在 disallowed 删除之前);非 teammate 时排除这些工具(主 Agent 看不到)
4. 同时增加常量 `TEAM_LEAD_DISALLOWED_TEAMMATE_TOOLS`——避免主 Agent 直接看到 TaskCreate 等(应该走 `teammate=True` 才能加上)

**简化策略:** `TEAMMATE_EXTRA_TOOLS` 不进默认 registry(由 `cli/__init__.py` 注册到 registry,但默认从 ALL 过滤集移除);`teammate=True` 时把它们加回。

**采用:**
- `cli/__init__.py` 把 5 个协作工具注册到 registry
- 修改默认 filter:`ALL_AGENT_DISALLOWED_TOOLS` 加上这 5 个工具(子 Agent 默认看不到)
- 新增 `TEAMMATE_ALLOWED_TOOLS = ALL_AGENT_DISALLOWED_TOOLS 中的协作工具`
- 修改 `apply_agent_tool_filter`:`teammate=True` 时,这 5 个工具不被 ALL 过滤

**验证:** 单测覆盖 `teammate=True / False`,断言 TaskCreate 等可见性

## T18: spawn_teammate 主流程 — `src/forgecode/team/spawn.py`**文件:** `src/forgecode/team/spawn.py`
**依赖:** T1-T17
**步骤:**
1. 定义 `async Manager.spawn_teammate(req: TeamSpawnRequest) -> str`
2. 实现 plan.md 中描述的步骤流程:
   - 取 Team
   - 校验调用者权限(看 ctx 是否有 TeammateContext,且 backend_type=in-process 时拒绝)
   - 解析 `SubAgentDefinition`
   - `await wt_mgr.create(f".forgecode/worktrees/team-{sanitized}+{member}")`
   - 申请 session_dir(本期复用 ch12 格式,自己生成新 id)
   - 预生成 agent_id(`f"agent-{secrets.token_hex(7)}"`),构造 SpawnRequest 含 agent_id 字段
   - 计算 allowed = `apply_agent_tool_filter(FilterParams(teammate=True, ...))`、system_prompt = `def.system_prompt + team_system_prompt_suffix()`
   - 若 backend_type=in-process:构造 sub_agent(**强制 `dont_ask=True`** F39a)+ sub_conv,注入 `<team-context>` reminder + ctx 装 `TeammateContext(mailbox=mc)`
   - 若 backend_type=tmux/iterm2:`await Box(t.mailbox_dir).write(agent_id, Message(from_="lead", type=TEXT, summary=..., content=req.prompt))` 预写初始任务(F13)
   - `await backend.spawn(req)` 取 `(pane_id, agent_id)`
   - `registry.register(member_name, agent_id)`
   - `await team.add_member(...)` (调用时 `reload_from_disk_locked` 保护跨进程并发)
   - 返回 JSON `{"member_name", "agent_id", "worktree", "backend", "pane_id"}`
3. 提供 helper `build_team_context_reminder(team, member, agent_id)` 构造 `<team-context>` reminder
4. 提供 helper `team_system_prompt_suffix() -> str` 返回 F39 附录;`truncate_for_summary(prompt)` 给初始任务 mailbox 消息生成 summary

**验证:** 单测覆盖 in-process 后端的 spawn 全流程;Pane 后端的 spawn 用 mock backend

## T19: Agent 工具集成 — `src/forgecode/agent/agent_tool.py` 修改**文件:** `src/forgecode/agent/agent_tool.py`(修改)
**依赖:** T16, T18
**步骤:**
1. `AgentToolArgs` dataclass 加 `team_name: str = ""`
2. `AgentTool` 加字段 `team_hook: TeamHook | None = None`
3. `AgentTool.__init__` 加参数 `team_hook`
4. `description()` 中说明 `team_name` 参数(可选,非空时走 Team spawn)
5. `parameters()` 加 `team_name` 字段
6. `execute` 在 `args.team_name != ""` 时:
   - 校验 `self.team_hook is not None`,否则抛错
   - 校验 ctx 不在 in-process 队员中(`self.team_hook.is_teammate_context(ctx)`,若是且 backend_type=in-process,抛 `InProcessTeammateNoSpawnError`)
   - 调 `await self.team_hook.spawn_teammate(TeamSpawnRequest(team_name=..., member_name=args.name, ...))`
   - 返回 spawn_teammate 的结果

**验证:** 单测:不带 team_name 走 ch13 老路径;带 team_name 调 mock team_hook,断言 spawn_teammate 被调

## T20: 队员 Loop incoming-messages 注入 — `src/forgecode/agent/team_mailbox.py`**文件:** `src/forgecode/agent/team_mailbox.py`
**依赖:** T16, T6
**步骤:**
1. 在 `agent.Agent.run` / `run_to_completion` 的迭代头部(调 LLM 前),检查 ctx 中是否有 TeammateContext;实现位于 `forgecode.agent.team_mailbox.ingest_team_mailbox`
2. 若有,调 `await tc.read_unread()`
3. 若有未读消息,构造 `<incoming-messages>` reminder 字符串(F42),加到 `runtime.pending_reminders`(下一轮 `build_reminder` 取出)
4. 调 `await tc.mark_read(indices)`
5. 若收到 `plan_approval_response(approve=True)`,调 `agent.set_permission_mode(PermissionMode.DEFAULT)` 切回 default(reminder 文本也会反映这一切换)。**注意:** Pane 后端子进程的 plan_approval 由 `run_team_member` 主循环额外处理一份——它读到 plan_approval_response 时同样切模式 + 合成续派 prompt 让 `run_to_completion` 接着跑(F19a)

**注意:** `agent` 包不直接 import `mailbox`(避免循环);通过 `TeammateContext` 中的 `Box` 字段访问;或通过 Protocol 抽象(`class MailboxReader(Protocol): async def read_unread(...); async def mark_read(...)`)。

**采用 Protocol:**
```python
# agent/team_hook.py
class MailboxReader(Protocol):
    async def read_unread(self, agent_id: str) -> tuple[list[int], list[Any]]: ...
    async def mark_read(self, agent_id: str, indices: list[int]) -> None: ...
```
import 还是会成环——把 Message 类型也抽象成 Protocol 或 `dict[str, Any]`。**简化:** TeammateContext 持 `read_unread: Callable[[], Awaitable[tuple[list[int], list[IncomingMessage]]]]` 闭包,由 spawn 时由 team 包注入。Message 在 agent 包定义一个轻量 dataclass `IncomingMessage`,只取需要的字段。

**采用最简方案:** 在 `agent` 包内定义 `@dataclass class IncomingMessage`(独立于 `mailbox.Message`),`TeammateContext` 携带 `read_unread`/`mark_read` 闭包;由 team 包在 spawn 时构造闭包注入。

**验证:** 单测覆盖:fake mailbox 写入 1 条消息,启动子 Agent.run,断言 reminder 含 `<incoming-messages>`

## T21: task.Manager 改造 — `src/forgecode/task/manager.py` 修改**文件:** `src/forgecode/task/manager.py`(修改)
**依赖:** T7
**步骤:**
1. `Manager` 持一个 `name_reg: AgentNameRegistry | None` 引用(可选 None 兜底)
2. `launch` 时:若 `name_reg` 非 None 且 name 非空,调 `name_reg.register(name, id_)`;同时保持本地 `_by_name` 兜底(避免破坏 ch13 既有调用)
3. `get_by_name` 优先用 `name_reg.resolve` 查
4. `send_message(parent_ctx, name, message)` 优先 `name_reg.resolve`
5. 新增 `on_task_done(fn: Callable[[str], Awaitable[None]])` 注册接口,可注册多个回调
6. `_run_task` 的 try/finally 末尾(在 `notify_done` 后)逐个 `await` 调 `on_task_done` 回调
7. 加 `set_name_registry(reg)` setter

**验证:** 单测:注册 `on_task_done`,`launch` 一个 noop task,等完成,断言回调被触发

## T22: 协作工具实现 — `src/forgecode/team/tools/`**文件:** `team_create.py` / `team_delete.py` / `task_create.py` / `task_get.py` / `task_list.py` / `task_update.py` / `send_message.py`
**依赖:** T3, T6, T7, T8
**步骤:**
1. 每个工具实现 `tool.Tool` Protocol(`name`/`description`/`parameters`/`read_only`/`execute`)
2. `TeamCreate`(F21):参数 `team_name` + `description`;`execute` 调 `await manager.create`,返回 JSON
3. `TeamDelete`(F23):参数 `team_name` + `force`;`execute` 调 `await manager.delete`
4. `TaskCreate`(F26):参数 `title`/`description`/`assignee`/`blocked_by`;从 ctx 取 TeammateContext 找当前 Team;`execute` 调 `await store.create`
5. `TaskGet`(F27):参数 `task_id`
6. `TaskList`(F28):参数 `status` 过滤;返回带 `is_ready` 字段的 JSON 数组
7. `TaskUpdate`(F29):参数 `task_id` + 各 Patch 字段
8. `SendMessage`(F34):参数 `to`/`summary`/`message`/`type`/`payload`;`execute` 调 `await mailbox.write` + `await backend.wake` + 续派检测
9. 每个工具 `read_only` 返回:TeamCreate/Delete/TaskCreate/Update/SendMessage 返回 False;TaskGet/TaskList 返回 True

**验证:** 每个工具一个单测覆盖正常路径与错误路径

## T23: 协作工具白名单生效 — 验证**文件:** `tests/test_tool_filter.py`(修改)
**依赖:** T17, T22
**步骤:**
1. 在 `apply_agent_tool_filter` 测试中加用例:
   - 主 Agent(`teammate=False`)调用:看不到 TaskCreate / SendMessage 等
   - 队员(`teammate=True`)调用:看到这 5 个

**验证:** 测试通过

## T24: coordinator 包 — `src/forgecode/coordinator/__init__.py`**文件:** `src/forgecode/coordinator/__init__.py`
**依赖:** 无
**步骤:**
1. 实现 `def is_enabled(cfg: Config) -> bool`——`cfg.features.coordinator_mode and env_truthy(os.environ.get("FORGECODE_COORDINATOR_MODE", ""))`
2. 实现 `def allowed_tools() -> list[str]`(F53)
3. 实现 `def system_prompt_suffix() -> str`(F55)——除四阶段框架外,**必须**包含"派完队员就停手等汇报"的纪律段:派出 Agent/SendMessage 后禁止立刻 read_file/glob/grep/bash 自己探索;禁止 sleep/TaskList 凑时间;只在 Research 首次定位 / Synthesis 读队员产出 / Verification 收敛 时才允许自己用读类工具
4. 实现 `def env_truthy(v: str) -> bool`——`v.lower() in {"1", "true", "yes"}`

**验证:** 单测覆盖双锁的 4 种组合(00/01/10/11),只有 11 返回 True;tmux 实跑观察 Lead 派完队员后不立刻 glob/read_file 而是"等待汇报"

## T25: config 加 features — `src/forgecode/config/__init__.py` 修改**文件:** `src/forgecode/config/__init__.py`(修改)
**依赖:** 无
**步骤:**
1. 加 `@dataclass class FeaturesConfig`,字段 `coordinator_mode: bool = False` + `fork_teammate: bool = False`
2. `Config` 加字段 `features: FeaturesConfig = field(default_factory=FeaturesConfig)`
3. `load` 时若 yaml 含 `features:` 段,用 `FeaturesConfig(**raw["features"])` 解析

**验证:** 单测加载 yaml 含 `features:` 段,断言字段被读出

## T26: TUI 集成 — `src/forgecode/tui/app.py` 修改**文件:** `src/forgecode/tui/app.py` 与可能的 view 文件(修改)
**依赖:** T3, T24
**步骤:**
1. `ForgeCodeApp.__init__` 加 `team_mgr: team.Manager`、`coordinator_mode: bool = False`
2. `ForgeCodeApp` 加字段 `coordinator_mode: bool` 与 `lead_mail_event: asyncio.Event`;`__init__` 时 `lead_mail_event = asyncio.Event()`
3. coordinator 应用迁到 `src/forgecode/cli/__init__.py` 中的 main_agent 上(`set_allowed_tools` + `append_system_prompt`)——tui 自身只负责状态栏渲染
4. 状态栏渲染时若 `app.coordinator_mode is True` 在 mode label 后追加 ` [COORDINATOR]`(参见 `src/forgecode/tui/view.py status_bar()`)
5. config 字段名是 **snake_case**:`features.coordinator_mode`

**验证:** 在 config.yaml 加 `features:\n  coordinator_mode: true`,启动时设环境变量 `FORGECODE_COORDINATOR_MODE=1`,观察状态栏出现 `[COORDINATOR]`

## T27: /team slash 命令 — `src/forgecode/command/builtin_team.py`**文件:** `src/forgecode/command/builtin_team.py`
**依赖:** T3
**步骤:**
1. 注册 4 个本地命令(`Kind.LOCAL`):
   - `/team list`(F59)
   - `/team info <name>`(F60)
   - `/team delete <name> [--force]`(F61)
   - `/team kill <member>`(F62)
2. 在 `register_builtins` 或对应注册入口加入

**验证:** `/team list` 在 TUI 输出含已创建 Team

## T28: cli wire — `src/forgecode/cli/__init__.py` 修改**文件:** `src/forgecode/cli/__init__.py`(修改)
**依赖:** T1-T27
**步骤:**
1. 构造 `name_reg = AgentNameRegistry()`
2. `task_mgr.set_name_registry(name_reg)`
3. 构造 `team_mgr = team.Manager(home, root, worktree_mgr, task_mgr, name_reg)`
4. 注册 7 个新工具到 registry(TeamCreate/TeamDelete/TaskCreate/TaskGet/TaskList/TaskUpdate/SendMessage)
5. `agent_tool = AgentTool(..., team_hook=team_mgr)`(把 team_mgr 作为 TeamHook 注入)
6. 构造 `ForgeCodeApp(..., team_mgr=team_mgr, coordinator_mode=coordinator.is_enabled(cfg))`
7. 若 `--team-member` flag 出现:**所有依赖 wire 完成后**直接调 `await run_team_member(team_member_args)` 并 `return`,**不**构造 TUI(F19a);否则继续走 TUI 路径
8. Lead 启动时(TUI 路径)若 `coordinator.is_enabled(cfg)`:`main_agent.set_allowed_tools(coordinator.allowed_tools())` + `main_agent.append_system_prompt(coordinator.system_prompt_suffix())`

**验证:** `python -m forgecode` 主流程能启动 TUI;`ruff check src/forgecode/cli/` 通过

## T29: --team-member 自治循环 — `src/forgecode/cli/team_member.py`(新文件)**文件:** `src/forgecode/cli/team_member.py`(新建)
**依赖:** T28
**步骤:**
1. 解析新增 CLI flags:`--team-member` / `--team` / `--member` / `--agent-id` / `--session-dir` / `--worktree` / `--agent-type` / `--model` / `--plan-mode`(用 `argparse` 或 `click`)
2. `cli/__init__.py` 中在 `--team-member` 分支先 `os.chdir(args.worktree)`,再 wire 完所有依赖
3. 实现 `async def run_team_member(args)`:
   - 从 `args.team_mgr.get(team_name)` 拿 Team(已含 Lead 写入的 alice 条目,reload-from-disk 兜底)
   - 解析角色定义(`subagent.catalog.resolve(agent_type)`),拿 system_prompt / max_turns / plan 等
   - 用 `apply_agent_tool_filter(FilterParams(teammate=True, ...))` 算 allowed tools
   - 构造 provider(`llm.new_provider`)+ `agent.Agent`,**强制 `dont_ask=True`**(F39a)
   - 注入 `<team-context>` reminder(F40) + ctx 装 `TeammateContext(mailbox=mc)`
   - 起一个 stdin reader asyncio task(`loop.add_reader(sys.stdin.fileno(), ...)` 或 `asyncio.StreamReader` over stdin):每读一行就 `wake_event.set()`,触发 mailbox 即时轮询
   - 进主循环(F19a):read unread → 分流消息(text 拼 task / plan_approval / shutdown_request)→ `run_to_completion` → 通知 Lead idle → `set_member_active(False)` → 等下一条
   - 检测 mailbox 目录消失 → 优雅退出
4. 把 `agent.Event` 流转 stdout 打印(`print_agent_event`),pane 内呈现只读日志

**验证:** 见 AC28 步骤 4 端到端实跑——alice pane 内显示 task 执行流,`/tmp/test_alice.txt` 落地,SendMessage 后 alice 能续派

## T30: 队员空闲通知 hook 注入**文件:** `src/forgecode/cli/__init__.py`(修改)+ `src/forgecode/team/manager.py`(加 helper)
**依赖:** T21, T3
**步骤:**
1. 在 `cli/__init__.py` wire 后,注册 `on_task_done` 回调到 `task_mgr`:
   ```python
   async def _on_done(task_id: str) -> None:
       await team_mgr.handle_task_done(task_id)
   task_mgr.on_task_done(_on_done)
   ```
2. 实现 `async Manager.handle_task_done(agent_id)`:
   - 查 `registry.name_of(agent_id) → name`
   - 遍历 teams 找到该成员所属 Team
   - `await set_member_active(name, False)`
   - `await mailbox.write(lead_agent_id, Message(type=TEXT, summary=f"{name} idle"))`

**验证:** 集成测试:in-process 后端 spawn 队员 → 自然结束 → 断言 Team.config 中 `is_active=False`、Lead mailbox 有 idle 消息

## T30b: Lead mailbox 轮询 + 自动唤醒 — `src/forgecode/team/manager.py` + `src/forgecode/tui/tasks.py` + `src/forgecode/tui/app.py` + `src/forgecode/tui/stream.py`**文件:**
- `src/forgecode/team/manager.py`(增加 `poll_lead_mailboxes` + `LeadMessage`)
- `src/forgecode/tui/tasks.py`(增加 `consume_lead_mail` / `wait_for_lead_mail` / `build_team_update_reminder` / `lead_mail_message`)
- `src/forgecode/tui/app.py`(`on_mount` 启动 watcher;`on_message` 处理 `LeadMailMessage`)
- `src/forgecode/tui/stream.py`(增加 `begin_autonomous_turn`)
**依赖:** T28(cli 已 wire team_mgr 进 TUI 参数)
**步骤:**
1. `team.Manager.poll_lead_mailboxes()`:遍历 `m.list_()`,对每个 Team 用 `Box(t.mailbox_dir).read_unread(t.lead_agent_id)` 读未读,标 read,返回 `list[LeadMessage(team_name, from_, type, summary, content, time)]`
2. TUI App 加字段 `lead_mail_event: asyncio.Event`(`__init__` 时初始化)
3. `consume_lead_mail`(TUI `on_mount` 启动 asyncio task):1 秒 sleep ticker → `poll_lead_mailboxes` → 非空时调 `build_team_update_reminder`(列消息条目 + content 截断 8000 字)→ `runtime.append_reminders` → `lead_mail_event.set()`
4. `wait_for_lead_mail(event)`:asyncio task,`await event.wait()` 后 `event.clear()`,通过 `app.post_message(LeadMailMessage())` 转给 Update handler;`on_mount` 同时启动这条 task
5. App 处理 `on_lead_mail_message`:
   - 重新 `asyncio.create_task(wait_for_lead_mail(event))` 让后续信号也能接住
   - 若 `app.state == SessionState.IDLE`,调 `await begin_autonomous_turn` 自动开新轮
   - 否则 reminder 已在 `pending_reminders` 里,等当前 Run 下一轮迭代自然取出
6. `begin_autonomous_turn`:合成 user 消息 `"[team-update] 队员发来新消息,请按 Coordinator 流程处理..."`,`conv.add_user(...)` + 调 `begin_turn(user_block(...))`——保证 LLM 调用满足"对话末尾必须 user"约束,用户在 RichLog scrollback 也能看见是自动触发

**验证:** tmux 实跑——Lead 派 alice + bob;30 秒内队员 run_to_completion idle 后 mailbox.unread 1 秒内归零(watcher 消费);若 Lead 当时空闲,屏幕上自动出现 `● [team-update] 队员发来新消息...` 用户文本块 + Lead 紧接着的 Synthesis 回复——内容包含队员报告里的真实文件名(如 `agent.py`、`team_mailbox.py`),证明完整 content 通过 reminder 传到 Lead 视野

## T31: 续写检测 — `src/forgecode/team/tools/send_message.py`**文件:** `src/forgecode/team/tools/send_message.py`(同 T22)
**依赖:** T22, T21
**步骤:**
1. `SendMessage.execute` 写完邮箱后:
   - 取目标 TeammateInfo.backend_type
   - 若 backend_type=in-process:
     - 查 `task_mgr.get(agent_id)`,若 `status != Running`:
       - `await Team.set_member_active(name, True)`
       - `await task_mgr.send_message(ctx, name, content)` 走 ch13 续派接口
   - 若 Pane 后端:已通过 wake 唤醒,无需续派

**验证:** 单测:先 spawn → 等结束 → SendMessage → 断言 task 重新 Running

## T32: Plan 审批权限切换 — `src/forgecode/agent/team_mailbox.py`**文件:** `src/forgecode/agent/team_mailbox.py`(修改)
**依赖:** T20
**步骤:**
1. 在 incoming-messages 注入逻辑中:若有 `plan_approval_response(approve=True)` 消息:
   - 调 `agent.set_permission_mode(PermissionMode.DEFAULT)`(或 Lead 当前模式,本期固定 default)
   - reminder 加文案:「Lead 已批准计划,权限模式已切到 default,可执行计划」
2. 若 `approve=False`:reminder 加文案:「Lead 驳回了计划,反馈:<feedback>。请调整后重新提交」

**验证:** 集成测试:队员以 plan 模式起步 → 收到 plan_approval_response(true) → `agent.permission_mode` 切换

## T33: 单元测试集 — 各模块 test_*.py**依赖:** T1-T32
**步骤:**
1. 跑 `pytest`,补失败用例
2. 跑 `ruff check src/`,修警告
3. 跑 `ruff format --check src/` 看无未格式化文件
4. 可选:`mypy src/forgecode/team/` 全绿

**验证:** 全绿

## T34: tmux 实跑端到端验证**依赖:** T1-T33
**步骤:**
1. 启动 tmux:`tmux new-session -s ch15-test`
2. 在内层跑 `cd /path/to/forgecode && uv run python -m forgecode`(或 `forgecode` 装好的入口)
3. 在 TUI 输入:「创建一个名为 demo 的团队」
4. 观察:
   - Agent 调 TeamCreate
   - `~/.forgecode/teams/demo/config.json` 落地
   - 状态栏 / 输出确认成功
5. 在 TUI 输入:「派 alice 用 general-purpose,在 worktree 里 echo hello > /tmp/test_alice.txt」
6. 观察:
   - tmux split 出新 pane
   - alice pane 内 forgecode 子实例启动
   - `.forgecode/worktrees/team-demo+alice/` 创建
   - `/tmp/test_alice.txt` 文件内容为 `hello`
7. 在 TUI 输入:`/team info demo`,确认 alice 出现
8. 在 TUI 输入:「给 alice 发消息,让她再写一行 world」(Agent 调 SendMessage)
9. 观察:alice pane 被唤醒,`/tmp/test_alice.txt` 多一行 `world`
10. `/team delete demo --force`,清理

**验证:** 步骤全部成功

## T35: in-process 实跑端到端验证**依赖:** T1-T33
**步骤:**
1. `unset TMUX TERM_PROGRAM`
2. `cd /path/to/forgecode && uv run python -m forgecode`
3. Agent 调 TeamCreate("inproc") → backend 为 in-process
4. Agent 派 bob(后端 in-process)
5. bob 在同进程跑完
6. 观察 `team.config.json` 中 bob 的 `is_active=False`
7. Lead 调 SendMessage(to="bob", message="再做一件事"),bob 从 session 恢复继续

**验证:** 全部成功

## 执行顺序

```
T1 → T2 → T3 → T4
              ↘
T5 → T6        T8 ── T9(把 lock 抽出,T6/T8 改 import)
T7
T10 → T11
   → T12,T13,T14(并行)
T15
T16 → T17 → T18 → T19
                → T20 → T32
T21
T22 → T23 → T31
T24 → T25 → T26
T27
T28 → T29 → T30
T33(收尾测试)
T34, T35(实跑验收)
```

并行机会:T5/T7/T8 互不依赖;T12/T13/T14 互不依赖;T22 中 7 个工具可分批。