# ForgeCode Plan

## 架构概览

应用分为 5 层，自上而下：

```
┌──────────────────────────────────────┐
│  CLI 层 (main.py)                     │  ← argparse 解析 --provider
├──────────────────────────────────────┤
│  TUI 层 (tui/)                        │  ← Rich 渲染 + prompt_toolkit 输入
├──────────────────────────────────────┤
│  对话层 (conversation/)               │  ← 消息存储、历史管理
├──────────────────────────────────────┤
│  Provider 层 (providers/)             │  ← 抽象基类 + Anthropic/OpenAI 实现
├──────────────────────────────────────┤
│  配置层 (config/)                     │  ← YAML 加载、两层合并、向导
└──────────────────────────────────────┘
```

**每层职责：**

| 层 | 职责 | 对应 spec |
|----|------|-----------|
| CLI 层 | 入口，解析 `--provider` 参数，串联各层启动 TUI | F7 |
| TUI 层 | 终端界面渲染、流式打印、命令分发、输入处理 | F1, F3, F4, F9 |
| 对话层 | 维护会话消息列表，增删查 | F2 |
| Provider 层 | 统一流式对话接口，封装 Anthropic/OpenAI SDK | F5, F8, F10 |
| 配置层 | YAML 加载合并、向导、ProviderConfig 产出 | F6, F7 |

**数据流向（一次对话的完整链路）：**

```
用户输入
  → prompt_toolkit 捕获
    → TUI App 判断：/command 还是普通消息
      → 普通消息：Conversation.add_user(msg)
        → Provider.chat_stream(Conversation.messages)
          → AsyncAnthropic/AsyncOpenAI SSE 流
            → yield StreamEvent(text/thinking/error)
              → TUI 逐事件渲染到对话区域
                → 流结束后 Conversation.add_assistant(full_text)
                  → 等待下一轮输入
      → /command：TUI App 本地处理（clear/switch/exit...）
```

---

## 核心数据结构

### StreamEvent — 流式事件联合类型

Provider 层向 TUI 层传递的流式事件的抽象。所有 Provider 实现都输出统一的事件类型，TUI 层不感知具体后端。

```python
from dataclasses import dataclass

@dataclass
class TextDelta:
    """一个文本 token"""
    text: str

@dataclass
class ThinkingStart:
    """思考块开始"""
    pass

@dataclass
class ThinkingDelta:
    """一个思考 token"""
    text: str

@dataclass
class ThinkingEnd:
    """思考块结束"""
    pass

@dataclass
class ErrorEvent:
    """流式过程中的错误"""
    message: str
    retryable: bool  # True 表示可重试（网络/5xx），False 表示不可重试（4xx）

# 联合类型：一个事件是上述五种之一
StreamEvent = TextDelta | ThinkingStart | ThinkingDelta | ThinkingEnd | ErrorEvent
```

### Message — 对话消息

```python
from dataclasses import dataclass

@dataclass
class Message:
    role: str       # "user" | "assistant"
    content: str    # 消息正文
```

### ProviderConfig — 单个供应商配置

```python
from dataclasses import dataclass

@dataclass
class ProviderConfig:
    name: str           # 标识名
    protocol: str       # "anthropic" | "openai"
    model: str          # 模型名
    base_url: str       # API 地址
    api_key: str        # 认证密钥
    thinking: bool = False  # 是否启用扩展思考
```

### AppConfig — 应用完整配置

```python
from dataclasses import dataclass

@dataclass
class AppConfig:
    providers: list[ProviderConfig]
    active_provider_name: str  # 当前选中的供应商 name
```

---

## 模块设计

### 模块 A: config/ — 配置管理

**职责：** 加载 YAML 配置文件，合并全局和项目级配置，提供交互式配置向导。

**对外接口：**

| 函数/类 | 说明 |
|----------|------|
| `load_config(provider_name: str \| None) -> AppConfig` | 加载配置。先合并两层 YAML，再根据 `provider_name` 选择活动供应商（为 None 时用第一个）。配置为空时调用向导 |
| `run_wizard() -> AppConfig` | 交互式向导，优先引导创建全局配置，用户可选项目级 |

**内部函数：**

| 函数 | 说明 |
|------|------|
| `_load_yaml(path: Path) -> dict \| None` | 读取单个 YAML 文件，不存在返回 None |
| `_merge_configs(global_cfg: dict, project_cfg: dict) -> list[ProviderConfig]` | 合并两层：项目级 provider 覆盖同名全局 provider |

**依赖：** pyyaml

**对应 spec：** F6, F7

---

### 模块 B: providers/ — Provider 抽象层

**职责：** 定义统一的流式对话接口，实现 Anthropic 和 OpenAI 两个后端，提供工厂函数。

**对外接口：**

| 类/函数 | 说明 |
|---------|------|
| `BaseProvider` (ABC) | 抽象基类，定义 `chat_stream()` 接口 |
| `create_provider(config: ProviderConfig) -> BaseProvider` | 工厂函数，根据 `config.protocol` 返回对应实现 |

**BaseProvider 接口契约：**

```python
class BaseProvider(ABC):
    def __init__(self, config: ProviderConfig): ...

    @abstractmethod
    async def chat_stream(
        self, messages: list[Message]
    ) -> AsyncIterator[StreamEvent]:
        """
        接收对话历史，返回流式事件序列。

        事件顺序约定：
        - ThinkingStart → ThinkingDelta* → ThinkingEnd → TextDelta* → (流结束)
        - 如果 thinking=False 或无思考内容，直接 TextDelta*
        - 出错时 yield ErrorEvent，不抛异常
        """
        ...
```

**子类实现：**

| 类 | 依赖 | 说明 |
|----|------|------|
| `AnthropicProvider(BaseProvider)` | `AsyncAnthropic` (anthropic SDK) | 封装 `AsyncAnthropic().messages.stream()`。将 SDK 的 `text_delta` / `thinking_delta` / `content_block_start` / `content_block_stop` 事件映射为 StreamEvent。重试逻辑：捕获 `APIStatusError`（5xx）和网络异常，最多重试 1 次 |
| `OpenAIProvider(BaseProvider)` | `AsyncOpenAI` (openai SDK) | 封装 `AsyncOpenAI().chat.completions.create(stream=True)`。将 `chunk.choices[0].delta.content` 映射为 `TextDelta`。o 系列模型的 reasoning tokens 同理映射为 Thinking 事件。重试逻辑同上 |

**重试策略（两个实现共用）：**
- 重试范围：网络异常（`httpx.NetworkError` 等）+ HTTP 5xx
- 不重试：HTTP 4xx（参数错误、认证失败直接报错）
- 重试次数：1 次，无等待间隔
- 两次都失败则 yield `ErrorEvent`，不抛异常

**依赖：** `anthropic` SDK, `openai` SDK

**对应 spec：** F5, F8, F10

---

### 模块 C: conversation/ — 对话管理

**职责：** 维护当前会话的消息列表，提供增删查操作。

**对外接口：**

| 类/方法 | 说明 |
|---------|------|
| `Conversation()` | 初始化空消息列表 |
| `Conversation.add(role: str, content: str) -> None` | 追加一条消息（user 或 assistant） |
| `Conversation.clear() -> None` | 清空所有消息 |
| `Conversation.messages -> list[Message]` | 属性，返回当前所有消息（供 Provider 使用） |

**依赖：** 无外部依赖

**对应 spec：** F2

---

### 模块 D: tui/ — 终端界面

**职责：** 管理整个终端 UI 生命周期——渲染对话区域、处理用户输入、分发命令、协调流式输出。

**对外接口：**

| 类/方法 | 说明 |
|---------|------|
| `ForgeApp` | TUI 主类，持有 `Conversation`、`BaseProvider`、`AppConfig`、`RichConsole` |
| `ForgeApp.run() -> None` | 启动 TUI 事件循环，阻塞直到用户退出 |

**内部组件：**

| 类/函数 | 说明 |
|---------|------|
| `ForgeApp._handle_input(text: str) -> None` | 判断 `/` 命令还是普通消息，分发处理 |
| `ForgeApp._handle_command(cmd: str, args: str) -> None` | 命令分发：`/help` `/clear` `/exit` `/quit` `/providers` `/switch` `/thinking` |
| `ForgeApp._send_message(text: str) -> None` | 将用户消息发送给 Provider，流式渲染回复 |
| `ForgeApp._render_header() -> None` | 渲染顶部状态栏 "ForgeCode · {model}" |
| `ForgeApp._render_thinking_block(thinking_text: str) -> None` | 渲染可折叠的思考区块 |
| `ForgeApp._render_assistant_message(text: str) -> None` | 流式渲染 AI 回复 |

**Rich + prompt_toolkit 分工：**

| 工具 | 负责 |
|------|------|
| `prompt_toolkit` | 输入捕获（`PromptSession`）、↑↓ 历史、输入样式 |
| `rich.live.Live` | 动态刷新整个 TUI 布局（header + conversation + divider + input area） |
| `rich.markdown.Markdown` | 渲染 AI 回复中的 Markdown（代码块、列表等） |

**命令处理表（F9）：**

| 输入 | 处理 |
|------|------|
| `/help` | 打印可用命令列表到对话区 |
| `/clear` | 调用 `Conversation.clear()`，刷新界面 |
| `/exit`, `/quit` | 退出 `prompt_toolkit` 事件循环 |
| `/providers` | 列出 `AppConfig.providers` 中所有 name/protocol/model |
| `/switch <name>` | 查找 `ProviderConfig`，重建 `BaseProvider` 实例，更新 `active_provider_name`，刷新 header |
| `/thinking on\|off` | 切换 `ForgeApp._show_thinking` 布尔值 |

**界面布局（F1, F4）：**

```
┌─────────────────────────────────────────────┐
│  ForgeCode · claude-sonnet-4-20250514       │  ← Header (Rich Panel)
│─────────────────────────────────────────────│  ← Rule 分割线
│                                             │
│  👤 用户消息...                              │  ← 对话区
│                                             │
│  🤖 💭 思考过程（折叠）                      │  ← 思考块 (Rich collapse)
│  ────────────────────────────────────────── │
│  🤖 AI 回复内容（流式打印 + Markdown 渲染）   │
│                                             │
│─────────────────────────────────────────────│  ← Rule 分割线
│  > 用户输入...                               │  ← prompt_toolkit 输入区
└─────────────────────────────────────────────┘
```

**依赖：** `rich`, `prompt_toolkit`

**对应 spec：** F1, F3, F4, F9

---

### 模块 E: main.py — 入口

**职责：** 解析命令行参数，加载配置，创建 Provider，启动 TUI。

**命令行接口：**

```
forgecode [--provider <name>]
```

**启动流程：**

1. `argparse` 解析 `--provider`
2. `load_config(provider_name)` → `AppConfig`
3. `create_provider(active_config)` → `BaseProvider`
4. `Conversation()` → `Conversation`
5. `ForgeApp(config, provider, conversation).run()` → 进入 TUI

**对应 spec：** F7

---

## 模块交互

```
main.py
  │
  ├─→ config.load_config(provider_name)
  │     ├─ _load_yaml(~/.forgecode/forgecode.yaml)
  │     ├─ _load_yaml(./forgecode.yaml)
  │     ├─ _merge_configs(global, project)
  │     └─ [空配置时] run_wizard()
  │     → AppConfig
  │
  ├─→ providers.create_provider(active_config)
  │     └─ if protocol=="anthropic" → AnthropicProvider
  │     └─ if protocol=="openai"    → OpenAIProvider
  │     → BaseProvider
  │
  ├─→ Conversation()
  │     → Conversation (空)
  │
  └─→ ForgeApp(config, provider, conversation).run()
        │
        ├─ prompt_toolkit.PromptSession 捕获输入
        │
        ├─ 每次用户输入:
        │   ├─ 以 / 开头 → _handle_command()
        │   │   ├─ /clear   → conversation.clear()
        │   │   ├─ /switch  → create_provider(new_config)
        │   │   ├─ /exit    → 退出循环
        │   │   └─ ...
        │   │
        │   └─ 普通消息 → _send_message()
        │       ├─ conversation.add("user", text)
        │       ├─ provider.chat_stream(conversation.messages)
        │       │     → AsyncIterator[StreamEvent]
        │       ├─ 对每个 StreamEvent:
        │       │   ├─ TextDelta      → Rich 实时追加到 AI 消息
        │       │   ├─ ThinkingStart  → 创建折叠块
        │       │   ├─ ThinkingDelta  → 追加到折叠块
        │       │   ├─ ThinkingEnd    → 收起折叠块
        │       │   └─ ErrorEvent     → 显示错误提示
        │       └─ 流结束后 conversation.add("assistant", full_text)
        │
        └─ 循环直到 /exit
```

---

## 文件组织

```
forgecode/
├── docs/
│   ├── spec.md
│   ├── plan.md              ← 本文档
│   ├── task.md              ← 下一步生成
│   └── checklist.md         ← 下一步生成
├── src/
│   └── forgecode/
│       ├── __init__.py
│       ├── main.py           — 入口：argparse、启动流程编排
│       ├── config/
│       │   ├── __init__.py
│       │   ├── schema.py     — ProviderConfig、AppConfig 数据类
│       │   ├── loader.py     — load_config()、YAML 加载、两层合并
│       │   └── wizard.py     — run_wizard() 交互式配置向导
│       ├── providers/
│       │   ├── __init__.py   — StreamEvent 类型、BaseProvider ABC、create_provider()
│       │   ├── anthropic.py  — AnthropicProvider 实现
│       │   └── openai.py     — OpenAIProvider 实现
│       ├── conversation/
│       │   ├── __init__.py
│       │   └── history.py    — Message、Conversation 类
│       └── tui/
│           ├── __init__.py
│           └── app.py        — ForgeApp 主类（界面渲染、命令分发、输入处理）
├── tests/
│   ├── __init__.py
│   ├── test_config.py
│   ├── test_providers.py
│   ├── test_conversation.py
│   └── test_tui.py
├── pyproject.toml
└── README.md
```

---

## 技术决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 异步框架 | `asyncio`（标准库），无额外框架 | Python 3.11+ 的 `asyncio` 已足够成熟，无需 FastAPI/aiohttp 等 Web 框架。Provider SDK 原生支持 async |
| TUI 渲染方案 | Rich `Live` + prompt_toolkit `PromptSession` | Rich Live 提供动态刷新能力，支持局部更新（不重刷整个屏幕）。prompt_toolkit 提供生产级输入处理（历史、补全、多行） |
| 流式事件模型 | 5 种 StreamEvent（TextDelta / ThinkingStart / ThinkingDelta / ThinkingEnd / ErrorEvent） | 将 Anthropic 和 OpenAI 各自的事件体系统一映射为有限的事件类型，TUI 层不感知具体后端。ThinkingStart/End 让 TUI 层知道何时创建/折叠思考块 |
| 重试策略实现 | 在 Provider 子类内部各自实现 | Anthropic 和 OpenAI SDK 的异常类型不同（`anthropic.APIStatusError` vs `openai.APIStatusError`），统一重试逻辑反而增加耦合。约定行为一致（1 次重试，5xx/网络），各自实现 |
| 配置合并策略 | 按 name 字段覆盖：项目级同名 provider 完全替换全局级 | 简单直观，用户不需要理解复杂的深度合并规则。想覆盖全局某个 provider 就用相同 name |
| 配置向导位置 | 提示 "创建全局配置？[Y/n]"，选 n 则创建项目级 | 优先全局方便用户跨项目复用，同时给用户选择权 |
| OpenAI thinking 处理 | o 系列模型的 `reasoning_tokens` 映射为 ThinkingDelta | 与 Anthropic Extended Thinking 统一为同一种展示方式，Provider 层屏蔽差异 |
| 思考块折叠实现 | Rich `Text` + 标记，默认不展开。TUI 内部维护折叠状态 | Rich 不原生支持折叠组件，用状态管理 + 条件渲染实现。简单可靠 |
| 输入处理 | prompt_toolkit `PromptSession` 底部固定输入行 | 单行模式简洁，符合 Claude Code 交互习惯。prompt_toolkit 原生支持 ↑↓ 历史 |
| 命令前缀 | `/` | 与 Claude Code、Slack 等工具一致，用户无需额外学习 |
| Markdown 渲染 | Rich `Markdown` 组件 | Rich 内置 Markdown 渲染，支持代码高亮、表格、列表。不需要额外引入渲染库 |
