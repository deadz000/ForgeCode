# ForgeCode Checklist

> 每一项通过运行代码或观察行为来验证，聚焦系统行为。

---

## 实现完整性

- [ ] 项目脚手架完整（验证：`uv run python -c "import forgecode"` 无报错）
- [ ] 所有 6 个数据结构和类可导入（验证：`uv run python -c "from forgecode.config.schema import ProviderConfig, AppConfig; from forgecode.conversation.history import Message, Conversation; from forgecode.providers import BaseProvider, create_provider; print('OK')"`）
- [ ] 配置加载器正常工作（验证：在项目目录创建测试 `forgecode.yaml`，运行 `uv run python -c "from forgecode.config.loader import load_config; c = load_config(); print(c.active_provider_name)"` 输出正确）
- [ ] 配置向导可生成有效配置文件（验证：删除所有 `forgecode.yaml`，运行 `uv run python -c "from forgecode.config.wizard import run_wizard; run_wizard()"` 后检查目标路径生成了合法 YAML）
- [ ] `AnthropicProvider` 可被工厂函数创建（验证：`create_provider(ProviderConfig(protocol="anthropic", ...))` 返回 `AnthropicProvider` 实例）
- [ ] `OpenAIProvider` 可被工厂函数创建（验证：`create_provider(ProviderConfig(protocol="openai", ...))` 返回 `OpenAIProvider` 实例）
- [ ] TUI 入口可启动（验证：`uv run forgecode --help` 显示使用帮助）
- [ ] 所有单元测试通过（验证：`uv run pytest` 全部绿色）

---

## 功能验收（按 spec 验收标准）

- [ ] **AC1**: 执行 `forgecode --provider my-claude` 后进入 TUI，界面顶部显示 "ForgeCode · claude-sonnet-4-20250514"（验证：启动后观察 header 内容）
- [ ] **AC2**: 在 TUI 中输入 "你好"，Claude API 返回的回复逐字流式打印在对话区域（验证：观察回复是否有打字机效果，非一次性输出）
- [ ] **AC3**: 连续进行 3 轮对话，第 3 轮 AI 的回复能结合第 1 轮的内容回答（验证：第 1 轮告诉 AI 你的名字，第 3 轮问 "我叫什么"，确认 AI 能答对）
- [ ] **AC4**: 输入 `/clear` 后再对话，AI 不再知道之前的内容（验证：`/clear` 后问 "我刚才叫什么名字"，确认 AI 表示不知道）
- [ ] **AC5**: 切换到 OpenAI 供应商后能正常对话（验证：`/switch my-openai` 后发送消息，确认收到 GPT 的回复）
- [ ] **AC6**: 配置中 `thinking: true` 时，回复时显示思考过程（验证：启动 thinking 启用的 provider，发起一个需要推理的问题，观察界面是否出现 "💭 思考过程" 以及后续推理内容）
- [ ] **AC7**: 网络不可达时 API 调用自动重试一次后显示错误提示而非崩溃（验证：配置一个不存在的 `base_url`（如 `http://localhost:19999`），发送消息，确认程序不退出，显示错误信息后仍可继续输入）
- [ ] **AC8**: 配置文件为空或不存在时，启动弹出向导引导创建初始配置（验证：删除所有 `forgecode.yaml`，运行 `forgecode`，确认出现交互式向导）
- [ ] **AC9**: 输入 `/exit` 后程序正常退出（验证：TUI 中输入 `/exit`，确认终端回到 shell 提示符，退出码为 0）
- [ ] **AC10**: 在输入区域按 ↑ 键能调出上一条输入历史（验证：发送一条消息后，在空输入行按 ↑，确认上条消息出现在输入行）
- [ ] **AC11**: 不指定 `--provider` 时使用配置文件中的第一个供应商（验证：`forgecode.yaml` 中有多个 provider，不带 `--provider` 启动，确认 header 显示第一个 provider 的模型名）

---

## 集成检查

- [ ] 配置加载 → Provider 创建 → TUI 启动的完整链路无断点（验证：`uv run forgecode` 正常启动到 TUI 界面）
- [ ] `/switch` 命令正确切换 Provider 并更新 header（验证：切换后发送消息，确认走的新后端；header 显示新模型名）
- [ ] 全局 + 项目级两层配置合并正确：项目级同名 provider 覆盖全局级（验证：在两层各配一个同名 provider，项目级使用不同 model，启动后 header 显示项目级的 model）
- [ ] 对话历史在各层之间正确传递：Conversation → Provider.chat_stream() → API 请求（验证：通过在 API 调用处打印 messages 数量，确认多轮后 messages 数量递增）
- [ ] `/clear` 后 Conversation 清空且后续 API 请求不带历史（验证：`/clear` 后发送消息，确认 API 请求中 messages 只有当前这一条）

---

## 编译与代码质量

- [ ] `uv run ruff check .` 无 lint 错误
- [ ] `uv run mypy src/forgecode/` 严格模式无类型错误（或仅有合理的 `# type: ignore`）
- [ ] `uv run pytest` 全部测试通过，覆盖率 ≥ 80%
- [ ] `pyproject.toml` 中声明的依赖与实际 import 一致（验证：`uv run python -c "import openai, anthropic, rich, prompt_toolkit, yaml"` 全部成功）

---

## 端到端场景

- [ ] **场景 1：全新用户首次使用完整流程**
  1. 用户机器上无任何 `forgecode.yaml`
  2. 运行 `uv run forgecode`
  3. 弹出配置向导，创建全局配置（protocol=anthropic, model=claude-sonnet-4-20250514）
  4. 进入 TUI，header 显示 "ForgeCode · claude-sonnet-4-20250514"
  5. 发送 "用 Python 写一个 hello world"
  6. 观察 AI 流式输出代码，Markdown 代码块高亮
  7. 发送 "在上面的代码里加一行注释"
  8. AI 能记住上一轮对话内容，正确修改代码
  9. 输入 `/clear` 清空历史
  10. 输入 `/exit` 退出
  11. **结果：** 全程无报错，对话体验流畅，退出码 0

- [ ] **场景 2：多供应商切换**
  1. 配置文件有两个 provider：`claude`（anthropic）和 `gpt`（openai）
  2. 默认启动使用 `claude`
  3. 发送一轮对话确认 Claude 正常回复
  4. `/switch gpt` 切换
  5. 发送一轮对话确认 GPT 正常回复
  6. `/providers` 列出两个供应商
  7. **结果：** 两次回复分别来自不同后端，切换过程无报错

- [ ] **场景 3：错误恢复**
  1. 配置一个 API Key 无效的 provider
  2. 启动并发送消息
  3. API 返回 401（4xx 不重试），直接显示错误信息
  4. 程序不崩溃，仍可输入 `/switch` 切换或 `/exit` 退出
  5. **结果：** 错误提示清晰，程序健壮不崩溃

- [ ] **场景 4：思考过程展示**
  1. 配置 thinking=true 的 Anthropic provider
  2. 发送一个需要多步推理的问题（如 "一个水池进水 3 小时满，出水 5 小时空，同时开多久满"）
  3. 观察界面：先出现 "💭 思考过程" 及推理文本，再出现最终答案
  4. `/thinking off` 后再次发送推理问题
  5. 观察界面：不再显示思考过程，直接输出答案
  6. **结果：** 思考过程可展示、可关闭

---

## 非功能检查

- [ ] Python 版本兼容：`uv run python -c "import sys; assert sys.version_info >= (3, 11)"`
- [ ] 依赖安装无冲突：`uv sync` 无报错
- [ ] README.md 包含安装步骤和使用说明
