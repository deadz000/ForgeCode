# Agent Team Checklist

> 每一项通过运行代码或观察行为来验证,聚焦系统行为而非实现细节。

## 实现完整性

- [ ] `team.Manager` 可被实例化:`team.Manager(home, root, wt_mgr, task_mgr, name_reg)` 返回非 None(验证:`python -c "from forgecode.team import Manager"`、跑单测)
- [ ] `await team.Manager.create("demo", "")` 在 `~/.forgecode/teams/demo/config.json` 落地(验证:运行单测后检查文件存在)
- [ ] `await team.Manager.create("foo bar/baz", "")` sanitize 后路径为 `~/.forgecode/teams/foo-bar-baz/`(验证:单测)
- [ ] 同名 Team 第二次 create 自动后缀 `-2`(验证:单测)
- [ ] `team.BackendType` 三个值齐全:`TMUX` / `ITERM2` / `IN_PROCESS`(验证:`ruff check` 通过 + 单测枚举)
- [ ] `backend.detect()` 在 `$TMUX` 设置时返回 `TMUX`;两环境变量都清空时返回 `IN_PROCESS`(验证:`monkeypatch.setenv` 单测)
- [ ] `mailbox.Box.write` + `mailbox.Box.read` 一进一出消息字段一致(验证:单测)
- [ ] `mailbox` 文件锁在 stale 10 秒后能被新 writer 抢占(验证:单测制造 11 秒前的锁,断言能拿到)
- [ ] `registry.AgentNameRegistry.register("alice", "agent-123")` 后 `resolve("alice")` 返回 `"agent-123"`,`name_of("agent-123")` 返回 `"alice"`(验证:单测)
- [ ] `tasks.Store.create` 返回的 task id 形如 `task_<6 位 hex>`(验证:单测)
- [ ] `await tasks.Store.update(id_, Patch(add_blocked_by=[other]))` 同时给 other 任务的 `blocks` 加上 id(验证:单测断言双向)
- [ ] `await tasks.Store.list_(Filter(status=PENDING))` 返回结果带 `is_ready` 字段,反映 blocked_by 是否全 completed(验证:单测)
- [ ] `coordinator.is_enabled` 在 feature flag 关 + 环境变量开时返回 False(验证:单测 4 种组合)
- [ ] `coordinator.allowed_tools()` 含 `bash` 不含 `write_file` / `edit_file`(验证:单测)
- [ ] `tool.apply_agent_tool_filter(FilterParams(teammate=True, ...))` 返回值含 `TaskCreate` / `SendMessage` 等 5 个协作工具(验证:单测)
- [ ] `tool.apply_agent_tool_filter(FilterParams(teammate=False, ...))` 不含这 5 个工具(验证:单测)
- [ ] 7 个新工具注册到 registry 后,`registry.definitions()` 输出含 `TeamCreate` / `TeamDelete` / `TaskCreate` / `TaskGet` / `TaskList` / `TaskUpdate` / `SendMessage`(验证:单测或启动后 `/status`)
- [ ] `Team.add_member` 与 `Team.set_member_active` 调用前先 `reload_from_disk_locked` 重读 disk(验证:跨进程并发写 disk 时不丢更新——单测制造"Lead 在 alice 子进程读完 config 之后才 add_member"的时序,alice 走 `set_member_active(False)` 后回读 disk 应看到 `is_active=False`)

## 集成

- [ ] `Agent` 工具不带 `team_name` 时走 ch13 原路径,行为不变(验证:`pytest tests/test_agent_tool.py` 全过)
- [ ] `Agent` 工具带 `team_name="demo"` 时调 `team_hook.spawn_teammate`(验证:单测 mock team_hook,断言被调用)
- [ ] `spawn_teammate` 创建 worktree 路径为 `.forgecode/worktrees/team-demo+alice`(验证:单测/集成测试)
- [ ] `spawn_teammate` 后 `team.members` 含 alice,持久化到 `config.json`(验证:单测)
- [ ] in-process 后端的队员 ctx 含 TeammateContext,其 backend_type=in-process;该队员调用 `Agent(team_name=...)` 被拒绝并抛 `InProcessTeammateNoSpawnError`(验证:集成测试)
- [ ] 队员 `Agent.run` 头部读取 mailbox 未读消息,以 `<incoming-messages>` reminder 注入到 LLM 输入(验证:单测,fake mailbox 写消息,捕获 Agent 构造的 prompt)
- [ ] 队员收到 `plan_approval_response(approve=True)` 后 `Agent.permission_mode` 切换到 default(验证:单测 + tmux 实跑——见场景 4)
- [ ] 队员 `run_to_completion` 结束触发 `on_task_done` 回调,Team config 中该成员 `is_active=False`(验证:单测注册回调 + launch noop task)
- [ ] 队员 idle 后 Lead mailbox 收到 `summary="<name> idle"` 消息(验证:单测/集成)
- [ ] `SendMessage(to="alice", ...)` 在 alice 已 stop 且为 in-process 后端时,通过 `task_mgr.send_message` 续派(验证:集成测试,断言 task status 回到 Running);Pane 后端时通过 `backend.wake` 让子进程读 mailbox 自然续派
- [ ] 所有 Team 队员一律 `dont_ask=True`(覆盖角色 frontmatter 的 `permission_mode`),子进程没人能应答 ApprovalRequest 不会卡死(验证:用 `permission_mode: default` 的角色派队员让她调 bash,实跑断言任务正常完成,而不是卡在 Ask)
- [ ] Pane 后端 spawn 时 `initial_prompt` 通过预写入 mailbox(type=text, from=lead)送达,子进程不需要走 CLI 参数(验证:tmux 实跑,在 spawn 完检查 alice mailbox 已有一条 from=lead 的初始任务)
- [ ] Pane 后端子进程命令行含 `--agent-id <id>` 参数(验证:看 `build_member_cmd` 单测;tmux 实跑后 `ps auxww | grep team-member` 看实际命令)
- [ ] Pane 后端的 `python -m forgecode --team-member` 子进程**不启动 TUI**(不构造 Textual App),跑 `run_team_member` 自治协程——读 mailbox → run_to_completion → 通知 Lead idle → stdin Wake 等下一轮(验证:tmux 实跑看 alice pane 显示纯文本日志流而非 Textual TUI 框)
- [ ] Lead mailbox watcher 每秒轮询所有 Team 的 lead.json,把未读消息转 `<team-update>` reminder 推 `pending_reminders` + 给 `lead_mail_event` `set()`(验证:tmux 实跑后看 alice 发完 idle 通知 1 秒内 mailbox 的 unread 归零、read 累加)
- [ ] Lead 在 `SessionState.IDLE` 时收到 `LeadMailMessage`,TUI 调 `begin_autonomous_turn` 合成 user 消息自动开新轮(验证:tmux 实跑——派完队员等他完成,Lead 不需要用户输入就自动出现 `[team-update]...` 行 + Synthesis 回复)
- [ ] `/team list` 输出含 `~/.forgecode/teams/` 下所有 Team(验证:TUI 实跑)
- [ ] `/team delete demo --force` 调 `backend.kill` 杀 pane(tmux/iterm2)+ 清 worktree + 清 team 目录(验证:TUI 实跑后 `tmux list-panes` 只剩 Lead,worktree 与 team 目录都消失)
- [ ] 沙箱开放 `/tmp` 与 `/private/tmp`(macOS 真实路径)作为白名单——write_file/edit_file 可写 `/tmp/foo.txt`,但 `/etc/passwd` 仍拒(验证:单测 `test_sandbox_contains` 含两组用例)

## 编译与测试

- [ ] `python -m forgecode --help` 能正常启动且打印帮助(验证:命令退出码 0)
- [ ] `ruff check src/` 无警告(验证:命令退出码 0)
- [ ] `ruff format --check src/` 无未格式化文件(验证:命令退出码 0)
- [ ] `pytest` 全部通过(验证:命令退出码 0)
- [ ] 可选:`mypy src/forgecode/team/` 全绿

## 端到端场景(tmux 实跑)

> 这是本章的核心验收场景,必须在真实 tmux 会话内手动跑一遍。

**场景 1:tmux 后端,Team 全生命周期**

环境准备:
- macOS / Linux
- tmux 已安装
- 当前不在 forgecode 进程内,准备开新 tmux 会话

步骤:
- [ ] `tmux new-session -s ch15-test` 进入新 tmux 会话
- [ ] `cd /path/to/forgecode && uv sync`(预装依赖,加快冷启动)
- [ ] `uv run python -m forgecode`(或装好的 `forgecode` 入口)启动 TUI;启动消息显示一切正常,无 ch15 相关 error
- [ ] 在 TUI 输入:「创建一个名为 demo 的团队」
  - 预期:Agent 调 `TeamCreate(team_name="demo")`;返回 `{"team_name":"demo","backend":"tmux","config_path":"..."}`
  - 验证:`ls ~/.forgecode/teams/demo/config.json` 存在;`cat config.json` 中 `backend` 字段为 `tmux`
- [ ] 在 TUI 输入:「派 alice 用 general-purpose 角色,在 worktree 里跑 `echo hello > /tmp/test_alice.txt && pwd > /tmp/test_alice_pwd.txt`」
  - 预期:Agent 调 `Agent(team_name="demo", subagent_type="general-purpose", name="alice", prompt="...")`
  - 验证 a:tmux 自动 split 出右侧 pane(`tmux list-panes -F "#{pane_id} #{pane_current_command}"` 看到新 pane)
  - 验证 b:新 pane 内**显示自治循环日志流**(`[team-member] alice · team=demo · agent=... · cwd=...` 起始行 + Agent 工具调用打印,**不是** Textual TUI 框)
  - 验证 c:`ls /path/to/forgecode/.forgecode/worktrees/team-demo+alice/` 目录存在
  - 验证 d:等待 30 秒,`cat /tmp/test_alice.txt` 内容为 `hello`
  - 验证 e:`cat /tmp/test_alice_pwd.txt` 内容为 worktree 路径(`.../team-demo+alice`)
  - 验证 f:`cat ~/.forgecode/teams/demo/config.json` 中 `members` 数组含 alice,`backend_type="tmux"`,`pane_id` 非空
  - 验证 g:`~/.forgecode/teams/demo/mailbox/<alice_agent_id>.json` 中应已含一条 `from=lead` 的 text 消息——Pane 后端的 initial_prompt 预写入证据
- [ ] 在 TUI 输入 `/team info demo`
  - 预期:输出含 alice 行,显示 worktree、pane_id、is_active 状态
- [ ] 在 TUI 输入:「给 alice 发消息,让她再写一行 world 到 /tmp/test_alice.txt」
  - 预期:Agent 调 `SendMessage(to="alice", summary="append world", message="...")`
  - 验证 a:alice pane 被唤醒(`tmux send-keys` 触发,pane 显示新内容)
  - 验证 b:30 秒内,`cat /tmp/test_alice.txt` 看到第二行 `world`
- [ ] 等待 alice 任务自然结束(或在 TUI 输入 `/team kill alice` 终止)
  - 验证 a:`cat ~/.forgecode/teams/demo/config.json` 中 alice 的 `is_active` 为 `false`(跨进程 reload 修复——alice 子进程的 `set_member_active(False)` 必须真的反映到 disk;早期 bug 是静默 no-op)
  - 验证 b:Lead 的 mailbox(`cat ~/.forgecode/teams/demo/mailbox/lead.json`)含一条 `summary` 含 `idle` 的消息,且 1-2 秒后该消息 `read=true`(watcher 已消费)
  - 验证 c:Lead 屏幕**不需要用户输入**自动出现 `● [team-update] 队员发来新消息...` 文本块 + 紧接的 Synthesis 回复(自动唤醒)
- [ ] 在 TUI 输入 `/team delete demo --force`
  - 验证 a:`ls ~/.forgecode/teams/` 无 `demo` 目录
  - 验证 b:`ls /path/to/forgecode/.forgecode/worktrees/` 无 `team-demo+alice`
  - 验证 c:`tmux list-panes` 只剩 Lead pane,alice 的 `%1` 被 `backend.kill` 干掉了

**场景 2:in-process 后端实跑**

环境准备:
- `unset TMUX TERM_PROGRAM`(确保 detect_backend 选 in-process)
- 在非 tmux 终端窗口内

步骤:
- [ ] 启动 `uv run python -m forgecode`(同会话已 unset 上述变量)
- [ ] 在 TUI 输入:「创建 inproc 团队」
  - 验证:`cat ~/.forgecode/teams/inproc/config.json` 中 `backend` 为 `in-process`
- [ ] 在 TUI 输入:「派 bob 用 general-purpose,在 worktree 里 `echo step1 > /tmp/bob.txt`」
  - 验证:无新终端窗口/pane 出现(同进程 asyncio task)
  - 验证:`/tmp/bob.txt` 内容 `step1`
- [ ] 等 bob 结束(`/team info inproc` 看 `is_active=False`)
- [ ] 在 TUI 输入:「给 bob 发消息让他再加一行 step2」
  - 验证:`/tmp/bob.txt` 多一行 `step2`
  - 验证:`/team info inproc` 看 bob 在 active → idle 反复变化
- [ ] `/team delete inproc --force` 清理

**场景 3:Coordinator Mode 实跑**

环境准备:
- `.forgecode/config.yaml` 加 `features:\n  coordinator_mode: true`(snake_case)
- 设环境变量 `FORGECODE_COORDINATOR_MODE=1`

步骤:
- [ ] `FORGECODE_COORDINATOR_MODE=1 uv run python -m forgecode`
- [ ] 观察 TUI 状态栏出现 `[COORDINATOR]` 标签
- [ ] 在 TUI 输入:「写一个 hello world 到 /tmp/coord_test.txt」
  - 预期:`write_file` **不在 Lead 工具集**(被 `set_allowed_tools` 剥夺),LLM 应该说"我没有 write_file 工具"并尝试用 bash 转写
  - 验证:`cat /tmp/coord_test.txt` 文件不存在(若用户拒掉 bash 的话)
- [ ] 在 TUI 输入:「跑 `git status`」
  - 预期:Agent 调 `bash`,工具正常执行(bash 在 Coordinator 白名单中)
  - 验证:输出含 git 状态信息
- [ ] 在 TUI 输入:「派几个队员探索 forgecode 的 src/forgecode/agent 和 src/forgecode/team」
  - 预期:Lead 调 Agent + SendMessage 派出队员后,**不**立刻调 read_file/glob/bash 自己探索(被 Coordinator system prompt 中的纪律段约束)
  - 验证:Lead 派完队员的回复应该是"等待汇报中"类似措辞;在队员发完 idle 消息前 Lead 屏幕没新工具调用

**场景 4:Plan 审批工作流**

环境准备:无特殊

步骤:
- [ ] 准备一个角色定义 `~/.forgecode/agents/planner.md`,frontmatter 含 `permission_mode: plan`,body 简述「先制定计划」
- [ ] 启动 forgecode,创建 team `plan-test`
- [ ] 在 TUI 输入:「派 planner 用 planner 角色,在 worktree 制定 hello world 程序的实现计划」
  - 预期:planner 队员以 plan 模式起步,生成计划后通过 SendMessage 发给 Lead
  - 验证:Lead mailbox 含计划消息
- [ ] 在 TUI 输入:「批准 planner 的计划」
  - 预期:Lead 调 `SendMessage(to="planner", type="plan_approval_response", payload={approve:True})`
  - 验证:planner 收到后切换权限模式,继续执行计划

## 失败回归

- [ ] forgecode 启动时 `~/.forgecode/teams/` 不存在,自动创建,不报错
- [ ] `~/.forgecode/teams/<somename>/config.json` 内容损坏时,启动只 stderr 警告,跳过该 Team
- [ ] 创建 Team 时若 disk 写失败(可手动 chmod 模拟),抛错,不留半成品目录
- [ ] mailbox 文件锁抢占冲突 10 次仍失败时,SendMessage 抛错,不丢消息
- [ ] tmux 后端在 `tmux split-window` 失败时(非 tmux 会话),抛错,Team.members 不留半成品
- [ ] 协作工具被主 Agent 误调用(主 Agent 工具列表本应不含)时,工具自己也抛错兜底