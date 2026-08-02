# slash命令体系 Checklist

> 每一项通过运行代码或观察行为来验证，聚焦系统行为；不依赖具体实现细节。

## 实现完整性

- [ ] /help 输出含 12 条命令名/描述(验证:`pytest -k test_register_builtins_all_registered tests/test_command_builtins.py` 绿 + tmux 场景 A2)
- [ ] /plan 不调用 `conv.add_user`、不触发 LLM 回合(验证:`pytest -k test_tui_dispatch_plan_local_only tests/test_tui.py` 绿)
- [ ] /do 触发 LLM 回合且写入会话存档(验证:`pytest -k test_tui_dispatch_do_injects_and_sends tests/test_tui.py` 绿 + tmux 场景 D2 后 `tail -3 $SESSIONS_DIR/<latest>.jsonl` 含新增 `"role":"user"` 记录)
- [ ] `register_builtins(reg)` 注册了恰好 12 条命令(验证:`pytest -k test_register_builtins_all_registered tests/test_command_builtins.py` 绿)
- [ ] 12 条命令的名字完整、命令名全小写、互不重复(验证:同上 + 看 test 断言列表)

## 注册中心行为

- [ ] 名字冲突立即 `raise RuntimeError`;异常消息含具体冲突名(验证:`pytest -k test_register_duplicate_name tests/test_command_registry.py` 绿)
- [ ] 别名冲突立即 `raise RuntimeError`;异常消息含具体冲突别名(验证:`pytest -k test_register_duplicate_alias tests/test_command_registry.py` 绿)
- [ ] `visible()` 返回按 name 字典序排序的可见命令(验证:`pytest -k test_visible_sorted tests/test_command_registry.py` 绿)
- [ ] `prefix_match("/s")` 仅命中以 "s" 开头的命令名,不含别名匹配、不含描述匹配(验证:`pytest -k test_prefix_match tests/test_command_registry.py` 绿)
- [ ] `parse("/Help")` 返回 `("help", True)`;`parse("")` 与 `parse("hello")` 返回 `("", False)`;`parse("/help xx")` 返回 `("", True)`(尾随参数让 lookup miss 走未命中分支);`parse("/ /help")` 返回 `("", True)`(验证:`pytest -k test_parse tests/test_command_dispatch.py` 绿)

## 命令分发与三类执行

- [ ] 提交 `/help` 后输出 12 行命令名/描述,且不调用 `conv.add_user`、不触发 LLM 回合(验证:`pytest -k test_tui_dispatch_help_lists_all_builtins tests/test_tui.py` 绿)
- [ ] 提交未知命令 `/foobar` 后输出文本含子串 "未知命令" 与 "/help" 两个关键字;不触发 LLM 回合(验证:`pytest -k test_tui_unknown_slash_command_friendly tests/test_tui.py` 绿)
- [ ] 提交 `/Help`(大小写混合)与 `/help` 行为一致(验证:`pytest -k test_tui_dispatch_case_insensitive tests/test_tui.py` 绿)
- [ ] 空字符串/纯空白字符提交时既不进 LLM 也不进分发器(验证:人工跑 tmux 场景"空回车"看无任何输出新增)
- [ ] /do 提交后会向 `conv.add_user` 追加文本"请按上面的计划开始执行。"且立即触发 LLM 回合(验证:`pytest -k test_tui_dispatch_do_injects_and_sends tests/test_tui.py` 绿 或 tmux 场景观察)
- [ ] /review 提交后会向 `conv.add_user` 追加文本含子串"审查"且立即触发 LLM 回合(验证:同上)
- [ ] /compact 在 `IDLE` 触发 `Agent.run_force_compact`;非 idle 状态打印"请等待当前任务完成"(验证:既有 test_tui_slash_compact_routes_to_command 迁移版 + 非 idle 情况新加用例)
- [ ] handler 抛异常时,用户看到 `error_block` 文案(验证:在单测中 mock 一个抛异常的 handler,断言 `app._pending_println` 含 `ERROR` 前缀)

## 12 条命令的具体输出

- [ ] /help 输出包含完整字符串 `/help`、`/status`、`/memory`、`/permission`、`/session`、`/clear`、`/review`、`/exit`、`/plan`、`/do`、`/compact`、`/resume` 共 12 个名字(验证:tmux 场景截屏 grep)
- [ ] /status 输出按顺序包含 6 行,每行 key 分别为 `Mode:`、`Tokens:`、`Tools:`、`Memories:`、`Model:`、`Directory:`(验证:`tmux capture-pane -p` 后按行 grep)
- [ ] /memory 输出在 `MEMORY.md` 存在时至少列出 "MEMORY.md" 这个文件名(验证:tmux 场景观察)
- [ ] /permission 输出当前 mode 的 `value`(default/plan/acceptEdits/bypassPermissions 之一)(验证:tmux 场景对照状态栏徽章)
- [ ] /session 输出至少 2 行,key 分别为 `Session:` 与 `Path:`(验证:tmux 场景截屏 grep)
- [ ] /clear 后状态栏 Tokens 区域消失或显示 0;旧会话 JSONL 文件仍在磁盘上(验证:tmux 场景 + `ls $SESSIONS_DIR/`)

## 自动补全菜单

- [ ] 输入框首字符输入 `/` 后,菜单立即激活并显示 12 条候选(验证:tmux 场景按 `/` 后 `capture-pane`)
- [ ] 继续输入 `s`(输入框为 `/s`)后,菜单只剩 /session 和 /status(验证:tmux 场景)
- [ ] 把输入框清空(全部退格)后菜单立即消失(验证:tmux 场景)
- [ ] 按 ↓ 高亮下移、↑ 高亮上移;按 ESC 菜单消失且输入框文本保留(验证:tmux 场景)
- [ ] 高亮 /status 后按回车,菜单消失、/status 立即执行、输入框清空(验证:tmux 场景)
- [ ] 高亮 /session 后按 Tab,菜单消失、/session 立即执行(验证:tmux 场景)
- [ ] 按 `/` 显示 12 条候选时,菜单可见行数 ≤ 8;按 ↓ 越过第 8 行后下方候选滚入视野
- [ ] 菜单不显示 `hidden=True` 的命令(本期没有 hidden 命令;通过单测验证机制:在 test_command_registry 中注册一条 `hidden=True` 看 `visible()` 不含它)

## 集成

- [ ] /help、未命中提示、`prompt.READY_HINT` 三处均不出现硬编码命令清单(验证:`grep -rE "/(exit|plan|do|compact|resume|help|clear|review|status|memory|permission|session)" src/forgecode/prompt.py src/forgecode/tui/commands.py` 应只在新分发器代码内出现一次类型常量)
- [ ] 状态栏左侧 mode 徽章渲染与本 spec 实施前完全一致(验证:`git diff main -- src/forgecode/tui/view.py | grep -E "(mode_label|mode_status_style|status_bar)"` 应无内部逻辑变更)
- [ ] /resume、/compact 沿用 ch09 的 `SessionState.IDLE` 限制(验证:T10 后跑既有 ch09 验收场景一遍)

## 编译与测试

- [ ] `python -m forgecode` 在合法配置下能正常启动 TUI
- [ ] `pytest -q` 全部通过
- [ ] `ruff check .` 无告警
- [ ] `ruff format --check .` 通过(或本地 `ruff format .` 已统一格式)
- [ ] (可选)`mypy src/forgecode` 通过

## 启动期冲突检测

- [ ] 在 `builtins.py` 中临时把某条命令注册两次,`python -m forgecode` 立即抛 `RuntimeError` 退出,异常文本含具体冲突的命令名(验证:人工临时改动 + 跑 forgecode + 还原)

## 端到端场景(tmux 实跑)

> 验证目标:在真实 tmux 会话内运行 forgecode 进程,按 plan/spec 描述跑完整流程。
> 准备:`uv sync`(或 `pip install -e ".[dev]"`);开一个 `~/.forgecode/memory/MEMORY.md` 保证 /memory 至少能列一条;`SESSIONS_DIR=$PWD/.forgecode/sessions`(按 forgecode 实际默认目录;如未自定义则使用 `${FORGECODE_HOME:-$PWD/.forgecode}/sessions`)。

### 场景 A: 启动与 /help- [ ] **A1** 启动会话:`tmux new-session -d -s mewspec -x 200 -y 50 "uv run forgecode 2>/tmp/forgecode.err"`;`sleep 2`;`tmux capture-pane -t mewspec -p | grep -E "(ForgeCode|Send a message|DEFAULT|PLAN|default|plan)"` 至少命中 2 个关键字
- [ ] **A2** 跑 /help:`tmux send-keys -t mewspec '/help' Enter`;`sleep 1`;`tmux capture-pane -t mewspec -p | head -30` 含 /clear、/compact、/do、/exit、/help、/memory、/permission、/plan、/resume、/review、/session、/status 全部 12 个名字,且按字典序排列

### 场景 B: 纯本地命令- [ ] **B1** /status:`tmux send-keys -t mewspec '/status' Enter`;`sleep 1`;capture 含 `Mode:` `Tokens:` `Tools:` `Memories:` `Model:` `Directory:` 6 行 key 名;Mode 值与状态栏徽章一致
- [ ] **B2** /permission:`tmux send-keys -t mewspec '/permission' Enter`;capture 输出含当前 mode 的 `value` (例如 `default` 或 `plan`)
- [ ] **B3** /memory:`tmux send-keys -t mewspec '/memory' Enter`;capture 至少有 1 行文件名,无报错
- [ ] **B4** /session:`tmux send-keys -t mewspec '/session' Enter`;capture 含 `Session:` 与 `Path:` 两行 key
- [ ] **B5** /help、/status、/permission、/memory、/session 跑完后状态栏 Tokens 计数保持 0 in / 0 out(纯本地不消耗 token)

### 场景 C: 自动补全菜单- [ ] **C1** 仅按 `/`:`tmux send-keys -t mewspec '/'`;`sleep 0.3`;capture 看到补全菜单含 12 条候选,在输入框下方
- [ ] **C2** 继续按 `s`:`tmux send-keys -t mewspec 's'`;capture 看到菜单只剩 /session 和 /status
- [ ] **C3** 按 ↓ 切高亮后回车执行次条命令:`tmux send-keys -t mewspec Down Enter`;capture 出现次条命令(如 /status)的特征输出 `Mode:`,反向证明高亮已切换
- [ ] **C4** 按 Enter 执行:`tmux send-keys -t mewspec Enter`;capture 看到 /status 的 6 字段输出(高亮是 /status 时)
- [ ] **C5** 输入 `/s` 后按 ESC:`tmux send-keys -t mewspec '/s' Escape`;`tmux capture-pane -t mewspec -p | tail -5` 输入框行(带 ╭─╯ 或边框的行)含 `/s` 字面且无命令执行输出
- [ ] **C6** 把 `/s` 全部删空:`tmux send-keys -t mewspec BSpace BSpace`;capture 看到菜单消失

### 场景 D: 影响界面命令- [ ] **D1** /plan 切到 PLAN:`tmux send-keys -t mewspec '/plan' Enter`;`tmux capture-pane -t mewspec -p | tail -1 | grep -i "plan"` 命中
- [ ] **D2** /do 切回 DEFAULT 并触发 AI 回复:`tmux send-keys -t mewspec '/do' Enter`;`sleep 5`(等流式开始);capture 状态栏左侧变 DEFAULT、scrollback 出现 AI 回复内容
- [ ] **D3** /compact 强制压缩:`tmux send-keys -t mewspec '/compact' Enter`;`sleep 5`;capture 看到 Compact 进度 notice、压缩完成后状态栏 Tokens 计数显著下降(或归零)
- [ ] **D4** /clear 开新 session:记录当前 `ls $SESSIONS_DIR/` 的文件数 N;`tmux send-keys -t mewspec '/clear' Enter`;capture 看到 "已清空当前会话,开启新 session" 类似 notice;`ls $SESSIONS_DIR/` 文件数变为 N+1(旧会话保留 + 新会话开启)

### 场景 E: 提示词命令- [ ] **E1** /review 注入审查请求:`tmux send-keys -t mewspec '/review' Enter`;`sleep 5`;capture 状态栏进入流式 + AI 开始回复;检查最新 session JSONL 文件:`tail -3 $SESSIONS_DIR/<latest>.jsonl` 含一条 `"role":"user"` 且文本含"审查"关键字

### 场景 F: /resume 恢复旧会话(集成 D4 后续)- [ ] **F1** 在 D4 之后,`tmux send-keys -t mewspec '/resume' Enter`;capture 看到会话列表(`SessionState.RESUMING`);使用 ↓ 选中 D4 之前的旧会话,Enter;`sleep 2`;capture 看到旧会话的 scrollback 内容已重新出现 + 状态栏 Tokens 计数为旧会话累计值(会话文件位于 `$SESSIONS_DIR/`)
- [ ] **F2** 空回车验证见 G2;纯空白字符(全空格 + 回车)见 G2 同场景

### 场景 G: 未命中与异常- [ ] **G1a** 发命令前 baseline:`tmux capture-pane -p -t mewspec | grep -E "Tokens" > /tmp/g1_before.txt`
- [ ] **G1b** 发未知命令:`tmux send-keys -t mewspec '/foobar' Enter`;`sleep 2`
- [ ] **G1c** capture 后断言(a)`tmux capture-pane -p -t mewspec` 含 "未知命令" 与 "/help" 两个关键字、(b)`tmux capture-pane -p -t mewspec | grep -E "Tokens"` 与 `/tmp/g1_before.txt` 完全一致、(c)capture 中无 AI 回复块标志(没有 assistant role 输出)、(d)`tail -3 $SESSIONS_DIR/<latest>.jsonl | grep -E '"role":"assistant"'` 无新增
- [ ] **G2** 仅按 Enter(空回车)与纯空白字符(全空格 + 回车):`tmux send-keys -t mewspec Enter`;`tmux send-keys -t mewspec '   ' Enter`;capture 无新增 notice、无新 user 消息

### 场景 H: 启动期冲突检测- [ ] **H1** 临时编辑 `src/forgecode/command/builtins.py`,把 /help 命令再注册一次同名;`python -m forgecode 2>&1 | head -10`;输出含 "RuntimeError" 与 "help"(或具体冲突文本);还原 builtins.py

### 场景收尾- [ ] **/exit 端到端验证**:`tmux send-keys -t mewspec '/exit' Enter`;`sleep 1`;`tmux has-session -t mewspec 2>&1` 应报 "can't find session"
- [ ] **错误日志可观察**:`wc -l < /tmp/forgecode.err` 输出为 0 或仅含白名单 info 行
- [ ] 关闭测试会话(若 /exit 未成功):`tmux kill-session -t mewspec 2>/dev/null || true`
- [ ] 所有截屏证据复制到本任务的端到端验证报告里(每个场景至少 1 张 capture 输出)

## 完成准则

- 上面所有 checkbox 全部勾选,且每一项的"验证"步骤已实际执行并记录证据
- `git status` 无未跟踪/未提交的临时调试改动(冲突检测的 builtins.py 临时改动已还原)