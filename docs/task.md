# ForgeCode Tasks

## 文件清单

| 操作 | 文件 | 职责 |
|------|------|------|
| 新建 | `pyproject.toml` | 项目配置、依赖声明、入口脚本 |
| 新建 | `src/forgecode/__init__.py` | 包标记 |
| 新建 | `src/forgecode/config/__init__.py` | 包标记 |
| 新建 | `src/forgecode/config/schema.py` | `ProviderConfig`、`AppConfig` 数据类 |
| 新建 | `src/forgecode/config/loader.py` | YAML 加载、两层合并、`load_config()` |
| 新建 | `src/forgecode/config/wizard.py` | `run_wizard()` 交互式向导 |
| 新建 | `src/forgecode/providers/__init__.py` | `StreamEvent` 类型、`BaseProvider` ABC、`create_provider()` |
| 新建 | `src/forgecode/providers/anthropic.py` | `AnthropicProvider` 实现 |
| 新建 | `src/forgecode/providers/openai.py` | `OpenAIProvider` 实现 |
| 新建 | `src/forgecode/conversation/__init__.py` | 包标记 |
| 新建 | `src/forgecode/conversation/history.py` | `Message`、`Conversation` 类 |
| 新建 | `src/forgecode/tui/__init__.py` | 包标记 |
| 新建 | `src/forgecode/tui/app.py` | `ForgeApp` TUI 主类 |
| 新建 | `src/forgecode/main.py` | 入口：argparse、启动流程编排 |
| 新建 | `tests/__init__.py` | 测试包标记 |
| 新建 | `tests/test_config.py` | 配置模块测试 |
| 新建 | `tests/test_providers.py` | Provider 测试 |
| 新建 | `tests/test_conversation.py` | Conversation 测试 |

---

## T1: 项目脚手架搭建

**文件：** `pyproject.toml`、6 个 `__init__.py`、`tests/__init__.py`
**依赖：** 无

**步骤：**
1. 创建目录结构：
   ```
   src/forgecode/config/
   src/forgecode/providers/
   src/forgecode/conversation/
   src/forgecode/tui/
   tests/
   ```
2. 创建 6 个 `__init__.py`（src/forgecode、config、providers、conversation、tui、tests），全部为空
3. 编写 `pyproject.toml`：
   - name = "forgecode"
   - requires-python = ">=3.11"
   - dependencies：`openai`、`anthropic`、`rich`、`prompt-toolkit`、`pyyaml`
   - dev-dependencies：`ruff`、`mypy`、`pytest`、`pytest-asyncio`
   - [project.scripts] forgecode = "forgecode.main:main"
   - [tool.ruff] 基本配置
   - [tool.mypy] strict = true
4. 创建空的 `tests/__init__.py`

**验证：** `uv run python -c "import forgecode"` 不报错；`uv run ruff check .` 无报错

---

## T2: 配置数据结构

**文件：** `src/forgecode/config/schema.py`
**依赖：** T1

**步骤：**
1. 定义 `ProviderConfig` dataclass：
   - `name: str`
   - `protocol: str`
   - `model: str`
   - `base_url: str`
   - `api_key: str`
   - `thinking: bool = False`
2. 定义 `AppConfig` dataclass：
   - `providers: list[ProviderConfig]`
   - `active_provider_name: str`

**验证：** `uv run python -c "from forgecode.config.schema import ProviderConfig, AppConfig; c = ProviderConfig(name='t', protocol='anthropic', model='m', base_url='b', api_key='k'); print(c)"` 输出正常

---

## T3: 对话管理

**文件：** `src/forgecode/conversation/history.py`
**依赖：** T1

**步骤：**
1. 定义 `Message` dataclass：
   - `role: str`（"user" | "assistant"）
   - `content: str`
2. 定义 `Conversation` 类：
   - `__init__`：初始化空 `_messages: list[Message]`
   - `add(role: str, content: str) -> None`：追加 `Message(role, content)`
   - `clear() -> None`：清空 `_messages`
   - `messages` 属性（`@property`）：返回 `list[Message]` 的副本（防止外部修改）

**验证：**
```python
from forgecode.conversation.history import Conversation, Message
c = Conversation()
c.add("user", "hello")
c.add("assistant", "hi there")
assert len(c.messages) == 2
assert c.messages[0].role == "user"
c.clear()
assert len(c.messages) == 0
```

---

## T4: Provider 抽象层

**文件：** `src/forgecode/providers/__init__.py`
**依赖：** T1, T2

**步骤：**
1. 定义 `StreamEvent` 的 5 个 dataclass：
   - `TextDelta(text: str)`
   - `ThinkingStart()`（空类）
   - `ThinkingDelta(text: str)`
   - `ThinkingEnd()`（空类）
   - `ErrorEvent(message: str, retryable: bool)`
2. 定义联合类型别名：`StreamEvent = TextDelta | ThinkingStart | ThinkingDelta | ThinkingEnd | ErrorEvent`
3. 定义 `BaseProvider` 抽象基类：
   - `__init__(self, config: ProviderConfig)`：保存 `self.config`
   - `@abstractmethod async def chat_stream(self, messages: list[Message]) -> AsyncIterator[StreamEvent]`
4. 定义 `create_provider(config: ProviderConfig) -> BaseProvider` 工厂函数：
   - 根据 `config.protocol` 返回对应实现
   - 使用字符串 import（`importlib.import_module` 延迟加载），避免循环依赖
   - 不支持的 protocol 抛出 `ValueError`

**验证：** `uv run python -c "from forgecode.providers import TextDelta, ThinkingStart, ThinkingDelta, ThinkingEnd, ErrorEvent, BaseProvider; print('OK')"` 正常执行

---

## T5: 配置加载器

**文件：** `src/forgecode/config/loader.py`
**依赖：** T2

**步骤：**
1. 实现 `_global_config_path() -> Path`：返回 `~/.forgecode/forgecode.yaml`
2. 实现 `_project_config_path() -> Path`：返回 `Path.cwd() / "forgecode.yaml"`
3. 实现 `_load_yaml(path: Path) -> dict | None`：
   - 文件不存在返回 `None`
   - 用 `yaml.safe_load()` 解析，语法错误抛出 `ValueError`
4. 实现 `_parse_providers(data: dict) -> list[ProviderConfig]`：
   - 从 `data["providers"]` 列表解析为 `ProviderConfig` 对象
   - 校验必填字段，缺失时抛出 `ValueError`
5. 实现 `_merge_configs(global_data: dict | None, project_data: dict | None) -> list[ProviderConfig]`：
   - 加载全局和项目级 YAML → 解析为 ProviderConfig 列表
   - 按 name 字段合并：项目级 provider 替换全局同名 provider
   - 若两层均为 None/空 → 返回空列表
6. 实现 `load_config(provider_name: str | None = None) -> AppConfig`：
   - 调用 `_merge_configs()` 得到 providers 列表
   - 若列表为空 → 委托给 `wizard.run_wizard()`（导入延迟到调用时）
   - 根据 `provider_name` 选择活动供应商（为 None 选第一个）
   - 若 `provider_name` 未找到 → 抛出 `ValueError`
   - 返回 `AppConfig(providers=..., active_provider_name=...)`

**验证：** 创建临时 YAML 文件测试合并逻辑，确保同名覆盖、不同名合并、空配置返回空列表

---

## T6: 配置向导

**文件：** `src/forgecode/config/wizard.py`
**依赖：** T5

**步骤：**
1. 实现 `run_wizard() -> AppConfig`：
   - 打印欢迎信息："未找到 forgecode.yaml，让我们来创建一个配置"
   - 询问 "创建全局配置 (~/.forgecode/forgecode.yaml)？[Y/n]"（默认 Y，直接回车为 Y）
   - 若选 Y：目标路径为 `~/.forgecode/forgecode.yaml`，创建 `~/.forgecode/` 目录（`exist_ok=True`）
   - 若选 n：目标路径为 `./forgecode.yaml`
   - 逐字段询问（每题提供 prompt，接受用户输入）：
     1. 供应商名称 (name)
     2. 协议类型 (protocol)："anthropic 或 openai？"
     3. 模型名称 (model)
     4. API 地址 (base_url)：提供默认值（anthropic: `https://api.anthropic.com`，openai: `https://api.openai.com/v1`）
     5. API Key (api_key)：不回显（`getpass`）
     6. 启用扩展思考？(thinking)：Y/n，默认 n
   - 将配置写入目标路径的 YAML 文件
   - 返回 `AppConfig(providers=[新创建的], active_provider_name=name)`
   - 告知用户配置文件保存位置

**验证：** 模拟交互式输入，确认生成的 YAML 文件格式正确、`AppConfig` 正确返回

---

## T7: Anthropic Provider

**文件：** `src/forgecode/providers/anthropic.py`
**依赖：** T2, T4

**步骤：**
1. 实现 `AnthropicProvider(BaseProvider)`：
   - `__init__`：创建 `AsyncAnthropic(base_url=config.base_url, api_key=config.api_key)`
2. 实现 `chat_stream(messages) -> AsyncIterator[StreamEvent]`：
   - 将 `Message` 列表转换为 Anthropic API 格式：
     - system: 无（本阶段不设 system prompt）
     - messages: `[{"role": m.role, "content": m.content} for m in messages]`
   - 调用 `self.client.messages.stream(model=config.model, max_tokens=4096, messages=..., thinking=...)`
   - 使用 `async with` 管理 stream context manager
   - 遍历 stream 事件，映射为 StreamEvent：
     - `RawContentBlockStartEvent` 且 `content_block.type == "thinking"` → yield `ThinkingStart()`
     - `RawContentBlockStopEvent` 且 index 对应 thinking block → yield `ThinkingEnd()`
     - `RawContentDeltaEvent` 且 `delta.type == "thinking_delta"` → yield `ThinkingDelta(delta.thinking)`
     - `RawContentDeltaEvent` 且 `delta.type == "text_delta"` → yield `TextDelta(delta.text)`
3. 重试逻辑：用 `_stream_with_retry(messages)` 内部方法包装：
   - 网络异常（`httpx.HTTPError`、`httpx.NetworkError` 等）→ 重试
   - `APIStatusError` 且 status_code >= 500 → 重试
   - `APIStatusError` 且 status_code < 500 → 不重试，yield `ErrorEvent(message=..., retryable=False)`
   - 重试 1 次后仍失败 → yield `ErrorEvent(message=..., retryable=True)`

**验证：** 创建 mock AsyncAnthropic 验证事件映射和重试逻辑（用 pytest + pytest-asyncio）

---

## T8: OpenAI Provider

**文件：** `src/forgecode/providers/openai.py`
**依赖：** T2, T4

**步骤：**
1. 实现 `OpenAIProvider(BaseProvider)`：
   - `__init__`：创建 `AsyncOpenAI(base_url=config.base_url, api_key=config.api_key)`
2. 实现 `chat_stream(messages) -> AsyncIterator[StreamEvent]`：
   - 将 `Message` 列表转换为 OpenAI API 格式：
     - `[{"role": m.role, "content": m.content} for m in messages]`
   - 调用 `self.client.chat.completions.create(model=config.model, messages=..., stream=True, ...)`
   - 遍历 `async for chunk in stream`：
     - 检查 `chunk.choices` 非空
     - 若 `chunk.choices[0].delta.content` 有值 → yield `TextDelta(content)`
     - 若存在 reasoning tokens（o-series 模型）→ 检查类似属性映射为 `ThinkingDelta`
     - 注意：OpenAI streaming 不天然区分 thinking/text 块边界，不做 `ThinkingStart`/`ThinkingEnd`（或简化处理）
3. 重试逻辑：同 T7 的逻辑，但捕获 `openai.APIStatusError` 和 `httpx` 异常：
   - 5xx → 重试 1 次
   - 4xx → `ErrorEvent(retryable=False)`

**验证：** 创建 mock AsyncOpenAI 验证事件映射和重试逻辑

---

## T9: TUI 主应用

**文件：** `src/forgecode/tui/app.py`
**依赖：** T2, T3, T4

**步骤：**
1. 定义 `ForgeApp` 类：
   - `__init__(self, config: AppConfig, provider: BaseProvider, conversation: Conversation)`：
     - 保存 config、provider、conversation
     - `_show_thinking: bool = True`（默认显示思考内容）
     - `_thinking_text: str = ""`（当前轮的思考内容缓冲）
     - `_assistant_text: str = ""`（当前轮的回复内容缓冲）
     - `_in_thinking: bool = False`

2. 实现 `run()` 方法：
   - 创建 `rich.console.Console`
   - 创建 `prompt_toolkit.PromptSession`（配置 ↑↓ 历史）
   - 打印欢迎信息（header + 初始提示）
   - 进入主循环：
     - 用 `session.prompt("> ")` 获取输入（asyncio 兼容模式）
     - 调用 `_handle_input(text)`
     - 若 `_exit_flag` 为 True 则 break

3. 实现 `_handle_input(text: str)`：
   - `text.strip()` 为空 → 忽略
   - 以 `/` 开头 → `_handle_command(text)`
   - 否则 → `asyncio.ensure_future(_send_message(text))`（或同步等待）

4. 实现 `_handle_command(text: str)`：
   - 解析命令和参数（按空格 split）
   - `/help` → 打印帮助信息到对话区
   - `/clear` → `conversation.clear()`，清屏重新渲染 header
   - `/exit`、`/quit` → 设置 `_exit_flag = True`
   - `/providers` → 遍历 `config.providers` 列出信息
   - `/switch <name>` → 查找 provider，重建 `self.provider`，更新 `config.active_provider_name`，刷新 header
   - `/thinking on` → `_show_thinking = True`
   - `/thinking off` → `_show_thinking = False`
   - 未知命令 → 提示 "未知命令，输入 /help 查看可用命令"

5. 实现 `async _send_message(text: str)`：
   - `conversation.add("user", text)`
   - 重置 `_thinking_text = ""`、`_assistant_text = ""`、`_in_thinking = False`
   - `async for event in self.provider.chat_stream(conversation.messages)`：
     - `TextDelta` → `_assistant_text += text`，实时打印到对话区（`console.print(text, end="")`）
     - `ThinkingStart` → `_in_thinking = True`，若 `_show_thinking` 则打印 "💭 思考过程"
     - `ThinkingDelta` → `_thinking_text += text`，若 `_show_thinking` 则实时打印
     - `ThinkingEnd` → `_in_thinking = False`，打印分割线
     - `ErrorEvent` → 打印错误提示
   - 流结束后 `conversation.add("assistant", _assistant_text)`
   - 打印换行

6. 实现 `_render_header()`：
   - 打印 Rich Panel："ForgeCode · {model}"，右侧显示当前 service name

**注意：** 本阶段不使用 Rich Live（避免过度设计），使用简单的 `console.print()` 逐行输出。流式效果通过 `end=""` + `sys.stdout.flush()` 实现。

**验证：** 启动应用 → 输入 "你好" → 确认流式输出 → `/clear` → `/exit`

---

## T10: 入口 main.py

**文件：** `src/forgecode/main.py`
**依赖：** T5, T6, T7, T8, T9

**步骤：**
1. 定义 `main()` 函数（async）：
   - `argparse`：定义 `--provider` 参数（可选，str）
   - 调用 `load_config(args.provider)` → `AppConfig`
   - 获取活动配置：遍历 `app_config.providers` 找 `name == app_config.active_provider_name`
   - 调用 `create_provider(active_config)` → `BaseProvider`
   - 创建 `Conversation()`
   - 创建 `ForgeApp(app_config, provider, conversation)`
   - 调用 `app.run()`
2. 定义 `cli()` 同步入口函数（给 pyproject.toml scripts 用）：
   - `asyncio.run(main())`
3. `if __name__ == "__main__": cli()`

**验证：** `uv run forgecode --provider my-claude` 正常启动 TUI；`uv run forgecode`（无参数）使用默认 provider；`uv run forgecode --provider nonexist` 报错退出

---

## 执行顺序

```
T1（脚手架）
├── T2（配置数据结构）
│   ├── T4（Provider 抽象层）
│   │   ├── T7（Anthropic Provider）
│   │   └── T8（OpenAI Provider）
│   └── T5（配置加载器）
│       └── T6（配置向导）
├── T3（对话管理）
│
└── T9（TUI 主应用）← 依赖 T2, T3, T4
    └── T10（入口）← 依赖 T5, T6, T7, T8, T9
```

**可并行：**
- T2 和 T3 可并行（都在 T1 完成后）
- T4 和 T5 可并行（都在 T2 完成后）
- T7 和 T8 可并行（都在 T4 完成后）
- T6 可在 T5 完成后独立开发
