# ForgeCode Spec

## 背景
从零开发一个命令行 AI 编程助手（Coding Agent），名为 ForgeCode，定位类似 Claude Code。第一阶段的 MVP 目标是实现一个基于终端的交互式对话界面（TUI），支持多轮对话和流式输出。

## 目标
- 用户在终端启动 ForgeCode 后进入交互式对话界面
- 用户输入问题，ForgeCode 调用大模型 API，流式地将回复逐字打印出来
- 支持多轮对话，AI 能记住之前说过的话（上下文管理留到后续记忆模块）
- 支持 Anthropic Claude 和 OpenAI 两种 API 后端，通过配置文件切换
- Provider 层抽象为统一接口，方便后续扩展新的后端

---

## 功能需求

### F1: 交互式对话界面（TUI）
用户启动 `forgecode` 后进入全功能终端界面，自上而下包含五个区域：

**(a) 启动横幅**：ASCII 小狗图案 + 应用名与版本号 + 当前工作目录
**(b) 就绪提示**：一行提示信息（如 "就绪 - 输入消息开始对话"）
**(c) 对话区**：依时间顺序展示历次用户输入与助手回复，流式渲染 AI 回复
**(d) 底部输入框**：带边框的输入框，含 `❯` 提示符与占位文字 `"Send a message..."`
**(e) 底部状态栏**：左侧显示活动 provider 的名称，右侧显示其模型名

界面示意：
```
┌─────────────────────────────────────────────────┐
│   /\___/\                                       │
│  (  o o  )    ForgeCode v0.1.0                  │
│  (  =^=  )    /home/user/project                │
│   (______)                                      │
│─────────────────────────────────────────────────│
│  就绪 - 输入消息开始对话，/help 查看命令            │
│─────────────────────────────────────────────────│
│                                                 │
│  👤 你好                                         │
│                                                 │
│  🤖 你好！有什么我可以帮助你的吗？                 │
│     （流式逐字输出）                              │
│                                                 │
│─────────────────────────────────────────────────│
│ ┌─────────────────────────────────────────────┐ │
│ │ ❯ Send a message...                         │ │
│ └─────────────────────────────────────────────┘ │
│ my-deepseek                      deepseek-v4-pro │
└─────────────────────────────────────────────────┘
```

输入框支持多行输入（Alt+Enter 换行）和历史记录（↑↓ 键）。

### F2: 多轮对话
用户和 AI 的对话历史在整个会话期间保留在上下文中。每一轮对话包含用户消息和 AI 回复，发送给 API 时附带完整历史。会话内通过 `/clear` 命令清空对话历史。

> 注：上下文的长期记忆、自动摘要和截断策略留到后续记忆模块处理，本阶段不做。

### F3: 流式输出
调用大模型 API 时使用 SSE（Server-Sent Events）方式接收流式响应。AI 回复的内容（文本部分）逐 token 实时打印到对话区域，不等全部生成完毕后再展示。流式输出保持打字机效果，每收到一个 token 立即追加到对话区域对应的 AI 消息中。

### F4: 扩展思考展示
当供应商配置中 `thinking: true` 时，Claude 的 Extended Thinking 内容展示给用户。思考内容以可折叠的区块呈现，默认折叠，展示标题如 "💭 思考过程"，用户可展开查看完整推理内容。折叠状态下不干扰用户阅读最终回复。OpenAI 的推理内容（如 o 系列模型）同理。

展示效果：
```
  🤖 💭 思考过程（点击展开）
     ──────────────────────────
     最终回复内容...
```

### F5: 双 API 后端支持
支持 Anthropic Claude API 和 OpenAI API 两种后端，用户可通过配置文件中的 `protocol` 字段指定使用哪种协议。`protocol` 可选值为 `anthropic` 或 `openai`。

### F6: YAML 配置文件
配置文件为 `forgecode.yaml`，支持全局（`~/.forgecode/forgecode.yaml`）和项目级（当前工作目录）两层。两层配置合并时，项目级覆盖全局级。配置文件使用 YAML 格式，结构为一个供应商列表，每个供应商包含以下字段：

| 字段 | 类型 | 必需 | 说明 |
|------|------|------|------|
| name | string | 是 | 供应商标识名，用于 `--provider` 参数引用 |
| protocol | string | 是 | 协议类型，`anthropic` 或 `openai` |
| model | string | 是 | 模型名称 |
| base_url | string | 是 | API 请求地址 |
| api_key | string | 是 | 认证密钥 |
| thinking | bool | 否 | 是否启用扩展思考，默认 false |

配置文件示例：
```yaml
providers:
  - name: my-claude
    protocol: anthropic
    model: claude-sonnet-4-20250514
    base_url: https://api.anthropic.com
    api_key: sk-ant-xxx
    thinking: true
  - name: my-openai
    protocol: openai
    model: gpt-4o
    base_url: https://api.openai.com/v1
    api_key: sk-xxx
```

### F7: 供应商选择
用户启动时可通过 `--provider <name>` 指定使用配置文件中哪个供应商。如果不指定，默认使用配置列表中的第一个。如果整个 `forgecode.yaml` 不存在或供应商列表为空，启动时通过交互式向导引导用户创建首个配置——优先引导在全局路径（`~/.forgecode/`）创建，用户可选择改为在项目目录创建。向导创建完成后自动将其设为当前会话的供应商。

### F8: 失败重试
API 调用失败时自动重试一次。重试只针对网络错误和可重试的服务端错误（5xx），4xx 错误（如认证失败、参数错误）不重试。重试之间无等待间隔。

### F9: 命令系统
支持以下内置命令（以 `/` 开头）：

| 命令 | 功能 |
|------|------|
| `/help` | 显示帮助信息（可用命令列表） |
| `/clear` | 清空当前会话的对话历史 |
| `/exit` 或 `/quit` | 退出程序 |
| `/providers` | 列出所有已配置的供应商 |
| `/switch <name>` | 切换到指定供应商（当前会话生效） |
| `/thinking on\|off` | 切换思考内容展示开关（当前会话生效） |

### F10: Provider 抽象层
通过抽象基类定义 Provider 接口规范，新增后端只需继承基类并实现约定方法。不依赖专用注册机制或装饰器，由工厂函数根据 `protocol` 字段选择具体实现。

---

## 非功能需求

### N1: 语言与运行时
Python 3.11+，使用 uv 管理依赖。

### N2: 外部依赖
- `openai` 官方 Python 库（使用 `AsyncOpenAI`）
- `anthropic` 官方 Python SDK（使用 `AsyncAnthropic`）
- `rich`（终端美化渲染）
- `prompt_toolkit`（输入处理、历史、自动补全）
- `pyyaml`（YAML 解析）

### N3: 安装与启动方式
通过 uv 管理项目和依赖。项目提供 `pyproject.toml`，用户可通过 `uv run forgecode` 或 `uv tool install` 后直接运行 `forgecode`。

### N4: 代码风格
- 所有 API 调用使用异步（`async/await`）
- 类型注解完整（通过 mypy 严格模式检查）
- 使用 Ruff 做 lint 和格式化

### N5: 跨平台
支持 Windows、macOS、Linux。

### N6: 性能
流式响应延迟不超过首 token 100ms + 网络延迟。界面刷新不卡顿。

---

## 不做的事
- 不做 Tool Use / Function Calling（留给后续 agent 模块）
- 不做文件操作和代码编辑（留给后续 agent 模块）
- 不做上下文自动截断或摘要（留给后续记忆模块）
- 不做 MCP（Model Context Protocol）集成
- 不做会话持久化（关闭程序后对话历史不保存）
- 不做多行输入的语法高亮
- 不做插件系统

---

## 验收标准

- AC1: 执行 `forgecode --provider my-claude` 后进入 TUI，界面顶部显示 "ForgeCode · claude-sonnet-4-20250514"
- AC2: 在 TUI 中输入 "你好"，Claude API 返回的回复逐字流式打印在对话区域
- AC3: 连续进行 3 轮对话，第 3 轮 AI 的回复能结合第 1 轮的内容回答（证明上下文被保留）
- AC4: 输入 `/clear` 后第 4 轮对话不再知道前 3 轮内容
- AC5: 用 `--provider` 切换到 OpenAI 供应商后，能正常对话
- AC6: 配置中 `thinking: true` 时，回复前显示可折叠的 "💭 思考过程" 区块
- AC7: 断开网络发起对话，API 调用失败后自动重试一次，然后显示错误提示而非崩溃
- AC8: 配置文件为空或不存在时，启动弹出向导引导创建初始配置
- AC9: 输入 `/exit` 后程序正常退出
- AC10: 在输入区域按 ↑ 键能调出上一条输入历史
- AC11: 不指定 `--provider` 时使用配置文件中的第一个供应商
