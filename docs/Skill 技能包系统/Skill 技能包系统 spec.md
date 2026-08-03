# Skill 技能包系统 Spec## 背景

ch10 给 forgecode 装上了 Slash Command 注册中心和 12 条内置命令，其中 `/review` 是 KindPrompt 类型——把硬编码在源码里的代码审查 prompt 注入对话并触发 LLM。这种"写死在源码里"的 prompt 暴露出几个问题：

- 调整 prompt 必须重新安装包/重启，用户没办法在不动源码的前提下定制
- 只有开发者能新增 prompt 类命令，普通用户无法贡献
- prompt 命令拿到的工具集与普通对话完全一致，没法在执行 SOP 时收窄注意力或限制权限
- prompt 是孤零零的字符串，无法捎带专属工具、参考资料、辅助脚本

与此同时,forgecode 接入 MCP 之后工具数量从 6 个膨胀到二十多个,模型选错工具的概率随之上升,需要一种机制把"完成某类任务时只看哪些工具"的范围收窄。

Skill 技能包系统在 ch10 命令体系之上解决这两个问题：把可复用的 AI 操作搬出源码、放进可编辑的 Markdown 文件；通过两阶段加载和工具白名单把每次任务的注意力收窄到最小工具子集。

## 目标- **G1**：让可复用的 AI 操作变成独立的 Markdown 文件（每个 Skill 一个目录），增/删/改一个 Skill 不需要重装 forgecode 包
- **G2**：自动把已加载的 Skill 注册成 `/<name>` 形式的 Slash Command，沿用 ch10 的 KindPrompt 分支
- **G3**：实现两阶段加载——启动时只把 Skill 的 `name + description` 注入系统提示；Agent 通过 LoadSkill 工具按需把完整 SOP 钉到环境上下文，从而让 Agent 既能被显式命令调用，也能通过自然语言意图自动触发
- **G4**：实现两种执行模式：`inline`（默认，注入主对话）与 `fork`（在 Python 端起子 Agent，跑完返回 final_text 作为 assistant 消息回流主对话），覆盖"需要继承上下文"和"需要客观隔离"两类任务
- **G5**：通过 `allowed_tools` 工具白名单做 fail-fast 依赖检查与 SOP 顶部"建议工具"提示，提高模型工具选择准确率
- **G6**：支持目录型 Skill：`SKILL.md` + 可选 `tool.json`（声明专属工具，调用时通过 `asyncio.create_subprocess_exec` 起 `references/` 下的可执行脚本）+ `references/`，整套作为自包含能力包
- **G7**：内置 `commit`、`review`、`test` 三个 Skill 通过 `importlib.resources` 随包分发；同时提供 `InstallSkill` 内置工具从 URL/zip 拉取第三方 Skill 到 `~/.forgecode/skills/`
- **G8**：`/clear` 时清空已激活 Skill 列表，保证新会话从干净状态开始

## 功能需求### Skill 定义与解析- **F1**：每个 Skill 是一个目录。目录内必须含一个 `SKILL.md` 文件；其它附属物（`tool.json`、`references/` 子目录）均为可选
- **F2**：`SKILL.md` 由 YAML frontmatter（被两行 `---` 包围）+ Markdown 正文构成。Frontmatter 必填字段为 `name`、`description`；可选字段为 `allowed_tools`、`mode`、`fork_context`、`model`
- **F3**：`name` 必须满足正则 `^[a-z][a-z0-9-]*$`，长度 1-32；`name` 同时作为 Slash Command 命令名
- **F4**：`description` 为一句话描述（建议 ≤120 字符），用于 system prompt 第一阶段注入与 `/help`、`/skill` 输出
- **F5**：`allowed_tools` 为字符串数组；缺省视为空（不限制）
- **F6**：`mode` 取值为 `inline` 或 `fork`；缺省视为 `inline`，未知值按 `inline` 处理并 warning
- **F7**：`fork_context` 取值为 `none` / `recent` / `full`；缺省视为 `none`；仅在 `mode: fork` 时生效，inline 模式下忽略
- **F8**：`model` 为可选字符串，覆盖该 Skill 执行时使用的 LLM 模型；缺省沿用主对话当前模型
- **F9**：Markdown 正文中的 `$ARGUMENTS` 占位符在执行期替换为用户传入的参数文本；如未包含该占位符且参数非空，则在正文末尾以 `\n\n## User Request\n\n<args>` 形式追加；参数为空时按空字符串处理
- **F10**：目录可包含 `tool.json` 文件，描述该 Skill 专属工具数组。每个工具元素包含 `name`（与 frontmatter `allowed_tools` 一致的命名规则）、`description`、`input_schema`（标准 function calling JSON Schema）、`command`（数组：argv 形式，首元素为相对 `references/` 的可执行文件路径或绝对路径）
- **F11**：单个 Skill 解析失败时跳过该 Skill 并打 warning，不阻断其它 Skill 加载

### Skill 加载器（Catalog）- **F12**：启动期按以下顺序扫描，每个位置下的"子目录"视为一个 Skill 候选：
  1. 内置 Skill（通过 `importlib.resources` 从 `forgecode.skills.builtin` 包资源读取 `<name>/SKILL.md`）
  2. 用户级：`~/.forgecode/skills/<name>/`
  3. 项目级：`<project_root>/.forgecode/skills/<name>/`
- **F13**：同名覆盖按上述顺序依次进行——后扫描的同名 Skill 替换前者。最终优先级为：项目级 > 用户级 > 内置
- **F14**：扫描目录不存在时静默跳过；无 `SKILL.md` 的子目录跳过且打 warning
- **F15**：加载阶段对所有 Skill 的 `allowed_tools` 做 fail-fast 依赖检查——引用的工具名必须存在于主工具注册中心（含 MCP 注入的工具，及 Skill 自己 `tool.json` 注册进来的专属工具）；任一未找到则在启动 banner 后立即打印 error 并跳过该 Skill 加载
- **F16**：Skill 的 `name` 与 ch10 已有内置 Slash Command 命令名（含别名）冲突时，跳过加载该 Skill 并打 warning（理由：内置命令保护）
- **F17**：Catalog 提供 `reload(work_dir)` 方法用于重新扫描三层路径，重新注册所有 Skill 命令；现有命令注册中心提供 `remove_skill_commands()` 入口让 reload 清掉旧的 skill 类命令再重新注册

### Slash Command 自动注册- **F18**：每个加载成功的 Skill 在 ch10 命令注册中心注册一条 `KindPrompt` 命令：
  - 命令名 = Skill 的 `name`
  - 描述 = Skill 的 `description` 末尾追加 `[skill]` 标记
  - 别名为空
  - hidden = False
- **F19**：用户输入 `/<name>` 等价于显式调用该 Skill（不带参数）；命令 handler 负责调用 Skill 执行器并按执行模式注入对话或起子 Agent
- **F20**：Skill 命令支持 ch10 的自动补全菜单，与内置命令共享同一前缀匹配逻辑

### 两阶段加载与 LoadSkill- **F21**：Prompt 模块新增一段 `skills-catalog`（priority 介于现有 long-term-memory 与 environment 之间），内容为：
  ```
  ## Available Skills

  - <name>: <description>
  - <name>: <description>
  ...

  Call the LoadSkill tool with {"name": "<skill_name>"} to activate a skill's full SOP and specialized tools before executing it.
  ```
  Catalog 为空时该模块为空字符串，被 prompt assembler 跳过
- **F22**：环境上下文新增一段 `active-skills` 区块，按激活顺序拼接每个已激活 Skill 的 `SKILL.md` 正文（前置一行 `### Skill: <name>` 标题），每轮 Agent loop 重建 env context 时重新装配
- **F23**：注册一个新的内置工具 `LoadSkill`：
  - 输入参数：`{"name": "string"}`
  - 行为：从 Catalog 取 Skill；从磁盘重新读取 `SKILL.md` 拿到最新 body；调用 Agent 提供的 `activate_skill(name, body)` 把 Skill 钉到 Active 列表；若该 Skill 有 `tool.json`，把其中的专属工具登记进主工具注册中心（重复登记的工具名静默覆盖）
  - 返回：`Skill <name> activated. SOP pinned to env context. <N> specialized tools registered.`
  - 标记为 read-only（不被权限系统拦截），并在工具过滤逻辑中标记为系统工具（永远可见，不受 allowed_tools 约束）
- **F24**：Agent 侧新增 `ActiveSkills` 列表（基于 SessionRuntime），提供 `activate_skill(name, body)`、`clear_active_skills()`、`list_active()` 方法
- **F25**：`/clear` 命令在新建会话前调用 `Agent.clear_active_skills()`，确保下一会话的 env context 不再含上一对话激活的 SOP

### Skill 执行器- **F26**：Skill 执行器入口 `execute(ctx, name, args)`（async 方法）：从 Catalog 取定义；从磁盘重读最新 `SKILL.md`（重读失败回退缓存版本并打 warning）；按 `mode` 走两条分支
- **F27**：`inline` 分支：完成 `$ARGUMENTS` 替换；在正文顶部前插一段"建议工具"提示行（当 `allowed_tools` 非空时）；通过 `UI.inject_and_send` 把最终文本作为 user 消息注入主对话并触发回合
- **F28**：`fork` 分支：完成 `$ARGUMENTS` 替换；按 `fork_context` 构造子 Agent 的初始 Conversation（`none`：仅一条 user 消息为 Skill 文本；`recent`：复制主对话末尾最近 5 条消息再追加 Skill 文本；`full`：先用主对话历史调一次 LLM 摘要，再把摘要 + Skill 文本作为初始 user 消息）；按 Skill 的 `model`（若指定）切 provider；按 `allowed_tools` 过滤工具集（LoadSkill 系统工具豁免）；新起子 Agent 跑一轮 `run()` 拿到 final_text；把 final_text 作为一条 assistant 消息插入主对话历史
- **F29**：fork 分支跑完后主对话沿用主 Agent 继续，不影响主对话的运行时模式/Conversation 长度估算外的其它状态

### InstallSkill 内置工具- **F30**：注册内置工具 `InstallSkill`，输入参数：`{"source": "string"}`。`source` 支持两种形式：
  - HTTP(S) URL 指向单个 `.zip` 文件（按 zip 解压）
  - HTTP(S) URL 指向"目录索引"（页面包含可下载文件列表，本期仅识别 .zip）
- **F31**：InstallSkill 解压目标固定为 `~/.forgecode/skills/`。zip 内顶层目录名即为 Skill 名，需满足 F3 命名规范；不满足或 zip 结构非法则报错
- **F32**：InstallSkill 安装成功后调用 `Catalog.reload`，自动让新 Skill 的 `/<name>` 命令与 system prompt 第一阶段列表立即可见
- **F33**：InstallSkill 不是系统工具，受权限模式约束（具有外部副作用——写磁盘/网络请求），需要走 ch08 权限系统的用户授权

### /skill 命令- **F34**：注册新的内置 Slash Command `/skill`，KindLocal，零参数：输出已加载 Skill 的精简列表——首行 `Available skills (N):`，随后每条一行 `  /name  description`（按字典序、固定列宽对齐），末行追加 `Type /<skill-name> to invoke a skill.` 引导。来源（builtin/user/project）与模式（inline/fork）等元信息本期不在 `/skill` 输出中展示，开发者需要时直接读 SKILL.md
- **F35**：Catalog 为空时输出一行提示 `No skills loaded.`

## 非功能需求- **N1**：Skill 加载、命令注册全部在 forgecode 启动期完成；启动期任何 fail-fast 错误（命名冲突、依赖工具缺失、zip 解压失败之外的解析错误）必须把错误消息打到 stderr 后继续启动但跳过出错 Skill，不阻断 forgecode 进程
- **N2**：第一阶段 system prompt 注入的 Skill 列表落在 prompt cache 的稳定前缀区（与 ch07 prompt cache 设计一致），Skill 数量 ≤30 时单轮 cache 命中开销可忽略
- **N3**：第二阶段 active-skills 块每轮重新装配 env context，不通过 user 消息历史维持 SOP 可见性
- **N4**：LoadSkill 是 read-only + 系统工具，跨任意 allowed_tools 白名单都可见；权限系统不拦截
- **N5**：Skill 执行时的 `SKILL.md` 重读路径必须容错——磁盘读失败回退到内存缓存的上一版本并打 warning，不让一次磁盘错误中断已激活的 Skill
- **N6**：fork 模式起子 Agent 跑完后必须把子 Agent 的 token 用量计入主对话的 `SessionRuntime.usage_anchor`，使后续上下文压缩仍能感知到 fork 烧掉的 token
- **N7**：fork 模式子 Agent 异常退出（超时、`CancelledError`、LLM 错）时返回主对话的 assistant 消息为 `[skill <name> failed: <reason>]`，不让主对话卡死
- **N8**：InstallSkill 解压前严格校验 zip 内路径（拒绝 `..`、绝对路径、符号链接），防止 zip-slip
- **N9**：`/clear` 清空 Active Skills 的动作发生在新建 session writer 前，确保新会话首条 env context 已剔除旧 SOP
- **N10**：所有 Skill 文件路径、URL、name 等用户输入在错误信息中保持原样回显，便于排查
- **N11**：UI 抽象层新增 `activate_skill / clear_active_skills / list_active_skills / list_catalog_skills` 等查询/修改方法，与 ch10 已有 UI 接口风格一致；NopUI 对所有新方法提供零值实现
- **N12**：`tool.json` 的专属工具 exec 时使用 30 秒固定超时（与现有 bash 工具一致），stdin 传入 JSON 序列化后的工具调用参数，stdout 作为 tool_result 文本回传；returncode 非 0 视为工具失败

## 不做的事

- 不做 Skill 市场分发与版本管理（不实现 `skill.lock`、不做语义化版本依赖）
- 不做 Skill 沙箱隔离（专属工具 exec 直接信任本地脚本，不做 chroot/namespace）
- 不做 Skill 间显式 `can_delegate_to` 类型约束；嵌套调用通过 LoadSkill 系统工具自然实现
- 不做 fork 模式的"参考资料附件传递"——子 Agent 不预读 `references/` 下任何文件，由 SOP 自行通过 ReadFile 取
- 不修改 ch10 状态栏、自动补全菜单的视觉行为
- 不修改 ch10 已有 11 条内置命令的外部行为（除删除 `/review`）
- 不支持 SKILL.md 之外的格式（不接受 `skill.yaml` 单独定义元数据）
- 不支持单文件 Skill（必须是目录形态，方便后续扩展 tool.json 与 references/）
- 不做 Skill 启用/禁用开关命令（要禁用就直接删目录）
- 不在 TUI 里渲染 Skill 详情面板（`/skill` 仅文本输出列表）
- 不为 Skill 提供独立日志文件（与主进程共享 stderr）

## 验收标准- **AC1**：项目根目录与用户目录下都未放 Skill 时，启动 forgecode 显示三个内置 Skill：`commit / review / test`；`/skill` 首行输出 `Available skills (3):`，随后三行 `  /<name>  <description>`，末行 `Type /<skill-name> to invoke a skill.`
- **AC2**：内置 `/review` 已从 ch10 命令注册中心移除；启动后 `/help` 不再单独列出 `/review` 而是出现 `/review [skill]`
- **AC3**：用户键入 `/review` 回车，触发 fork 模式 Skill；状态栏进入流式态、AI 输出审查报告后回流到主对话；主对话历史新增一条 assistant 消息（用户角度看不出是 fork）
- **AC4**：用户键入 `/commit` 回车，触发 inline 模式 Skill；主对话注入一条 user 消息（含 commit SOP 文本），LLM 按 SOP 调用 git status / diff / add / commit
- **AC5**：用户键入 `/test` 回车，触发 inline 模式 Skill；主对话注入测试相关的 SOP，LLM 按 SOP 检测项目类型并跑测试
- **AC6**：用户键入"帮我做个后端面试准备"等自然语言；当存在意图匹配的 Skill 时，LLM 主动调用 LoadSkill 工具激活它；下一轮 env context 中能看到该 Skill 的 SOP 钉在 active-skills 块
- **AC7**：LoadSkill 在权限模式为 PlanMode 下也可调用（read-only 标记生效，不被拦截）
- **AC8**：键入 `/clear`，新会话开始后 env context 的 active-skills 块为空，已激活 Skill 全部清掉
- **AC9**：在 `~/.forgecode/skills/` 与 `<work_dir>/.forgecode/skills/` 都放一个 `name: commit` 的 Skill，启动后 `/skill` 中 commit 一行的 description 取自项目级目录的版本（用户级被覆盖；source 信息不在 `/skill` 输出中展示，可通过描述差异区分）
- **AC10**：在 `<work_dir>/.forgecode/skills/foo/SKILL.md` 中声明 `allowed_tools: [NotExist]`，启动时 stderr 打印 `skill foo: allowed_tool "NotExist" not registered, skipped`，进程继续启动，`/skill` 中不出现 foo
- **AC11**：在某 Skill 目录添加合法 `tool.json` 声明一个 `parse_resume` 工具（command 指向 references/parse_resume.sh，echo "ok"）；执行 LoadSkill 该 Skill 后，主工具注册中心新增 `parse_resume` 工具且 LLM 可调用并得到 `ok` 输出
- **AC12**：使用 LoadSkill 工具调用一个 `name: foo` 但 Catalog 中不存在的 Skill 时，tool_result 返回 `unknown skill: foo`，主对话不被中断
- **AC13**：InstallSkill 工具接受一个 zip URL（本地起 http server 模拟），下载并解压到 `~/.forgecode/skills/<name>/`；解压完成后 `/skill` 列表立即包含该 Skill，无需重启
- **AC14**：在受 PlanMode 限制时调用 InstallSkill 工具，被权限系统拦截，提示需要切回默认模式
- **AC15**：恶意 zip 内含 `../../etc/passwd` 路径条目时，InstallSkill 拒绝解压并返回 `unsafe path in zip` 错误
- **AC16**：fork 模式跑完后 SessionRuntime 的 token 锚点已计入子 Agent 用量（用 `/status` 观察累计 token in/out 比 fork 前增加）
- **AC17**：在 tmux 内启动 forgecode，依次执行 `/skill → /commit → /review → /test → 自然语言触发 LoadSkill → /clear → /skill`，全程不卡顿、无异常（端到端场景见 checklist）