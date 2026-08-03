# Skill 技能包系统 Checklist

> 每一项通过运行代码或观察行为来验证。最后一节"端到端场景（tmux 实跑）"必须在 tmux 内实际跑过。

## 实现完整性

- [ ] `forgecode.skills` 包可正常 import（验证：`python -c "import forgecode.skills"` 无错）
- [ ] `forgecode.tool.load_skill` 与 `forgecode.tool.install_skill` 可正常 import（验证：`python -c "from forgecode.tool import load_skill, install_skill"`）
- [ ] `forgecode.prompt` 改造后单测通过（验证：`pytest tests/test_prompt.py`）
- [ ] `forgecode.command` 改造后单测通过（验证：`pytest tests/test_command*.py`）
- [ ] `forgecode.agent` 改造后单测通过（验证：`pytest tests/test_agent*.py`）
- [ ] 整包可启动（验证：`python -m forgecode` 不报错）
- [ ] `ruff check .` 无新增告警
- [ ] `ruff format --check .` 通过
- [ ] 内置三个 Skill（commit / review / test）的 SKILL.md 通过 frontmatter 与 body 双重校验（验证：启动后 `/skill` 输出三行）

## Skill 定义与解析

- [ ] 一个最简的合法 SKILL.md（仅 name + description）能被 parser 解析成功（验证：`tests/test_skills_parser.py` 中 `test_parse_skill_dir_minimal` 通过）
- [ ] 非法 name（大写、空格、超长）被 parser 拒绝（验证：`tests/test_skills_parser.py` 中 `test_parse_skill_dir_invalid_name` 通过）
- [ ] `tool.json` 合法时解析为 ToolSpec 列表（验证：`tests/test_skills_parser.py` 中 `test_parse_skill_dir_with_tool_json` 通过）
- [ ] 缺 SKILL.md 时抛 `FileNotFoundError`（验证：`tests/test_skills_parser.py` 中 `test_parse_skill_dir_no_skill_md` 通过）

## Catalog 加载

- [ ] 空 work_dir + 空 HOME 启动时 Catalog 仅含三个内置 Skill（验证：`tests/test_skills_catalog.py` `test_load_catalog_builtin_only` 通过）
- [ ] 用户目录下同名 Skill 覆盖内置（验证：`test_load_catalog_user_override` 通过）
- [ ] 项目目录下同名 Skill 覆盖用户（验证：`test_load_catalog_project_override` 通过）
- [ ] 单个 Skill 解析失败（损坏 SKILL.md）只跳过它本身，其它 Skill 仍能加载（验证：写一个临时 user 目录含损坏 + 合法两个 Skill，启动后只看到合法那一个）
- [ ] Skill 名字与 ch10 已有命令冲突时跳过加载（验证：临时建一个 name=help 的 Skill 放 user 目录，启动 stderr 打 warning 且 `/help` 仍为内置命令）

## fail-fast 依赖检查

- [ ] Skill 的 `allowed_tools` 引用不存在的工具时，启动 stderr 输出对应错误并把该 Skill 从 Catalog 中剔除（验证：建一个含 `allowed_tools: [NotExist]` 的 Skill，启动 stderr 含 `allowed_tool "NotExist" not registered`，`/skill` 中不出现该 Skill）
- [ ] `load_skill` / `install_skill` 在 fail-fast 检查中被视为允许引用（验证：建一个 `allowed_tools: [load_skill]` 的 Skill，启动正常加载，不报错）

## Slash Command 自动注册

- [ ] 启动后 `/help` 包含 `/commit [skill]`、`/review [skill]`、`/test [skill]` 三行且不再有独立 `/review`（验证：tmux 启动后键入 `/help`）
- [ ] `/help` 包含 `/skill` 一行（验证：同上）
- [ ] 用 Tab 补全输入 `/comm`，菜单展示 `/commit [skill]` 候选（验证：tmux 实跑）

## 两阶段加载

- [ ] System prompt 中含 `## Available Skills` 区块，列出全部 Catalog Skill 的 `- name: description`（验证：在 `agent.run` 前打日志或加一个 dump-prompt 测试用例）
- [ ] 未激活任何 Skill 时 env context 不含 `## Active Skills` 区块（验证：单测 `render_active_skills_block([]) == ""`）
- [ ] 激活一个 Skill 后下一轮 env context 含 `## Active Skills` 区块包含该 Skill 的 body（验证：用单测覆盖 `render_active_skills_block`；端到端见 tmux 场景）

## LoadSkill 工具

- [ ] 调用 LoadSkill({"name":"commit"}) 后 `active.names()` 包含 `"commit"`（验证：单测）
- [ ] 调用 LoadSkill 不存在的 name 时返回 `unknown skill: <name>`，对话不中断（验证：tmux 实跑触发）
- [ ] LoadSkill 调用时即便 `allowed_tools` 是空白名单也可见（验证：单测 `Registry.definitions_filtered([])` 输出包含 `load_skill`）
- [ ] LoadSkill 在 Plan Mode 下可调用，不被权限拦截（验证：tmux 实跑 `/plan` 后让 LLM 触发 LoadSkill）

## /clear

- [ ] `/clear` 之后 `active.names()` 为空（验证：tmux 实跑：先触发 LoadSkill 激活某 Skill，再 `/clear`，下一轮观察 env context 无 Active Skills 块）
- [ ] `/clear` 之后新会话可在 `/resume` 列表中看到旧会话条目（验证：与 ch10 N9 一致，回归现有行为）

## Skill 执行器

- [ ] inline Skill 执行后主对话历史新增一条 user 消息（验证：tmux 触发 `/commit` 后 `/session` 显示路径，查看会话 JSONL）
- [ ] inline Skill 的 SOP 顶部含 "This skill is designed to use only these tools: ..." 提示（验证：单测覆盖 `render_body`）
- [ ] fork Skill 跑完后主对话新增一条 assistant 消息（验证：tmux 触发 `/review` 后会话 JSONL 末尾是 assistant 角色消息）
- [ ] fork Skill 失败（如子 Agent 报错或超时）时返回的 assistant 消息为 `[skill <name> failed: ...]` 文本（验证：mock provider 出错的执行器单测）

## tool.json 专属工具

- [ ] 一个含 `tool.json` 的 Skill 被 LoadSkill 激活后，主工具注册中心新增对应的工具名（验证：tmux 实跑：放一个测试 Skill 含 echo 的 `tool.json`，激活后让 LLM 调那个工具，观察输出）
- [ ] 专属工具 exec 超时 30 秒（验证：`tests/test_tool_skill_tool.py`：脚本 `sleep 100` 时返回 `asyncio.TimeoutError` 触发的错误结果）
- [ ] 专属工具 `returncode != 0` 视为失败，stderr 内容并入 result 文本（验证：单测）

## InstallSkill

- [ ] 合法 zip 安装后 `~/.forgecode/skills/<top_dir>/` 出现 SKILL.md（验证：单测 + tmux 实跑）
- [ ] 合法 zip 安装后 `/skill` 立即列出新 Skill 且 `/<name>` 可调用（验证：端到端）
- [ ] zip-slip（含 `..` 路径）被拒绝，`~/.forgecode/skills/` 无副作用（验证：单测 `test_install_from_url_zip_slip`）
- [ ] zip 内顶层目录命名违规时拒绝（验证：单测）
- [ ] InstallSkill 工具在 Plan Mode 下被权限引擎拦截，需要切回默认模式才能装（验证：tmux 实跑 `/plan` → 自然语言让 Agent 装 Skill → 看到权限被拦截）

## /skill 命令

- [ ] `/skill` 首行输出 `Available skills (N):`，随后每条一行 `  /<name>  <description>`（按字典序、固定列宽对齐），末行输出 `Type /<skill-name> to invoke a skill.`（验证：tmux 实跑）
- [ ] Catalog 为空时 `/skill` 输出 `No skills loaded.`（验证：清空内置 Skill 资源后启动）

## 编译与测试

- [ ] `python -m forgecode` 能正常启动（在合法配置下进入 TUI）
- [ ] `pytest` 通过（含新增的 `tests/test_skills_*.py` 与 `tests/test_command_skill*.py`）
- [ ] `ruff check .` 无新增告警
- [ ] `ruff format --check .` 通过
- [ ] （可选）`mypy src/forgecode` 通过

## 端到端场景（tmux 实跑）

> 在 tmux 内启动 forgecode，按下面流程一步步操作；每步附"观察"项。

**前置**：
- 用 `tmux new -s forgecode-ch11 -x 200 -y 50` 起一个固定大小的 tmux session
- `cd /Users/codemelo/forgecode && uv sync && python -m forgecode`

**步骤**：

1. **启动与就绪**
   - 操作：进程启动
   - 观察：banner 正常显示；状态栏底部含 "Type a message and press Enter..."；进程不抛异常；stderr 无 "skipped" 类错误（如果用户/项目目录干净）

2. **`/help`**
   - 操作：键入 `/help` 回车
   - 观察：输出含 11 条 ch10 命令（已无独立 `/review`）+ `/skill` + `/commit [skill]` + `/review [skill]` + `/test [skill]`，共 15 行

3. **`/skill`**
   - 操作：键入 `/skill` 回车
   - 观察：首行 `Available skills (3):`，随后三行 `  /commit ...` / `  /review ...` / `  /test ...`，末行 `Type /<skill-name> to invoke a skill.`

4. **显式调用 inline Skill `/commit`**
   - 操作：键入 `/commit` 回车
   - 观察：状态栏立即进入流式；AI 开始按 commit SOP 走（应该会调 git status / diff）；本步骤是真实操作，按 q/esc 可中断；目的是验证 inline 路径联通

5. **显式调用 fork Skill `/review`**
   - 操作：在主对话先随便说一句 "I just edited some files."（让主对话有上下文），然后键入 `/review`
   - 观察：状态栏进入流式；AI 输出审查报告；最后主对话新增一条 assistant 消息（含审查结果）；`fork_context=none` 意味着子 Agent 看不到 "I just edited..." 那条 user 消息

6. **意图触发 LoadSkill**
   - 操作：键入自然语言 "我想做后端面试准备"（或类似能匹配 backend-interview-like description 的 Skill；如果当前 Catalog 只有 commit/review/test，需要先放一个 user-level Skill，name=backend-interview）
   - 观察：LLM 调用 LoadSkill 工具，工具结果为 "Skill backend-interview activated..."；下一轮起 env context 中出现该 Skill 的 SOP body

7. **`/clear` 清空激活**
   - 操作：键入 `/clear` 回车
   - 观察：对话区清空、session 新建；接着说一句任意话题，env context 中不再含上一轮激活的 SOP（可通过让 Agent 复述"现在你激活了什么 Skill"间接验证，或开启 debug 日志）

8. **InstallSkill 安装第三方 Skill**
   - 操作：用 `python3 -m http.server 8080` 在本地 8080 端口托管一个写好的 `test-skill.zip`（含 `myskill/SKILL.md`），切到 forgecode 输入 "把这个 skill 装下：http://localhost:8080/test-skill.zip"
   - 观察：Agent 调 install_skill 工具；安装成功后 `/skill` 列表立即出现 myskill；`/myskill` 可调用

9. **`/clear` → 新会话不残留**
   - 操作：先激活 myskill，再 `/clear`，再 `/skill`
   - 观察：`/skill` 仍能看到 myskill（Catalog 与 Active 列表是两个概念，Catalog 不清）；env context 已无 Active Skills 块

10. **退出**
    - 操作：`/exit` 回车
    - 观察：进程优雅退出，无错误日志

## 验收报告模板

```
## 验收报告

### 通过
- [x] 实现完整性 — 全包启动：python -m forgecode 输出 ...
- [x] /help 列表正确：含 /skill, /commit [skill] ...
- [x] /skill 输出三行内置 Skill ...

### 未通过
- [ ] 第 X 项 — 预期：...，实际：...，修复方案：...

### 端到端
- [x] 启动与就绪 — 结果：banner 正常
- [x] /help — 结果：15 行命令
- [x] /skill — 结果：commit/review/test 三行
- ...（按上面 10 步逐条列出）
```