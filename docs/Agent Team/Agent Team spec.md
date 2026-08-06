# Agent Team Spec## 背景

ch13 SubAgent 把任务从单 Agent 委派给子 Agent,实现了消息、权限账本、文件读缓存与 token 计数的隔离;ch14 Worktree 给每个子 Agent 配上独立工作目录,文件系统层并发也安全。但这两章合起来仍是「星型」拓扑——所有子 Agent 只能与主 Agent 通信,子 Agent 之间没有横向通道;主 Agent 既要决策、又要中转,既是大脑也是邮局。对「同时重构四个模块」「三个角度查同一个 bug」这类持续性、需要互相交流的工作,星型结构的瓶颈很明显。

本章把 forgecode 从星型升级到「网状」:

- 主 Agent 创建 **Team** 后升任 **Lead**,Team 是一个长期存在的小组对象,记名称、负责人、成员花名册、持久化位置
- 每个 **队员**(Teammate)是一个独立的 Agent 实例,有自己的 Conversation、自己的 Worktree
- 三种执行后端 `tmux` / `iterm2` / `in-process` 覆盖不同环境;按优先级一次性自动检测,启动后不静默回退
- 队员之间通过**共享任务列表**与**邮箱**直接通信,不必经过 Lead 中转;协作工具仅在 Team 上下文出现
- 队员可暂停可续写,自然停下后 session 留盘,Lead 调 `SendMessage` 会从磁盘恢复后继续指派
- Lead 可选启用 **Coordinator Mode**(独立于 Team,但典型场景一起用),双锁机制下剥夺 write_file/edit_file 工具,只保留调度、读类操作与 shell(用于 git merge)
- 收敛阶段由 Lead 用 Bash 跑 `git merge` 逐个合各队员的 worktree 分支,冲突由 LLM 推理解决,搞不定就 `git merge --abort` 保留 worktree 上报用户

forgecode 现有相关基础设施:
- ch13 `task.Manager` 已支持后台任务管理 + `send_message` 续派 + `AgentNameRegistry` (`by_name` 字段已是 name → id 映射);本章扩展为多 Team 寻址
- ch13 `AgentTool.execute` 已是子 Agent 启动入口,本章新增 `team_name` 参数走 Team spawn 分支
- ch13 工具过滤 `tool.apply_agent_tool_filter` 已支持多层防线;本章新增 Team 专属白名单(协作工具)与 Coordinator Mode 白名单
- ch14 `worktree.Manager` 已支持嵌套 slug(`team/alice` → `.forgecode/worktrees/team+alice/`),本章直接复用做队员 worktree(slug 形式 `team-<team_name>/<member>`)
- ch12 session 持久化(`.forgecode/sessions/<id>/conversation.jsonl`)按对话粒度落盘;本章给每个队员单独申请一个 session,队员 stop 不删 session,SendMessage 续派时通过 session 反序列化 Conversation
- ch10 `forgecode.command` slash 命令系统,本章新增 `/team` 系列
- ch07 `permission` 已支持 `plan` 模式,本章给 `plan_mode_required` 队员的 Plan 提交-Lead 审批工作流套用同一引擎

本章**只做**到「Lead 多人协作 + Plan 审批 + Coordinator 收敛」。跨进程跨机器分布式团队、队员之间实时流式通信、复杂任务依赖约束(优先级 / deadline)、Windows 平台 iTerm2 适配均不在范围内。

## 目标- **G1**: 提供 `team.Team` 与 `team.Manager`——Team 封装小组生命周期(name、lead_agent_id、members、config_path);Manager 在单 forgecode 进程内管理多个 Team(典型场景同时只有一个活跃 Team)
- **G2**: 提供 `TeamCreate` 工具——主 Agent 调用即创建 Team、调 `detect_backend` 确定后端、写 `~/.forgecode/teams/<sanitized_name>/config.json`、把 Lead 注册成第一个成员;同名团队自动后缀 `-2` / `-3` 避免冲突
- **G3**: 扩展 `Agent` 工具——增加 `team_name` 可选参数,非空时走 Team spawn 分支:加载定义 → 创建队员 Worktree → 注入协作工具 → 按后端分流 spawn → 注册到 `AgentNameRegistry` → 写入 `team.members`
- **G4**: 提供 `TeamDelete` 工具——确认所有成员 `is_active=False` 后,删队员 worktree + 删 team 目录,Lead 退出团队;有活跃成员时拒绝删除
- **G5**: 三种执行后端 `tmux` / `iterm2` / `in-process`,统一抽象 `team.Backend` Protocol;`detect_backend` 按 `$TMUX → $TERM_PROGRAM=iTerm.app && shutil.which("it2") → shutil.which("tmux") → in-process` 优先级一次性决定,不做运行时回退
- **G6**: 队员注入 5 个协作工具 `TaskCreate` / `TaskGet` / `TaskList` / `TaskUpdate`(后者支持 `add_blocks` / `add_blocked_by` 依赖字段) / `SendMessage`;主 Agent 与普通 SubAgent 看不到这些工具
- **G7**: `SendMessage` 寻址支持 `to="<name>"`、`to="<agent_id>"`、`to="*"` 广播三种;通过 `AgentNameRegistry` 解析 name → agent_id,写邮箱;Tmux/iTerm2 后端额外通过 `send-keys` 唤醒目标 pane
- **G8**: 邮箱文件并发安全——每个收件人独占一个 lock 文件(`os.open(O_CREAT|O_EXCL)`),抢锁失败按 5-100ms 随机抖动重试,最多 10 次;持锁超过 10 秒视为 stale 直接清掉;消息文件 read-modify-write,走 `os.replace` 原子替换
- **G9**: 三种结构化消息——纯文本(必带 5-10 词 `summary`)、`shutdown_request` / `shutdown_response`(优雅退出协商)、`plan_approval_response`(Plan 审批回复,只允许 Lead 发送);全部走同一 SendMessage 入口,以 `type` 字段分流
- **G10**: 队员收到的未读消息在下一轮 Agent Loop 开头被读出,以 `<incoming-messages>` system reminder 形式注入到 LLM 输入;读后批量标记为 read
- **G11**: 队员 spawn 两种路径——指定 `subagent_type` 走定义式(从空白对话起步)、留空走 Fork 路径(继承 Lead 完整对话历史);Fork 路径受 `FORK_TEAMMATE` feature flag 控制,默认关闭
- **G12**: 队员 `run_to_completion` 结束后自动通知 Lead——团队 config 里把该成员 `is_active=False`、Lead 邮箱收到 `idle_notification`;队员的 Conversation 已通过 ch12 Writer 实时写入 session 文件
- **G13**: 队员续写——Lead 调 `SendMessage(to="alice", message="…")`,系统检测 alice 已 stop 时,从 ch12 session 反序列化 Conversation、新建一个 asyncio task 走 `run_to_completion(initial_message=new_message)`;Conv 沿用历史
- **G14**: `plan_mode_required=True` 的队员被 spawn 时强制以 plan 模式起步——计划生成后通过 SendMessage 发给 Lead,Lead 用 `plan_approval_response` 回复 approve 或 reject;approve 时队员权限模式切到 Lead 的当前模式继续执行,reject 时队员按 feedback 调整后重新提交
- **G15**: Coordinator Mode 独立于 Team——`is_coordinator_mode() = feature("COORDINATOR_MODE") and env_truthy(FORGECODE_COORDINATOR_MODE)`,两把锁全开才生效;开启后 Lead 工具集收窄到 `Agent / TeamCreate / TeamDelete / TaskCreate / TaskGet / TaskList / TaskUpdate / SendMessage / read_file / glob / grep / bash`(剥夺 `write_file` / `edit_file`),并注入 coordinator 系统提示词引导 Research / Synthesis / Implementation / Verification 四阶段
- **G16**: 收敛全部由 LLM 推理驱动——Lead 用 Bash 跑 `git merge worktree-team-<team>+<member> --no-ff -m "merge: <member>"` 逐个合,冲突由 Lead 用 read_file / edit_file / bash 自行解决;搞不定就 `git merge --abort`,保留队员 worktree,把冲突上下文上报给用户
- **G17**: 提供 TUI slash 命令 `/team list` / `/team info <name>` / `/team delete <name>` / `/team kill <member>`,辅助用户人工介入
- **G18**: 与 ch04~ch14 既有功能协同——主 Agent 平时(未 TeamCreate)看到的工具列表不变;协作工具仅在 Team 上下文出现;ch13 后台任务 / AdoptRunning / SendMessage 续派路径保留,Team 队员的续派复用同一套底层 `task.Manager`

## 功能需求### Team 数据结构与 Manager- **F1**: `team.Team` 字段——`name`(原始名)、`sanitized_name`(经 `sanitize` 处理后用于路径)、`lead_agent_id`、`members: list[TeammateInfo]`、`config_dir`(`<home_dir>/.forgecode/teams/<sanitized_name>/`)、`config_path`(`<config_dir>/config.json`)、`created_at: datetime`、`backend: BackendType`
- **F2**: `team.TeammateInfo` 字段——`name`(Lead 分配的队员名,Team 内唯一)、`agent_id`(对应 `task.BackgroundTask.id`)、`agent_type`(使用的 subagent 定义名;Fork 路径下为 `""`)、`model`(覆盖,空表 inherit)、`worktree_path`(绝对路径)、`branch`(对应 worktree 分支名)、`backend_type`(可 per-member 不同)、`pane_id`(tmux pane / iterm2 split id,in-process 为空)、`is_active: bool | None`(`None` 或 `True` 表活跃,`False` 表空闲;终止后直接从 `members` 移除)、`plan_mode_required: bool`、`session_dir`(队员独立 session 目录绝对路径)
- **F3**: `team.Manager` 字段——`_lock: asyncio.Lock`、`teams: dict[str, Team]`(按 `sanitized_name` 索引)、`home_dir`(`Path.home()`)、`wt_mgr: worktree.Manager`、`task_mgr: task.Manager`、`registry: AgentNameRegistry`
- **F4**: `team.Manager(home_dir: Path, wt_mgr, task_mgr, reg) -> Manager`——校验 `<home_dir>/.forgecode/teams/` 可写;扫描该目录还原 `teams` dict(每个子目录读一次 `config.json`,跳过解析失败的并 stderr 警告)
- **F5**: `await Manager.create(name: str, agent_type: str) -> Team`——
  1. `sanitized = sanitize(name)`(只保留 `[a-zA-Z0-9._-]`,其他替换为 `-`,首尾去 `-`,空字符串拒绝)
  2. 同名冲突时在 `sanitized` 后追加 `-2` / `-3` 直到唯一
  3. 创建 `config_dir`,落 `config.json`(原子写)
  4. 调 `detect_backend()` 写入 `team.backend`
  5. 取当前 Lead Agent ID(从调用上下文取,本期 Lead = 主 Agent,固定 `"lead"`)
  6. 把 Lead 注册成第一个成员(`TeammateInfo(name="lead", agent_id="lead", is_active=None)`)
  7. 加入 `teams` dict,返回 Team
- **F6**: `Manager.get(name: str) -> Team | None`——按 sanitized name 查询
- **F7**: `await Manager.delete(name: str, force: bool) -> None`——
  1. 取 Team;不存在抛 `TeamNotFoundError`
  2. 非 force 时若有 `member.is_active != False`(包括 None 和 True)抛 `TeamHasActiveMembersError`
  3. 逐个删队员 Worktree(调 `wt_mgr.remove(name, discard_changes=True)`,失败只警告不中断)
  4. 删队员 session 目录(`shutil.rmtree(member.session_dir, ignore_errors=True)`)
  5. 删 `config_dir`(`shutil.rmtree`)
  6. 从 `teams` dict 移除
- **F8**: `await Team.add_member(info: TeammateInfo) -> None`——校验 name 在 Team 内唯一;加入 `members`;持久化 `config.json`(原子写——先写 `.tmp` 再 `os.replace`)
- **F9**: `await Team.set_member_active(name: str, active: bool) -> None`——更新 `is_active`,持久化
- **F10**: `await Team.remove_member(name: str) -> None`——从 `members` 移除,持久化

### 后端检测与抽象- **F11**: `team.BackendType` 字符串枚举,取值 `"tmux"` / `"iterm2"` / `"in-process"`(用 `enum.StrEnum`)
- **F12**: `team.Backend` Protocol——
  ```python
  class Backend(Protocol):
      def type(self) -> BackendType: ...
      # spawn 在后端启动一个新队员;返回 (pane_id, agent_id)。
      # 对 Pane 后端,spawn 会执行 split-window / it2 split + send-keys 启动 CLI。
      # 对 in-process 后端,spawn 在事件循环里起一个 asyncio task 跑 run_to_completion。
      async def spawn(self, req: SpawnRequest) -> tuple[str, str]: ...
      # wake 用于消息到达时唤醒目标 pane。in-process 后端为 no-op。
      async def wake(self, pane_id: str, agent_id: str) -> None: ...
      # kill 终止 pane(Pane 后端)或 cancel task(in-process)。
      async def kill(self, pane_id: str, agent_id: str) -> None: ...
  ```
- **F13**: `team.SpawnRequest` 字段——`team_name`、`member_name`、`agent_id`、`worktree_path`、`session_dir`、`agent_type`、`model`、`initial_prompt`、`plan_mode_required`、`sub_agent: Any`(in-process 用,实际是 `agent.Agent`)、`conv: Any`(in-process 用,实际是 `conversation.Conversation`)、`task_mgr: Any`(in-process 用)
  - 对 Pane 后端(tmux / iterm2),`initial_prompt` **不**走命令行——在 `Backend.spawn` 调用前由 `team.spawn_teammate` 预写入 alice 的 mailbox(类型 `text`,from `lead`),子进程启动后读 mailbox 自然拿到。这样避免长 prompt 在命令行里 shell-quote 的边界问题。
- **F14**: `team.detect_backend() -> BackendType`——按以下优先级一次性决定:
  1. `os.environ.get("TMUX")` → `tmux`
  2. `os.environ.get("TERM_PROGRAM") == "iTerm.app"` && `shutil.which("it2")` → `iterm2`
  3. `shutil.which("tmux")` → `tmux`(外部 spawn 新 session)
  4. 否则 → `in-process`

### tmux 后端- **F15**: `forgecode.team.backend.tmux.TmuxBackend` 实现 `Backend` Protocol
  - `spawn`:`tmux split-window -h -P -F "#{pane_id}" -- <cmd>`(横向 split,-P 打印 pane id,-F 指定格式);`cmd` 为 `python -m forgecode --team-member --team <team_name> --member <member_name> --agent-id <agent_id> --session-dir <session_dir> --worktree <worktree_path> [--agent-type <type>] [--model <model>] [--plan-mode]`
  - `--agent-id` 是关键:Lead spawn 时已生成的 agent_id 直接传给子进程,子进程不需要读 Lead 还没写完的 `config.json` 找自己
  - 用 `asyncio.create_subprocess_exec` 跑 tmux,捕获 stdout 作为 pane_id
  - `wake`:`tmux send-keys -t <pane_id> "" Enter`(回车触发子进程 stdin reader 读到一行,立刻去 mailbox 轮询;in-process 后端无此动作)
  - `kill`:`tmux kill-pane -t <pane_id>`(忽略 pane 不存在错误)
- **F16**: 若当前在 tmux 会话外但本机有 tmux,spawn 走 `tmux new-session -d`(detached 新 session);若失败回落到错误而非 in-process(不静默回退)

### iterm2 后端- **F17**: `forgecode.team.backend.iterm2.Iterm2Backend` 实现 `Backend` Protocol
  - `spawn`:`it2 split --new-pane --command "<cmd>"`,`<cmd>` 与 F15 同构(含 `--agent-id`);通过 `it2` CLI 解析输出取 pane id
  - `wake`:`it2 send-text --pane <pane_id> ""`(空文本即唤醒)
  - `kill`:`it2 close-pane --pane <pane_id>`

### in-process 后端- **F18**: `forgecode.team.backend.inprocess.InProcessBackend` 实现 `Backend` Protocol
  - `spawn`:复用 `task.Manager.launch`——创建带 `cwd=worktree_path` 的子 Agent,在 asyncio task 里跑 `run_to_completion`;返回 `(pane_id="", agent_id=<task_id>)`,内部用 `task.BackgroundTask.id` 关联
  - `wake`:no-op(同进程,下一轮 Loop 自动读邮箱)
  - `kill`:调 `await task.Manager.stop(agent_id)`
- **F19**: in-process 后端的队员**只允许同步子 Agent**——其 `Agent` 工具看不到 `team_name` 参数(`team_name` 被拦截);后台子 Agent 也禁用(过滤 `run_in_background=True`)

### Pane 后端子进程的 team-member 模式- **F19a**: `python -m forgecode --team-member` 在 Pane 后端被 spawn 的 forgecode 子进程**不启动 TUI**(不构造 Textual App),而是跑一个自治协程(`src/forgecode/cli/team_member.py` 的 `run_team_member`):
  1. 从 CLI 解析 `--team / --member / --agent-id / --session-dir / --worktree / --agent-type / --model / --plan-mode`
  2. `os.chdir(--worktree)`,让该进程的 `Path.cwd()` 与权限沙箱根都指到 worktree
  3. 构造**单独的** `team.Manager`、provider、registry、permission engine、hook engine(完整复用 Lead wire 代码,但不构造 TUI)
  4. 构造队员 `agent.Agent`,设 `dont_ask=True`(子进程无 TUI 接 ApprovalRequest)、注入 `<team-context>` reminder、用 `set_ctx_decorator` 注入 `TeammateContext`(含 mailbox client)
  5. 启动 stdin reader asyncio task:任何来自 tmux send-keys 的回车都推到 `wake_event`(`asyncio.Event`),触发立刻去 mailbox 轮询(0~2s 内响应)
  6. 进入主循环:
     - 读 `mailbox.read_unread(agent_id)`
     - 空 → `await asyncio.wait_for(wake_event.wait(), timeout=2.0)` 兜底轮询
     - 有未读:`text` 拼成 task,`plan_approval_response(approve=True)` 触发 `set_permission_mode(default)` + 续派 prompt,`shutdown_request` 触发优雅退出
     - 调 `await agent.run_to_completion(conv, task, events)` 让队员跑到底
     - 完成后:写 `summary="<name> idle"` 到 Lead mailbox,再 `await Team.set_member_active(name, False)`
     - 检测到 mailbox 目录已被删除(Lead 调用 `/team delete`)→ 优雅退出
- **F19b**: 该自治协程的最小事件转 stdout 打印:`Text` 直接 `print`、`ToolEvent` 打 `● tool(args)` 行、`Done` 打分隔横线、错误打 stderr。pane 内 UX 是只读的"日志流",不接受用户输入(任何回车都被 stdin reader 消费做 Wake 信号)
- **F19c**: 跨进程 `config.json` 写入并发:Lead 与子进程是不同进程,各持一份内存中的 Team 对象。`Team.add_member` 与 `Team.set_member_active` 在加锁后**先从磁盘 reload `members` 字段**再修改+原子 save(`_reload_from_disk_locked`)。否则会出现"子进程内存看不到自己,set_member_active 静默 no-op"的丢更新问题

### TeamCreate 工具- **F20**: 工具名 `TeamCreate`,参数 schema:
  - `team_name`(string,必填):团队名,经 sanitize 后做 `Team.sanitized_name`
  - `description`(string,可选):团队描述,写入 `config.json` 的 `description` 字段
  - `agent_type`(string,可选):本期保留位,实际不使用
- **F21**: `TeamCreate.execute`——
  1. 解析参数
  2. 调 `await manager.create(name, agent_type)` 创建 Team
  3. 返回 JSON `{"team_name":"<sanitized>","backend":"<type>","config_path":"<path>"}`
  4. Lead 创建 Team 后保持原有工具集(非 Coordinator Mode 下不剥夺工具)

### TeamDelete 工具- **F22**: 工具名 `TeamDelete`,参数 `team_name`(必填)、`force`(可选 bool)
- **F23**: `TeamDelete.execute`——调 `await manager.delete(name, force)`,返回成功/失败消息

### Agent 工具扩展 (team_name)- **F24**: `Agent` 工具参数 schema 新增字段:
  - `team_name`(string,可选):非空时走 Team spawn 分支
- **F25**: 当 `team_name` 非空,`Agent.execute` 走 Team 分支:
  1. 校验 `team_name` 对应的 Team 存在(`manager.get`),否则抛错
  2. 校验当前调用者权限:
     - 主 Agent / Lead → 允许
     - in-process 队员调 Team spawn → 拒绝(`InProcessTeammateNoSpawnError`)
     - Pane 队员可以调(README:Pane 队员拥有完整 Agent 工具),但 `team_name` 参数被屏蔽(队员不能往 Team 加人,只 Lead 在 Coordinator Mode 或普通 Lead 调用时可以)
  3. 加载 `SubAgentDefinition`(指定 `subagent_type` 走 Catalog;留空且 `FORK_TEAMMATE` 开启走 Fork 定义;留空且 flag 关闭则用 `general-purpose`)
  4. 调 `await wt_mgr.create(f"team-{sanitized}/{member_name}", "HEAD", False)` 创建 Worktree
  5. 申请新 session 目录(复用 `session` 包接口),作为 `session_dir`
  6. 构造 in-process 子 Agent(若后端为 in-process)或仅构造 SpawnRequest(若 Pane 后端);把协作工具注入到子 Agent 的 allowed tools 集合
  7. 注入队员系统提示词附录(F39)
  8. 注入 `<team-context>` initial system reminder 到子 Agent Conv
  9. **若是 Pane 后端**,在 `backend.spawn` 之前把 `initial_prompt` 作为 `text` 消息(`from=lead, summary=initial task`)预写入 alice 的 mailbox(F13);in-process 后端不需要,`initial_prompt` 直接作为 `task.Manager.launch` 的 task 参数
  10. 调 `await team.Backend.spawn(req)` spawn,记 `pane_id`
  11. 注册到 `AgentNameRegistry`:`member_name → agent_id`
  12. 构造 `TeammateInfo` 加入 `team.members`,持久化(F19c 的 reload-before-modify 兜底)
  13. 返回 JSON `{"member_name":"<name>","agent_id":"<id>","worktree":"<path>","backend":"<type>","pane_id":"<id 或空>"}`

### 协作工具- **F26**: `TaskCreate` 工具——参数 `title`(必填)、`description`(可选)、`assignee`(可选,队员名)、`blocked_by`(可选 list[str],任务 id);返回新建 `task_id`(`task_<6位 hex>`);写入 Team 的 `tasks.json`(原子)
- **F27**: `TaskGet` 工具——参数 `task_id`,返回任务详情
- **F28**: `TaskList` 工具——参数可选 `status` 过滤(`pending`/`in_progress`/`completed`/`blocked`);返回任务数组,带依赖关系标注(`blocked_by`、`blocks`、是否 `is_ready`(无未完成 blocker))
- **F29**: `TaskUpdate` 工具——参数 `task_id`(必填)、`title`(可选)、`description`(可选)、`status`(可选)、`assignee`(可选)、`add_blocks`(可选 list[str])、`add_blocked_by`(可选 list[str])、`remove_blocks` / `remove_blocked_by`(可选 list[str]);更新后持久化
- **F30**: `tasks.json` 结构:
  ```json
  {
    "tasks": [
      {
        "id": "task_a1b2c3",
        "title": "...",
        "description": "...",
        "status": "pending",
        "assignee": "alice",
        "blocked_by": ["task_xxx"],
        "blocks": ["task_yyy"],
        "created_at": 1234567890,
        "updated_at": 1234567890
      }
    ]
  }
  ```
  写入走 `<team_config_dir>/tasks.json`,read-modify-write,文件锁 `tasks.lock`(同邮箱 lock 机制)

### SendMessage 工具与邮箱- **F31**: `SendMessage` 工具——参数:
  - `to`(string,必填):队员名 / agent_id / `"*"` 广播
  - `summary`(string,纯文本消息时必填,5-10 词)
  - `message`(string,可选,纯文本消息体)
  - `type`(string,可选,默认 `"text"`):取值 `"text"` / `"shutdown_request"` / `"shutdown_response"` / `"plan_approval_response"`
  - `payload`(object,可选):结构化消息的载荷(如 `shutdown_response` 的 `{approve, reason}`)
- **F32**: 邮箱文件路径——`<team_config_dir>/mailbox/<agent_id>.json`,结构:
  ```json
  {
    "messages": [
      {
        "from": "lead",
        "to": "alice",
        "type": "text",
        "summary": "interface change",
        "content": "...",
        "payload": null,
        "timestamp": 1234567890,
        "read": false
      }
    ]
  }
  ```
- **F33**: `team.mailbox.Box` 提供 `await write(agent_id, msg)` / `await read(agent_id) -> list[Message]` / `await mark_read(agent_id, indices)` 接口
  - `write`:抢 `<team_config_dir>/mailbox/<agent_id>.lock`(`os.open(O_CREAT|O_EXCL|O_WRONLY)`),失败 5-100ms 随机抖动重试 10 次;持锁超 10 秒视为 stale(`Path.stat().st_mtime` 判定)直接删 lock 重试;成功后 read-modify-write,`os.replace` 原子替换
  - 广播 `to="*"` 时,write 对 Team 内除发件人外所有成员的 mailbox 各 write 一次
- **F34**: `SendMessage.execute`——
  1. 校验调用者在 Team 内
  2. 解析 `to`:若 `"*"` 走广播;否则通过 `registry.resolve(to)` 取 agent_id(name 优先,失败按 agent_id 直查);解析不到抛错
  3. `plan_approval_response` 仅 Lead 可发,否则抛错
  4. `shutdown_response` 只能发给 Lead,否则抛错
  5. 调 `await mailbox.write`
  6. 取目标的 `backend_type` 与 `pane_id`,若是 Pane 后端调 `await backend.wake(pane_id, agent_id)`
  7. 若目标 agent_id 已 stop(in-process 后端):触发续写(F45)
  8. 返回 `{"delivered_to":["<agent_id>"],"timestamp":<ts>}`

### Agent 名称注册表- **F35**: `team.AgentNameRegistry` 字段——`_lock: threading.Lock`、`by_name: dict[str, str]`(name → agent_id)、`by_id: dict[str, str]`(agent_id → name,反查)
- **F36**: 接口 `register(name, agent_id)`、`unregister(name)`、`resolve(name_or_id) -> str | None`、`name_of(agent_id) -> str | None`
- **F37**: 注册时机——`Agent` 工具 spawn 队员时(F25 step 10);`AgentTool` 的 `name` 参数非空时(ch13 已有,本章统一这套 registry,替换 `task.Manager.by_name` 的内部 dict)
- **F38**: 命名冲突——后注册的覆盖前注册的(README 称「弱引用,后启动覆盖前面的弱引用」)

### 队员系统提示词附录- **F39**: 在子 Agent 的 system_prompt 后追加(若 spawn 进 Team)以下文本(无变量):
  ```
  IMPORTANT: You are running as an agent in a team.
  Just writing a response in text is not visible to others
  on your team - you MUST use the SendMessage tool.
  The user interacts primarily with the team lead.
  Your work is coordinated through the task system
  and teammate messaging.
  ```
- **F39a**: 所有 Team 队员(三种后端共有)一律以 `dont_ask=True` 启动,**覆盖角色定义里的 `permission_mode`**。理由:队员没有可交互的 TUI 接 `ApprovalRequest`(in-process 走 task.Manager 聚合事件不响应、Pane 子进程更没有 TUI),Ask 工具会无人应答地永远阻塞。队员的安全边界由 allowed 工具集 + Worktree 隔离 + Plan 模式控制,不靠逐次 ask 弹窗(子进程没人在看)。
- **F40**: 在 spawn 时把 `<team-context>` 注入子 Conv 的首条 system reminder:
  ```
  <team-context>
  team: <team_name>
  你的成员名: <member_name>
  你的 agent_id: <agent_id>
  worktree 目录: <worktree_path>
  当前团队成员: <name1>(<role1>), <name2>(<role2>) ...
  </team-context>
  ```

### 邮箱读取与消息注入- **F41**: 子 Agent 的 Loop 在每轮请求 LLM **之前**先调 `await mailbox.read(agent_id)`;若有未读消息,构造 `<incoming-messages>` system reminder 追加到本轮请求的 system_reminders,然后调 `mark_read`
- **F41a**: Lead 侧不通过 ctx hook 自动读 mailbox(Lead 没有 `TeammateContext`),而是由 TUI 在 `on_mount` 启动后台 asyncio task `consume_lead_mail`(实现于 `src/forgecode/tui/tasks.py`):
  - 每秒调 `await manager.poll_lead_mailboxes()`,遍历所有 Team 的 `<config_dir>/mailbox/lead.json` 读未读消息,标 read,返回 `list[LeadMessage]`
  - 把这批消息渲染成 `<team-update>` reminder(与 `<incoming-messages>` 不同,Lead 视角语义更清晰;消息内容截断上限 8000 字符,允许队员的完整报告完整透传),调 `runtime.append_reminders(...)` 推到 `pending_reminders`
  - **同时**往 `lead_mail_event: asyncio.Event` `set()` 一个信号
  - Lead 下一轮 Run 迭代头部 `build_reminder` 自动取出。**Lead 即便正在长 Run 中也能中途惊醒**——下一个 LLM 调用前就会看到队员更新
  - 这是 Pane 后端队员通知 Lead 的关键路径:in-process 队员还有 `task.Manager.subscribe_done` → TUI `<task-notification>` 的额外路径,但 Pane 队员只能靠 mailbox + 本机制
- **F41b**: Lead idle 时的自动续推。TUI 通过 `await wait_for_lead_mail(event)` 协程阻塞在 `lead_mail_event` 上,收到信号后触发 message handler:
  - 若 `app.state == SessionState.IDLE`,调 `await begin_autonomous_turn`:合成一条 user 消息 `"[team-update] 队员发来新消息,请按 Coordinator 流程处理..."` 加入对话历史(用户在 RichLog scrollback 也看得见,清楚是系统通知触发而非自己输入),然后走 `begin_turn` 启 Run
  - 若 `app.state` 非 idle(STREAMING/APPROVING):reminder 已经在 pending_reminders 里,Lead 当前 Run 的下一轮迭代头部自然取出,不需要主动 wake
  - 末尾 `event.clear()` 让后续信号也能接住
  - 这避免了"队员都 idle 了,Lead 在 idle 等用户输入,reminder 静默积累没人取"的卡死场景——这正是 ch15 协作 UX 的关键
- **F42**: `<incoming-messages>` 格式:
  ```
  <incoming-messages>
  收到 N 条新消息:
  [1] 来自 <from>(type=<type>,ts=<时间>): <summary>
      <content 前 200 字>
  [2] ...
  </incoming-messages>
  ```
- **F43**: 收到 `shutdown_request` 时,队员可在下一轮自主选择回复 `shutdown_response(approve=True)` 然后停止,或 `approve=False` 拒绝并附 reason(LLM 决策,不强制)
- **F44**: 收到 `plan_approval_response(approve=True)` 时,队员的权限模式自动切换到 Lead 当前模式(从 Team config 取);`approve=False` 时队员根据 `feedback` 调整重新发 Plan

### 队员空闲与续写- **F45**: 队员 `run_to_completion` 自然结束时(`task.Manager._run_task` 完成路径):
  1. 调 `await Team.set_member_active(member_name, False)`
  2. 给 Lead 邮箱写一条 `idle_notification`(`type="text", summary="<member> idle", content="agent <id> finished work, available for new tasks"`)
- **F46**: SendMessage 检测到目标 agent_id 已 stop 且为 in-process 队员(`task.BackgroundTask.status` 不是 `Running`):
  1. 从 `TeammateInfo.session_dir` 反序列化 Conversation(`session.load`)
  2. 调 `await task.Manager.send_message(parent_ctx, name, message)` 复用 ch13 已有续派接口
  3. `task.Manager.send_message` 重置 `status=Running`,起新 asyncio task 跑 `run_to_completion(new_message)`
  4. 续派前调 `await Team.set_member_active(member_name, True)`
- **F47**: Pane 后端队员的续写——SendMessage 写邮箱后,目标 pane 内的 forgecode 实例下一轮 Loop 自然读到消息;若 pane 已死(`tmux list-panes` 查不到 `pane_id`),报错让 Lead 决定是否重新 spawn

### Plan 审批工作流- **F48**: `Agent` 工具 spawn 队员时,若 `plan_mode_required=True`(来自 `SubAgentDefinition` 的新字段或 spawn 参数),把子 Agent 的初始 `permission.Mode` 设为 `plan`
- **F49**: 队员在 plan 模式下生成 Plan 后(通过常规 LLM 推理),用 `SendMessage(to="lead", type="text", summary="plan ready", content="<plan text>")` 发给 Lead——本期不强制结构化 Plan 类型(Lead 自行识别)
- **F50**: Lead 用 `SendMessage(to="<member>", type="plan_approval_response", payload={"approve":True|False,"feedback":"..."})` 回复
- **F51**: 队员收到 `plan_approval_response`:
  - `approve=True`:从 Team config 读 Lead 当前 `permission_mode`(本期固定 `default`),切到该模式继续执行 plan
  - `approve=False`:把 `feedback` 当作新的用户消息加入对话,重新进入 plan 模式

### Coordinator Mode- **F52**: 提供 `coordinator.is_enabled() -> bool` 函数:
  ```python
  def is_enabled(cfg: Config) -> bool:
      if not feature_has(cfg, "COORDINATOR_MODE"):
          return False
      return env_truthy(os.environ.get("FORGECODE_COORDINATOR_MODE", ""))
  ```
  `feature_has` 通过 `forgecode.config` 读 `features.coordinator_mode` 字段;`env_truthy` 接受 `"1"` / `"true"` / `"yes"`(大小写不敏感)
- **F53**: Coordinator Mode 允许工具白名单常量:
  ```python
  COORDINATOR_ALLOWED_TOOLS: list[str] = [
      "Agent", "TeamCreate", "TeamDelete",
      "TaskCreate", "TaskGet", "TaskList", "TaskUpdate",
      "SendMessage",
      "read_file", "glob", "grep", "bash",
  ]
  ```
- **F54**: Lead 启动时(`tui` 主流程构造 Agent 后),若 `coordinator.is_enabled()`:
  1. 把 Lead 的 allowed tools 设为 `COORDINATOR_ALLOWED_TOOLS`(调 `agent.set_allowed_tools` 已有接口)
  2. 在 system_prompt 后追加 coordinator 提示词(F55)
  3. TUI 状态栏显示 `[COORDINATOR]` 模式标签
- **F55**: Coordinator 系统提示词追加在 system_prompt 末尾,核心是"四阶段 + 派完不许自己干"纪律。最终文案见 `src/forgecode/coordinator/coordinator.py:SYSTEM_PROMPT_SUFFIX`,关键约束:
  - **派完队员就停手等汇报**:派出 Agent / SendMessage 后**禁止**立刻调 read_file / glob / grep / bash 自己探索;**禁止**用 sleep / TaskList 轮询凑时间。`task.Manager` 完成时自然推送 `<task-notification>` reminder,Lead 下一轮被唤醒后再继续
  - 唯一该做的事:发一行总结"已派 N 名队员探索 X,等结果",让本轮结束
  - 允许自己用 read_file/glob/grep 的场景仅限:Research 第一次目标定位;Synthesis 阶段读**队员产出的报告文件**;Verification 阶段 git diff / git status 等收敛操作

  这段纪律是为了对抗"LLM 派完队员后等不及自己 glob 代码库重复劳动"的常见行为——纯 prompt 引导,不强制(LLM 偶尔仍会越线,弱模型尤甚)。

### 收敛阶段- **F56**: 收敛由 LLM 推理驱动,**不提供专门的 merge 工具**——Lead(无论是否 Coordinator Mode)在所有任务 `completed` 后,自主用 Bash 跑:
  ```bash
  git merge worktree-team-<sanitized_team>+<member> --no-ff -m "merge: <member>"
  ```
- **F57**: 冲突解决也由 Lead 推理——Lead 用 `read_file` 看冲突文件、`edit_file`(非 Coordinator Mode)或 `bash`(Coordinator Mode)写入解决方案、`bash` 跑 `git add` + `git commit`
- **F58**: 回滚——Lead 判断搞不定时,自主调 `bash` 跑 `git merge --abort`,然后给用户报告冲突文件 + 队员 worktree 路径;**不删队员 worktree**### TUI Slash 命令- **F59**: `/team list`——遍历 `manager.teams`,每行 `<name>  <backend>  <member_count> 成员  [<active>/<total>] 活跃`
- **F60**: `/team info <name>`——展示 Team 详情:配置路径、各成员的 name/agent_id/backend/worktree_path/is_active/任务计数
- **F61**: `/team delete <name> [--force]`——调 `await manager.delete(name, force)`
- **F62**: `/team kill <member>`——查到 member 所属 Team,调对应 backend.kill,然后 `remove_member`

### 持久化与恢复- **F63**: `~/.forgecode/teams/<sanitized_name>/config.json` 结构:
  ```json
  {
    "name": "...",
    "sanitized_name": "...",
    "lead_agent_id": "lead",
    "backend": "tmux",
    "description": "",
    "created_at": 1234567890,
    "members": [
      {
        "name": "alice",
        "agent_id": "agent-a1b2c3d",
        "agent_type": "worker",
        "model": "",
        "worktree_path": "/abs/path/.forgecode/worktrees/team-foo+alice",
        "branch": "worktree-team-foo+alice",
        "backend_type": "tmux",
        "pane_id": "%5",
        "is_active": null,
        "plan_mode_required": false,
        "session_dir": "/abs/path/.forgecode/sessions/<id>"
      }
    ]
  }
  ```
  所有写操作原子(先写 `.tmp` 再 `os.replace`),受 `Team._lock` 保护。**跨进程**(Pane 后端)下,Lead 与子进程是不同进程的不同 Team 内存对象——`add_member` 与 `set_member_active` 在加锁后**先 `_reload_from_disk_locked` 重读 disk members**再改写+ atomic save(F19c)
- **F64**: forgecode 启动时(`team.Manager` 构造)扫描所有 Team 目录:
  - 解析 `config.json`,失败的目录跳过并 stderr 警告
  - **不**自动恢复 in-process 队员(进程重启后 in-process 队员状态丢失,is_active 视为 False)
  - Pane 队员根据 `pane_id` 探测后端是否仍在(`tmux has-session` / `it2 list-panes`),不在的 is_active 标 False
- **F65**: 队员 session 沿用 ch12 session 持久化机制,路径 `<project_root>/.forgecode/sessions/<id>/conversation.jsonl`;Team 删除时一并删除
- **F66**: `Manager.delete(name, force=True)` 步骤(顺序重要):
  1. 持锁,校验 `force` 或全员 is_active=False
  2. 对每个非 lead 成员:用 `backend.new` 解析其 `backend_type` 拿 `Backend` 实例,调 `await backend.kill(pane_id, agent_id)` 杀掉 pane(tmux/iterm2)或 cancel asyncio task(in-process);Pane 子进程检测到 mailbox 目录消失会自行优雅退出兜底
  3. 调 `await _cleanup_member_resources` 删 session 目录与 worktree
  4. `shutil.rmtree(team.config_dir)` 删整个 Team 目录
  5. 从 Manager 的 in-memory dict 移除

## 非功能需求- **N1**: 主 Agent 平时(未 TeamCreate)看到的工具列表保持稳定——`TeamCreate` / `TeamDelete` 总是可见;`Agent` 工具的 `team_name` 参数对模型可见但仅在调用时校验
- **N2**: 协作工具(TaskCreate 等)仅在队员上下文出现,主 Agent 与普通 SubAgent 看不到——通过 `apply_agent_tool_filter` 在 spawn 时收窄
- **N3**: 邮箱写入对所有后端共用一套并发安全机制(文件锁);in-process 多 asyncio task 写同一 mailbox 也由文件锁串行
- **N4**: 所有 Team 状态变更受 `Team._lock`(`asyncio.Lock`)保护;Team 之间互不相关,各自一把锁;`Manager._lock` 仅保护 `teams` dict
- **N5**: 后端 spawn / kill 调用不持 `Team._lock`(避免长锁);只在更新 `members` 时短暂持锁
- **N6**: 与 ch04~ch14 既有测试零破坏——`pytest` 全绿
- **N7**: 中文友好——错误消息、TUI 输出、coordinator 提示词全部中文(对齐 forgecode 其他模块风格);代码注释中文
- **N8**: Coordinator Mode 一旦启用,Lead 不可在运行时解锁(避免 LLM 被注入后自行解锁);取消的唯一方式是退出 forgecode 重启
- **N9**: 权限沙箱(`src/forgecode/permission/sandbox.py`)允许写入项目根**之外**的 `/tmp` 与 macOS 真实路径 `/private/tmp` 作为系统临时目录白名单。理由:工具脚本和队员经常需要 `/tmp` 做中转文件,严格限定在项目根内会导致大量正常用法被沙箱误杀。这一开放对 file-class 工具(read_file / write_file / edit_file)生效;bash 走 exec-class 权限,本来就不受沙箱约束

## 不做的事

- 跨 forgecode 进程的 Team 共享(同一仓库同一时刻只支持一个 forgecode 实例操作活跃 Team)
- 跨机器分布式 Team
- 队员之间实时流式通信(走 mailbox 文件 + 轮询/Wake,不走 socket)
- 复杂任务依赖约束(优先级、deadline、SLA)
- 任务自动分配(Lead 与队员都靠 LLM 推理领任务,系统不做调度)
- 队员的细粒度资源限额(token 上限、超时硬限制)
- Plan 审批的结构化 Plan 类型(本期 Plan 文本就是 SendMessage content,Lead 自行识别)
- Windows 平台特殊适配(iTerm2 后端仅 macOS;tmux 在 WSL 可用但不保证;本期以 macOS / Linux 为主)
- Coordinator Mode 的运行时解锁与重新进入
- 跨 Team 寻址(SendMessage 只能在同一 Team 内寻址)
- 插件来源的 Team 后端

## 验收标准- **AC1**: `team.Manager(...)` 在 `~/.forgecode/teams/` 不存在时自动创建;已有时正确扫描子目录还原 `teams` dict
- **AC2**: `await manager.create("refactor auth", "")` 把 `"refactor auth"` sanitize 为 `"refactor-auth"`,在 `~/.forgecode/teams/refactor-auth/config.json` 落地,`backend` 字段反映 `detect_backend` 结果
- **AC3**: 同名 Team 二次 create 自动后缀 `-2`,目录与 sanitized_name 都生效
- **AC4**: `await manager.delete(name, False)` 在有 `is_active!=False` 成员时抛 `TeamHasActiveMembersError`,目录仍在
- **AC5**: `await manager.delete(name, True)` 删 Worktree、删 session 目录、删 config_dir
- **AC6**: `detect_backend()` 在 `$TMUX` 设置时返回 `tmux`;未设但 `$TERM_PROGRAM==iTerm.app` 且 `it2` 可执行返回 `iterm2`;都无但 `tmux` 二进制在 PATH 返回 `tmux`;否则 `in-process`
- **AC7**: `Agent` 工具带 `team_name="<existing>"` 时,在 `.forgecode/worktrees/team-<sanitized>+<member>/` 落地 Worktree、调对应 backend.spawn 并在 `team.members` 里出现该成员;不带 `team_name` 时维持 ch13 原行为
- **AC8**: in-process 后端队员的 `Agent` 工具调用 `team_name` 参数被拦截,抛 `InProcessTeammateNoSpawnError`
- **AC9**: 协作工具 `TaskCreate` / `TaskGet` / `TaskList` / `TaskUpdate` / `SendMessage` 在主 Agent 工具列表里**不**可见;在 Team 队员的工具列表里**可见**
- **AC10**: `TaskCreate` 落 `<team_config_dir>/tasks.json`,`TaskUpdate(task_id, add_blocked_by=[id])` 正确更新双向 `blocked_by` / `blocks` 关系
- **AC11**: `TaskList(status="pending")` 返回的任务带 `is_ready` 字段,反映其 `blocked_by` 是否全部 `completed`
- **AC12**: `SendMessage(to="alice", summary="hi", message="hello")` 在 `<team_config_dir>/mailbox/<alice_agent_id>.json` 追加一条 unread 消息
- **AC13**: `SendMessage(to="*", ...)` 广播给 Team 内除发件人外所有成员;每人邮箱各得一条
- **AC14**: 并发 10 个 asyncio task 同时向同一 mailbox `write`,最终 10 条消息全部落盘且无丢失/无截断(集成测试)
- **AC15**: mailbox lock 文件 `Path.stat().st_mtime` 超过 10 秒时,新的 write 会清掉旧 lock 并继续(集成测试)
- **AC16**: 队员 LLM 调用前,未读消息以 `<incoming-messages>` reminder 注入 system_reminders;调用后标记 read(单测断言)
- **AC17**: 队员 `run_to_completion` 自然结束后,`team.config.json` 里该成员 `is_active=False`,Lead mailbox 收到 `summary="<member> idle"` 消息
- **AC18**: `SendMessage(to="alice", message="new task")` 当 alice 已 stop 时,从其 session_dir 恢复 Conv 并续派(in-process 后端,task.Manager 状态从 Cancelled/Completed 回到 Running)
- **AC19**: `Agent(team_name="t", subagent_type="planner", plan_mode_required=True, ...)` spawn 后,该队员初始权限模式为 `plan`
- **AC20**: Lead 发 `SendMessage(to="planner", type="plan_approval_response", payload={"approve":True})` 后,planner 队员下一轮权限模式切回 `default`
- **AC21**: `feature_has(cfg, "COORDINATOR_MODE")=True` 且 `FORGECODE_COORDINATOR_MODE=1` 时,Lead 的 allowed tools 收窄为 `COORDINATOR_ALLOWED_TOOLS`,`write_file` / `edit_file` 不在其中;TUI 状态栏显示 `[COORDINATOR]`
- **AC22**: Coordinator Mode 关闭时,Lead 工具列表与 ch13 一致(`write_file` / `edit_file` 可见)
- **AC23**: tmux 后端 spawn 后,`tmux list-panes` 看到新 pane,pane 内 forgecode 实例启动并连接到该 Team
- **AC24**: tmux 后端 `wake(pane_id, agent_id)` 通过 `tmux send-keys` 触发目标 pane 输入(集成测试可观察 pane 内容)
- **AC25**: in-process 后端队员与主 Agent 在同一进程内运行,共享 `task.Manager`,但有独立 `cwd=worktree_path`
- **AC26**: `/team list` slash 命令输出含所有 Team 摘要;`/team info <name>` 输出成员详情;`/team delete <name>` 调 `manager.delete`
- **AC27**: 项目能正常启动 `python -m forgecode`;`ruff check src/` 通过;`pytest` 全部通过
- **AC28**: tmux 实跑(端到端):
  - 步骤 1:在 tmux 会话内启动 `forgecode`
  - 步骤 2:输入 prompt 让主 Agent 调 `TeamCreate(team_name="demo")`,看到状态栏出现 team 标识,`~/.forgecode/teams/demo/config.json` 落地
  - 步骤 3:Agent 调 `Agent(team_name="demo", subagent_type="general-purpose", name="alice", prompt="在 worktree 里 echo hello > /tmp/test_alice.txt")`
  - 步骤 4:观察 tmux 新增 pane,pane 内出现 forgecode 子实例;`.forgecode/worktrees/team-demo+alice/` 目录创建;`/tmp/test_alice.txt` 文件创建,内容 `hello`
  - 步骤 5:`/team info demo` 显示 alice 成员
  - 步骤 6:Lead 调 `SendMessage(to="alice", summary="ping", message="再写一行 world 到 /tmp/test_alice.txt")`,观察 alice pane 被唤醒(send-keys 触发)、`/tmp/test_alice.txt` 多一行 `world`
  - 步骤 7:`/team delete demo --force`,worktree 和 team 目录清空
- **AC29**: in-process 后端实跑(端到端,不依赖 tmux):
  - 步骤 1:`unset TMUX TERM_PROGRAM`,启动 `forgecode`(自动 fallback in-process)
  - 步骤 2:主 Agent 调 `TeamCreate("inproc")`,创建后端为 `in-process`
  - 步骤 3:`Agent(team_name="inproc", name="bob", prompt="...")` 在同进程 asyncio task 启动 bob
  - 步骤 4:bob 完成后 `team.config.json` 标记 `is_active=False`、Lead mailbox 收到 idle 消息
  - 步骤 5:Lead 调 `SendMessage(to="bob", message="再做一件事")`,bob 从 session_dir 恢复对话上下文继续
- **AC30**: Coordinator Mode 实跑——`FORGECODE_COORDINATOR_MODE=1` 启动 forgecode,主 Agent 的 `write_file` 工具调用被拒绝(is_error=True);`bash git merge` 调用允许