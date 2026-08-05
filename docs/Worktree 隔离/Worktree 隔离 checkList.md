# Worktree 隔离 Checklist

> 每一项通过运行代码或观察行为来验证,聚焦系统行为。

## 实现完整性### worktree 子包

- [ ] src/forgecode/worktree 子包存在且可导入(验证:`python -c "from forgecode import worktree"`)
- [ ] `validate_slug` 对合法/非法 case 行为符合 spec F1(验证:`pytest tests/test_worktree_slug.py -v`)
- [ ] `flat_slug("team/alice") == "team+alice"`(验证:同上)
- [ ] `WorktreeSession` JSON 序列化/反序列化字段名为下划线小写(验证:`pytest tests/test_worktree_manager.py -k session -v`)
- [ ] `save_session` 原子写——失败前不破坏既有文件;`save_session(path, None)` 写入 `null`(验证:同上)
- [ ] `_run_git` 设置 `GIT_TERMINAL_PROMPT=0` + `GIT_ASKPASS=""`、stdin=DEVNULL(验证:`pytest tests/test_worktree_git.py -k run_git -v`)
- [ ] `_has_worktree_changes` 在临时 git 仓库内:无修改返回 False;改一个文件返回 True;git 命令出错 fail-closed 返回 True(验证:同上)
- [ ] `_resolve_head_sha_from_fs` 在真实 worktree 路径下返回 commit SHA(验证:`pytest tests/test_worktree_git.py -k resolve_head`)
- [ ] `Manager(repo_root)` 校验 repo_root 是 git 仓库;非 git 目录抛 ValueError(验证:`pytest tests/test_worktree_manager.py -k construct -v`)
- [ ] `Manager` 加载已存在的 session 文件;指向不存在目录的 session 自动清空(验证:同上)
- [ ] `manager.create("alice", "HEAD", manual=True)` 在 `.forgecode/worktrees/alice/` 下落地 + 分支 `worktree-alice`(验证:`pytest tests/test_worktree_create.py`)
- [ ] `manager.create("team/alice", ...)` 落地 `.forgecode/worktrees/team+alice/` + 分支 `worktree-team+alice`(验证:同上)
- [ ] `manager.create` 目录已存在时走快速恢复(不调 git;active 立即就绪)(验证:同上,可用 monkeypatch 替换 `_run_git` 断言未被调用)
- [ ] `manager.create` 已 active 名字时再 create 抛异常(验证:同上)
- [ ] 创建后设置 A——`.forgecode/settings.local.yaml` 被复制到 Worktree(验证:同上,需在测试 fixture 准备文件)
- [ ] 创建后设置 B——主仓 `.husky/` 存在时 Worktree git config 含 core.hooksPath(验证:`pytest tests/test_worktree_create.py -k hooks`)
- [ ] 创建后设置 C——主仓 node_modules 存在时 Worktree 内为软链(`Path.is_symlink()` 为 True)(验证:`pytest tests/test_worktree_create.py -k symlink`)
- [ ] 创建后设置 D——主仓 `.worktreeinclude` 模式命中的 ignored 文件被复制到 Worktree(验证:`pytest tests/test_worktree_create.py -k include_ignored`)
- [ ] `manager.enter(name)` 不改变进程 `Path.cwd()`,返回 session 含 original_cwd/worktree_path/session_id 等字段(验证:`pytest tests/test_worktree_lifecycle.py -k enter`)
- [ ] `manager.enter` 持久化 session 到 `.forgecode/worktree_session.json`(验证:同上)
- [ ] `manager.exit(name, REMOVE, ExitOptions())` 有变更时抛 `WorktreeHasChangesError`,Worktree 目录仍在(验证:`pytest tests/test_worktree_lifecycle.py -k exit`)
- [ ] `manager.exit(name, REMOVE, ExitOptions(discard_changes=True))` 成功删除 Worktree + 分支;session 文件被清空(验证:同上)
- [ ] `manager.exit` 调用了 `os.chdir(original_cwd)` 兜底(验证:测试时改进程 cwd 后调 exit,断言 cwd 回到 original)
- [ ] `manager.remove(name, ExitOptions())` 与 exit 的 remove 分支一致,但允许非当前 session(验证:同上)
- [ ] `manager.auto_cleanup` 对 manual=True 直接 kept=True(验证:`pytest tests/test_worktree_lifecycle.py -k auto_cleanup`)
- [ ] `manager.auto_cleanup` 无变更时 remove 并返回 kept=False;有变更返回 kept=True(验证:同上)
- [ ] `manager.sweep_stale` 第一层只识别 `agent-a[0-9a-f]{7}` 模式;手动命名跳过(验证:`pytest tests/test_worktree_sweep.py`)
- [ ] `manager.sweep_stale` 跳过当前 session 的目录(验证:同上)
- [ ] `manager.sweep_stale` 有未提交修改 / 未推送 commit 的目录跳过(fail-closed)(验证:同上)
- [ ] `worktree.random_agent_name` 返回形如 `agent-a[0-9a-f]{7}` 的字符串(验证:`pytest tests/test_worktree_sweep.py -k random_agent_name`)

### tool 包 ctx 改造

- [ ] `tool.with_cwd` / `cwd_from_ctx` / `resolve_path` 三函数存在(验证:`pytest tests/test_tool_ctx.py -v`)
- [ ] `resolve_path` 对绝对路径直接返回;对相对路径用 ctx cwd 或 `Path.cwd()` 拼接(验证:同上)
- [ ] `read_file(path="a.txt")` 在 `with with_cwd(tmp_dir):` 下读 tmp_dir/a.txt(验证:`pytest tests/test_tool_read_file.py -k cwd`)
- [ ] `write_file(path="a.txt")` + ctx cwd 同上(验证:同上)
- [ ] `edit_file(path="a.txt")` + ctx cwd 同上(验证:同上)
- [ ] `bash(command="pwd")` + ctx cwd 输出 cwd 路径(验证:`pytest tests/test_tool_bash.py -k cwd`)
- [ ] `glob(pattern="*.txt")` + ctx cwd 在 cwd 内搜索(验证:`pytest tests/test_tool_glob.py -k cwd`)
- [ ] `grep` + ctx cwd 同上(验证:`pytest tests/test_tool_grep.py -k cwd`)
- [ ] 工具 schema 不变——`Tool.parameters` 不含新字段(验证:对比 ch13 测试快照,或断言 keys)

### subagent 包扩展

- [ ] `subagent.Definition` 含 `isolation: str` 字段(验证:`pytest tests/test_subagent_definition.py`)
- [ ] `parse_definition` 正确解析 `isolation: worktree`(验证:`pytest tests/test_subagent_parser.py -k isolation -v`)
- [ ] 非法 `isolation` 值时 stderr 警告并回落 `""`(验证:同上,用 `capsys` 断言)
- [ ] 既有定义不写 isolation 时 `isolation == ""`(验证:同上)

### agent 包扩展

- [ ] `agent.AgentTool` 含 `worktree_mgr: worktree.Manager | None` 字段;`__init__` 签名末尾接收 worktree_mgr(验证:`python -c "from forgecode.agent import AgentTool"`)
- [ ] `agent._execute_with_worktree` 调用 `manager.create` + `auto_cleanup`,期间通过 ctx 传 wt.path(验证:`pytest tests/test_agent_worktree.py -v`)
- [ ] `build_worktree_notice` 输出含 `<worktree-context>` 标签 + 父目录 + 工作目录(验证:同上)
- [ ] `AgentTool.execute` 在 `definition.isolation == "worktree"` 时走 worktree 分支(验证:同上)
- [ ] `AgentTool.execute` 在 `worktree_mgr is None` 且 isolation=worktree 时返回 `is_error=True`(验证:同上)
- [ ] `AgentTool.execute` 在 isolation=worktree + background=True 时强制走前台路径(验证:同上)

### command 包扩展

- [ ] `command.WorktreeSummary` 与 `WorktreeAccessor` Protocol 存在(验证:`python -c "from forgecode.command.ui import WorktreeAccessor, WorktreeSummary"`)
- [ ] `UI` Protocol 加 `worktree_accessor()` 方法;`nop_ui` 返回 None(验证:同上)
- [ ] `/worktree` 命令被注册,lookup 命中(验证:`pytest tests/test_command_builtins.py -k worktree_registered`)
- [ ] `handle_worktree` 分发子命令 create/list/enter/exit/remove(验证:`pytest tests/test_command_builtins.py -k handle_worktree -v`)
- [ ] `handle_worktree` 在 `ui.worktree_accessor()` 返回 None 时报错(验证:同上)

### tui 包扩展

- [ ] `forgecodeApp` 含 `worktree_mgr: worktree.Manager | None` 与 `active_cwd: str` 字段(验证:`python -c "from forgecode.tui.app import forgecodeApp"`)
- [ ] `forgecodeApp.__init__` 接收 `worktree_mgr` 参数;启动时若 `manager.current_session()` 非 None,设 `active_cwd=session.worktree_path`(验证:`pytest tests/test_tui_app.py -k worktree`)
- [ ] 主 Agent Run 前用 `with with_cwd(...):` 包住——可通过 mock provider 断言 tool 调用收到的 cwd(验证:同上)
- [ ] worktree_adapter 实现 WorktreeAccessor 协议(验证:`python -c "from forgecode.tui.worktree_adapter import WorktreeAdapter"`)

### cli 接入

- [ ] src/forgecode/cli.py 构造 Manager,失败 stderr 警告 + 降级(验证:启动 forgecode + 在非 git 目录测试)
- [ ] AgentTool 构造末尾追加 worktree_mgr(验证:同上)
- [ ] forgecodeApp 构造接收 worktree_mgr(验证:同上)
- [ ] 启动时异步跑 sweep_stale(验证:`grep -n sweep_stale src/forgecode/cli.py`)
- [ ] .gitignore 追加 `.forgecode/worktrees/` 与 `.forgecode/worktree_session.json`(验证:`git check-ignore .forgecode/worktrees/test`)

## 集成

- [ ] subagent.Definition.isolation + agent.AgentTool 协同——isolation:worktree 的 SubAgent 启动时自动创建 Worktree(验证:test_agent_worktree 通过)
- [ ] tool ctx with_cwd + AgentTool._execute_with_worktree 协同——SubAgent 在 Worktree 内的工具调用使用 wt.path 作为 cwd(验证:集成测试,在临时 git repo 跑一个 mock subagent)
- [ ] 主 Agent 工具列表稳定——5 个核心工具 + Agent + TaskList + TaskGet + TaskStop + SendMessage + worktree 不暴露新工具(验证:工具数计数)
- [ ] worktree 包 + subagent 包 + agent 包 + command 包 + tui 包之间无导入循环(验证:`python -c "import forgecode.tui.app, forgecode.agent.agent_tool, forgecode.command.builtins, forgecode.worktree"`)

## 编译与测试

- [ ] 项目可启动:`python -m forgecode --help`(或正常进 TUI)
- [ ] 所有单元测试通过:`pytest`
- [ ] lint 通过:`ruff check`(可选 `ruff format --check`)

## 端到端场景(tmux 实跑)

每个场景在 tmux 内启动一个 forgecode 实例完成,验证可视化行为。

**通用预置:**
- 当前目录 `cd /Users/codemelo/forgecode`
- 已执行 `uv sync` 或 `pip install -e .`

### 场景 1:isolation:worktree 子 Agent 修改文件不影响主目录**预置:** 创建项目级自定义 Agent:

```
.forgecode/agents/worktree-writer.md
---
name: worktree-writer
description: 在 Worktree 内写文件的测试 Agent
permission_mode: dontAsk
max_turns: 5
isolation: worktree
---

你是一个测试 Agent。当用户让你写文件时,直接用 write_file 工具写,不要询问。
```

并准备一个主目录文件 `echo "MAIN" > scratch_ch14.txt`(测试前 git status 干净,这个文件未跟踪)。

**步骤:**
- [ ] tmux 启动:`tmux new-session -d -s ch14 -x 200 -y 50 "python -m forgecode"`
- [ ] 输入:「用 Agent 工具调 subagent_type=worktree-writer,prompt 是『把 scratch_ch14.txt 的内容覆盖为 SUBAGENT,只用 write_file 工具』」
- [ ] 子 Agent 跑动,scrollback 出现 `Agent(...)` 行
- [ ] tool_result 中末尾含 `[Worktree 保留: .forgecode/worktrees/agent-a... ,分支 worktree-agent-a...]`(因为有未提交修改,auto_cleanup 保留)
- [ ] **主目录** `cat scratch_ch14.txt` 仍为 `MAIN`(验证主目录未被改)
- [ ] **Worktree 副本** `cat .forgecode/worktrees/agent-a*/scratch_ch14.txt` 为 `SUBAGENT`
- [ ] tmux 截屏断言:`tmux capture-pane -p -t ch14 | grep -i "worktree"`
- [ ] 清理:`rm scratch_ch14.txt`,删除残留 worktree:在 forgecode 内 `/worktree remove agent-a... --discard`(或 `git worktree remove --force` 手动清)
- [ ] tmux kill-session -t ch14

### 场景 2:isolation:worktree 子 Agent 无变更时自动清理**预置:** 同场景 1 的 worktree-writer.md(已存在)。

**步骤:**
- [ ] tmux 启动 forgecode
- [ ] 输入:「用 Agent 工具调 subagent_type=worktree-writer,prompt 是『用 read_file 读 README.md 头 5 行,然后用 30 字总结』」
- [ ] 子 Agent 跑动,tool_result 是总结文本
- [ ] tool_result **不含**「Worktree 保留」字样(因为读文件不产生修改,auto_cleanup 直接清理)
- [ ] `ls .forgecode/worktrees/` 不存在与本次任务对应的 `agent-a*` 目录(已被 auto_cleanup 删除)
- [ ] tmux kill-session

### 场景 3:`/worktree create` + `/worktree list` 手动管理**预置:** 当前在 main 分支,git 工作区干净。

**步骤:**
- [ ] tmux 启动 forgecode
- [ ] 输入:`/worktree create demo-feature`
- [ ] scrollback 显示 `Worktree 已创建: .forgecode/worktrees/demo-feature (分支 worktree-demo-feature)`
- [ ] 输入:`/worktree list`
- [ ] scrollback 显示一行含 `demo-feature` 的列表项,标记 `[manual]`(`manual=True`)
- [ ] tmux 外验证:`ls .forgecode/worktrees/demo-feature/` 含正常 forgecode 仓库内容;`git -C .forgecode/worktrees/demo-feature branch` 显示在 `worktree-demo-feature`
- [ ] 清理:输入 `/worktree remove demo-feature --discard`
- [ ] 验证 `.forgecode/worktrees/demo-feature` 已不存在
- [ ] tmux kill-session

### 场景 4:`/worktree exit` 变更保护**预置:** 同场景 3 创建好 `demo-feature`。

**步骤:**
- [ ] 手动写一个修改:`echo "modified" > .forgecode/worktrees/demo-feature/test.txt`
- [ ] tmux 启动 forgecode
- [ ] 输入:`/worktree enter demo-feature`
- [ ] 输入:`/worktree exit --remove` (不加 --discard)
- [ ] scrollback 显示错误 `worktree has uncommitted changes or new commits`(或对应中文消息)
- [ ] 输入:`/worktree exit --remove --discard`
- [ ] scrollback 显示成功消息,worktree 已被删除
- [ ] tmux kill-session

### 场景 5:explicit cwd——`/worktree enter` 后工具调用用 worktree 路径**预置:** 创建 worktree 并准备测试文件。

**步骤:**
- [ ] tmux 启动 forgecode
- [ ] 输入:`/worktree create cwd-test`
- [ ] 在 tmux 外:`echo "in-worktree-only" > .forgecode/worktrees/cwd-test/probe.txt`(主目录无 probe.txt)
- [ ] tmux 内输入:`/worktree enter cwd-test`
- [ ] 输入:「用 read_file 读 probe.txt」
- [ ] 主 Agent 调 read_file 工具(path=probe.txt 相对路径)
- [ ] tool_result 应为 `in-worktree-only`(证明 cwd 解析到 worktree 路径)
- [ ] 输入:`/worktree exit`,主目录 cwd 恢复
- [ ] 再输入:「用 read_file 读 probe.txt」
- [ ] tool_result 报「无法访问文件 probe.txt」(主目录没这文件)
- [ ] 清理:`/worktree remove cwd-test --discard`
- [ ] tmux kill-session

### 场景 6:Slug 校验阻止路径遍历**步骤:**
- [ ] tmux 启动 forgecode
- [ ] 输入:`/worktree create ../etc`
- [ ] scrollback 显示错误,含「invalid」或「拒绝」(不创建 `.forgecode/etc/` 或类似)
- [ ] 输入:`/worktree create ..`
- [ ] 同样错误
- [ ] 输入:`/worktree create normal_one`
- [ ] 成功创建
- [ ] 清理:`/worktree remove normal_one --discard`
- [ ] tmux kill-session