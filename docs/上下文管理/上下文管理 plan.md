# 上下文管理 Plan

## 架构概览

ch08 引入一个新的本地子包 `forgecode.compact`，作为上下文管理的唯一权威入口。包内承担三块职责：

1. **第 1 层预防性压缩**：在每一轮 LLM 请求发出之前，对 `forgecode.conversation` 中的工具结果做幂等的"超阈值落盘 + 字符串替换"，并把替换决策冻结在一个会话级账本里，保证 prompt cache 前缀逐字节稳定。
2. **第 2 层 LLM 摘要 + 恢复**：在估算 token 触达阈值（或被手动 / 紧急触发）时，调用 provider 跑一次结构化摘要请求，生成 9 部分摘要 + 三段恢复 + 近期原文，构造一个新的 `list[Message]` 替换掉旧的对话历史。
3. **辅助子模块**：token 估算（锚定真实 usage + 字符增量）、最近读过文件的并发安全追踪、会话目录管理、PTL 自重试与熔断器。

`forgecode.compact` 不直接持有 `Agent`,也不直接管理 `Provider`。它通过一组窄接口与外部模块交互：

| 外部模块 | 交互方向 | 形式 |
|----------|----------|------|
| `forgecode.agent` | Agent 调 compact | 主循环每轮请求前调 `manage_context`；ReadFile 成功后调 `RecoveryState.record_file`；捕获 `PromptTooLongError` 后调 `force_compact` 重试一次 |
| `forgecode.conversation` | compact 改 conversation | compact 拿到 `list[Message]` 后做字符串替换 / 摘要重建，再用一个新方法 `replace_history` 整体替换内存列表 |
| `forgecode.llm` | compact 调 provider | 摘要请求复用同一份 `Provider.stream`，但 `Request.tools` 留空；从 `StreamEvent` 尾部拿 usage 锚定 token 估算 |
| `forgecode.tui` | TUI 调 compact | TUI 拿到以 `/` 开头的输入走命令分发；`/compact` 命令调 compact 的 `force_compact` 并展示 token 变化系统消息 |
| `forgecode.config` | config 喂 compact | `ProviderConfig` 新增 `context_window: int`，未配置时按协议给默认值；compact 通过参数拿到当前 provider 的 `context_window` |

**Agent 生命周期与状态归属调整**：现状的 TUI 在 `_begin_turn` 里每轮 `Agent(...).run(...)` 重新构造一次 Agent（见 `src/forgecode/tui/stream.py`），意味着把 compact 的长生命周期状态（替换决策账本、文件追踪、自动摘要熔断计数、`usage_anchor`、本轮工具列表缓存）放成 `Agent` 字段会被每轮重置——决策冻结与熔断器立刻失效。

本章引入 `SessionRuntime` 作为 TUI Model 跨 run 持有的长生命周期状态容器：

```python
# src/forgecode/agent/runtime.py（新建）
from dataclasses import dataclass, field
import asyncio
from forgecode.compact import (
    ContentReplacementState, RecoveryState,
    CompactCircuitBreaker, SessionContext,
)

@dataclass
class SessionRuntime:
    replacement: ContentReplacementState
    recovery: RecoveryState
    auto_tracking: CompactCircuitBreaker
    session: SessionContext
    context_window: int = 200000
    usage_anchor: int = 0       # 上一次主对话路径 stream 真实 usage 之和;摘要请求不更新
    anchor_msg_len: int = 0     # anchor 当时 Conversation.length()，下次估算只算这之后的字符增量
    # asyncio 单线程，无需锁  # 保护 usage_anchor / anchor_msg_len
```

`Agent` 构造期通过关键字参数 `runtime: SessionRuntime` 注入；TUI Model 持有同一份 `SessionRuntime` 跨轮复用。状态所有权关系：TUI Model 拥有 `SessionRuntime`；每轮把 `SessionRuntime` 与 `Conversation` 一并交给 `Agent`。compact 是逻辑层，对状态零持有、可重入。

**依赖方向无环**：
- `forgecode.compact` 不 import `forgecode.agent` / `forgecode.config` / `forgecode.tui` / `forgecode.cli`。
- `forgecode.config` 仅在 `effective_context_window()` 中读自身常量（`DEFAULT_ANTHROPIC_CONTEXT_WINDOW` / `DEFAULT_OPENAI_CONTEXT_WINDOW` 定义在 `src/forgecode/config/protocol_defaults.py`，不放 compact 子包）。
- `forgecode.agent` 依赖 `forgecode.compact` + `forgecode.conversation` + `forgecode.llm` + `forgecode.tool` + `forgecode.permission`，**不** import `forgecode.config`。
- `src/forgecode/cli.py` 是唯一同时 import `config` 与 `agent` 的位置，负责把 `provider_cfg.effective_context_window()` 注入 `SessionRuntime`。
- `forgecode.tui` 持有 `SessionRuntime` 与 `Agent`（或在每轮构造 Agent 时把 runtime 传入）。

## 核心数据结构

```python
# src/forgecode/compact/state.py

import asyncio
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

# ContentReplacementState 是会话级的"工具结果替换决策账本"。
# _seen_ids 记录已经决策过的 tool_use_id，无论决策是替换还是保留原文。
# _replacements 只保存"决定替换"那一支的预览字符串，键是 tool_use_id。
# 同一个 tool_use_id 一旦进入 _seen_ids 就再也不会被重新评估，保证 prompt cache 稳定。
#
# 并发安全约束:offload_and_snip 在执行期间在 asyncio 事件循环中串行执行(读账本 → 决策 → 落盘 →
# 写账本必须在同一临界区内原子完成),避免出现"已 Seen 但 replacement 未写"的中间态。
# 对外只暴露一个高层方法 decide_once 让调用方传入决策回调,由本类型内部统一加锁。
# 一旦预览字符串写入 _replacements[id]，本会话内不允许修改。offload_and_snip 永远不
# 重新调用 build_preview，已 Seen 的 id 直接复用现存字符串。
class ContentReplacementState:
    def __init__(self) -> None:
        # 无需显式锁——Python asyncio 单线程事件循环保证串行
        self._seen_ids: set[str] = set()
        self._replacements: dict[str, str] = {}

    def decide_once(
        self,
        tool_use_id: str,
        original_content: str,
        decide: Callable[[], tuple[str, str]],  # 返回 (decision, preview)
    ) -> str:
        """一次性完成"查账本→决策→写账本"。

        decide 回调在持锁状态下被调用，返回 (decision, preview)，其中：
          - decision == "kept" → 写 _seen_ids，不写 _replacements；返回原 content。
          - decision == "replaced" → 写 _seen_ids + _replacements；返回 preview。
          - decision == "skip" → 既不写 _seen_ids 也不写 _replacements；返回原
            content（下一轮重试）。
        若 id 已 Seen：直接返回账本中存量结果（不再调 decide）。
        """
        ...

# CompactCircuitBreaker 跟踪自动摘要连续失败次数,用于熔断。
# 手动 / 紧急压缩路径不读这个字段。
class CompactCircuitBreaker:
    def __init__(self) -> None:
        # 无需显式锁——Python asyncio 单线程事件循环保证串行
        self._consecutive_failures = 0

    def record_success(self) -> None: ...
    def record_failure(self) -> None: ...
    def tripped(self) -> bool: ...

# RecoveryState 是 Agent 主循环写、compact 摘要时读的文件追踪状态。
# _files 的键是文件绝对路径，避免相对路径在不同 cwd 下错乱。
@dataclass
class FileReadRecord:
    path: str
    content: str            # 不带行号前缀的纯净字节
    timestamp: datetime     # 最后一次成功读取的时间

class RecoveryState:
    def __init__(self) -> None:
        # 无需显式锁——Python asyncio 单线程事件循环保证串行
        self._files: dict[str, FileReadRecord] = {}

    def record_file(self, path: str, content: str) -> None: ...
    def snapshot(self) -> list[FileReadRecord]:
        """返回按 timestamp 倒序排序的拷贝列表。"""
        ...

# SessionContext 是会话生命周期信息。session_id 进程启动时一次性生成。
# spill_dir 是落盘目录，固定指向 .forgecode/sessions/<session_id>/tool-results/。
@dataclass
class SessionContext:
    session_id: str
    spill_dir: str

def new_session_context(workspace: str) -> SessionContext: ...
```

```python
# src/forgecode/compact/const.py

SINGLE_RESULT_LIMIT                   = 50000   # 单条工具结果落盘阈值(字节)
MESSAGE_AGGREGATE_LIMIT               = 200000  # 单条 RoleTool 消息内工具结果聚合阈值(字节)
SUMMARY_RESERVE                       = 20000   # 给摘要 LLM 输出预留的 token 空间
AUTO_SAFETY_MARGIN                    = 13000   # 自动触发的额外安全余量:防估算误差与单轮波动
MANUAL_SAFETY_MARGIN                  = 3000    # 手动触发的安全余量:只用来判断摘要请求本身能不能塞下
RECOVERY_FILE_LIMIT                   = 5       # 恢复段最多展示几个文件
RECOVERY_TOKENS_PER_FILE              = 5000    # 单个文件快照的 token 上限,超出时保留头部、截掉尾部
RECENT_KEEP_TOKENS                    = 10000   # 摘要后保留近期原文的 token 下界
RECENT_KEEP_MESSAGES                  = 5       # 摘要后保留近期原文的条数下界
MAX_CONSECUTIVE_AUTO_COMPACT_FAILURES = 3       # 熔断阈值
PTL_RETRY_LIMIT                       = 3       # 摘要请求自身 PTL 的"直接重试"次数
PTL_DROP_PERCENTAGE                   = 0.2     # 3 次后每次再丢的比例
ESTIMATE_CHARS_PER_TOKEN              = 3.5     # 增量估算的字符/token 比
PREVIEW_HEAD_BYTES                    = 2048    # 预览体头部字节数上限
PREVIEW_HEAD_LINES                    = 20      # 预览体头部行数上限
```

```python
# src/forgecode/config/config.py 改动(仅追加字段,不动现有字段顺序与名字)

from dataclasses import dataclass

@dataclass
class ProviderConfig:
    name: str
    protocol: str            # "anthropic" | "openai"
    base_url: str | None
    api_key: str
    model: str
    thinking: bool = False      # 仅 anthropic 生效
    context_window: int = 0     # 新增字段，单位 token，0 表示走协议默认

# src/forgecode/config/protocol_defaults.py（新文件）
DEFAULT_ANTHROPIC_CONTEXT_WINDOW = 200000
DEFAULT_OPENAI_CONTEXT_WINDOW    = 128000

# 派生方法,给 compact / cli 用
def effective_context_window(p: ProviderConfig) -> int:
    if p.context_window > 0:
        return p.context_window
    if p.protocol == "anthropic":
        return DEFAULT_ANTHROPIC_CONTEXT_WINDOW
    if p.protocol == "openai":
        return DEFAULT_OPENAI_CONTEXT_WINDOW
    return DEFAULT_ANTHROPIC_CONTEXT_WINDOW
```

> **依赖方向说明**：协议默认值常量定义在 `src/forgecode/config/protocol_defaults.py`，由 `forgecode.config` 自身使用；`forgecode.compact` 包不持有协议默认值常量。`config` 与 `compact` 单向无环。

## 模块设计

### compact 子包

#### `compact.py` - manage_context 主入口

```python
from dataclasses import dataclass
from enum import Enum
from typing import Any

class TriggerKind(Enum):
    AUTO = "auto"
    MANUAL = "manual"
    EMERGENCY = "emergency"

@dataclass
class ManageInput:
    conv: "Conversation"
    provider: "Provider"
    model: str
    context_window: int
    tool_defs: list["ToolDefinition"]       # 主循环本轮迭代开头按当前 mode 选好的工具定义列表，恢复段与 stream 共用此列表
    replacement: ContentReplacementState
    recovery: RecoveryState
    auto_tracking: CompactCircuitBreaker
    session: SessionContext
    usage_anchor: int                       # 上一次主对话路径 stream 真实 usage 之和
    anchor_msg_len: int                     # anchor 当时 conv.length()
    estimated_token: int                    # 调用方算好的本轮估算 token (= anchor + chars/3.5)
    trigger: TriggerKind

@dataclass
class ManageOutput:
    before_tokens: int
    after_tokens: int

async def manage_context(in_: ManageInput) -> ManageOutput:
    """Agent 每轮请求前必调的唯一入口。

    步骤:
      1. 若 trigger == MANUAL: 跳过第 1 层、阈值、熔断;直接 force_compact。
         若 trigger == EMERGENCY: 先强制跑一次 offload_and_snip(layer1),
         再无条件 force_compact——避免摘要请求本身因为大工具结果直接撞 PTL。
      2. 否则(AUTO 路径):
         a. 先执行第 1 层 offload_and_snip 得到 updated_msgs;
         b. 用 estimate_tokens(in_.usage_anchor, updated_msgs, in_.anchor_msg_len)
            重算估算 token (**必须用 layer1 之后的 updated_msgs**,否则估算会偏高、
            过早触发 layer2);
         c. 若估算 < (context_window - SUMMARY_RESERVE - AUTO_SAFETY_MARGIN) 或
            auto_tracking.tripped(): 直接返回,仅 layer1 生效;
         d. 否则 auto_compact, 成功后 replace_history。

    before_tokens / after_tokens 口径:
      - before_tokens = manage_context 入口处的 in_.estimated_token;
      - after_tokens = layer2 替换 conversation 后用 estimate_tokens(0, new_msgs, 0)
        重新算的值;若只跑了 layer1, after_tokens = estimate_tokens(
        in_.usage_anchor, layer1_out, in_.anchor_msg_len)。
    """
```

职责：编排两层调用顺序、决定走自动 / 手动 / 紧急路径、把替换/摘要后的消息写回 `Conversation`、更新熔断器计数。

依赖：`layer1.offload_and_snip`、`layer2.auto_compact`、`layer2.force_compact`、`token.estimate_tokens`。

#### `layer1.py` - 单结果与聚合落盘 + 决策冻结

```python
def offload_and_snip(
    msgs: list[Message],
    state: ContentReplacementState,
    session: SessionContext,
) -> list[Message]:
    """遍历 msgs，针对每一条 Role == "tool" 的消息上的 tool_results 列表做处理
    (forgecode 在 Conversation.add_tool_results 把一轮工具结果挂在一条 RoleTool
    消息上，工具结果不在 assistant 消息里)。规则:
      1. 已经在 state._seen_ids 中的工具结果，通过 decide_once 拿到现存决策结果
         (kept → 返回原文; replaced → 复用 _replacements[id]，**不重新构造** preview);
      2. 未决策的项进入候选列表，按字节倒序处理:
         a. 单条 > SINGLE_RESULT_LIMIT: spill_single 成功 → 改写 content → replaced,
            同时把该项从聚合预算里扣除;
         b. 然后看剩余项的聚合字节是否 > MESSAGE_AGGREGATE_LIMIT;继续按倒序逐项落盘,
            直至剩余聚合 ≤ MESSAGE_AGGREGATE_LIMIT;
         c. 未落盘的项 kept。
      3. 落盘失败时降级为不替换、不写账本(decide_once 通过 decision == "skip" 信号
         实现),下次重试。
      4. 落盘 → 改写 content → 写账本 三个动作通过 decide_once 在持锁状态下顺序执行,
         任一步失败回退到 skip; 保证 content 与账本永远一致。
    返回新的 list[Message]，纯函数风格，不修改入参。
    """

def spill_single(session: SessionContext, tool_use_id: str, content: str) -> None:
    """把单条 tool_result 内容写入 spill_dir/<tool_use_id>。

    幂等:文件已存在则不重写、不报错。失败抛 OSError 由上层捕获。
    """

def build_preview(original_bytes: int, head: str, spill_path: str) -> str:
    """构造替换体字符串，包含原始字节数、头部预览、落盘路径、重读提示。

    头部预览策略: 先按 \\n 分成最多 PREVIEW_HEAD_LINES 行，再按 PREVIEW_HEAD_BYTES
    字节二次裁剪。调用时机: 只在 offload_and_snip 内首次决策为替换的瞬间调用一次;
    之后所有轮次都必须通过 state.decide_once 复用 _replacements[id] 里存好的字符串,
    不允许重新调用。
    """
```

职责：单条 / 聚合判断、落盘 I/O、预览体格式化、账本写入。

依赖：`SessionContext`、`ContentReplacementState`。

#### `layer2.py` - 摘要、PTL 重试、熔断

```python
async def auto_compact(in_: ManageInput) -> tuple[list[Message], int, int]:
    """熔断器未触发时执行,整轮(含 PTL 自重试)失败累加 consecutive_failures,
    成功清零。before_tok = in_.estimated_token; after_tok = estimate_tokens(0, new_msgs, 0)。
    返回 (new_msgs, before_tok, after_tok); 失败抛 CompactError。"""

async def force_compact(in_: ManageInput) -> tuple[list[Message], int, int]:
    """手动 / 紧急路径专用:跳过熔断器。before_tok / after_tok 口径同 auto_compact。
    失败也不计入熔断。"""

async def run_summary(in_: ManageInput) -> list[Message]:
    """两条路径的共同核心:构造摘要 prompt、发请求、解析 <summary>、拼接恢复段、
    追加近期原文边界裁剪。

    调用入口必须先拍一次 recovery_snapshot = in_.recovery.snapshot()，整个
    run_summary 生命周期内只使用这一份快照，避免恢复段渲染期间 record_file 写入
    造成"声明的工具/文件"与"stream 调用时刻状态"漂移。
    """

async def summarize_once(in_: ManageInput, msgs: list[Message]) -> str:
    """发一次摘要请求。

    实现要点: req = Request(messages=build_summary_prompt(msgs), tools=None);
    async for ev in in_.provider.stream(req): text 累加, ev.usage 捕获;
    ev.err 非 None 时立即终止并把该 err 抛出; PTL 由调用方通过 isinstance(err,
    PromptTooLongError) 识别并切到 ptl_retry。

    **重要**: 摘要请求结束后不更新 SessionRuntime.usage_anchor; usage_anchor
    只由主对话路径维护。
    """

async def ptl_retry(
    in_: ManageInput, msgs: list[Message], first_err: Exception
) -> str:
    """实现 F27 的丢消息组策略:
      - 前 PTL_RETRY_LIMIT 次:每次丢最旧的若干"用户提交 + 一组 assistant/tool 往返"分组;
      - 之后:每次按当前剩余消息组数 × PTL_DROP_PERCENTAGE 丢(math.ceil,至少 1 组);
      - 直到摘要请求能塞下,或全部丢光抛错误。
    中间任何"非 PTL"错误立即上抛,不再重试。
    """

def pick_recent_tail(msgs: list[Message]) -> list[Message]:
    """从 msgs 尾部累加，满足以下条件后停止:
      - 累计估算 token ≥ RECENT_KEEP_TOKENS 且
      - 累计消息数 ≥ RECENT_KEEP_MESSAGES;
      - 二者择宽(两个下界都满足)。
    之后再做 tool_use/tool_result 配对修正:若截断点夹在配对中间，向前推到
    tool_use 之前。
    """

def group_by_user_turn(msgs: list[Message]) -> list[list[Message]]:
    """按 F27 的"用户提交 → 一组 assistant/tool 往返"分组,给 ptl_retry 用。"""
```

职责：摘要 LLM 请求构造、PTL 自重试、熔断计数维护、近期原文边界推算。

依赖：`forgecode.llm.Provider`、`summary_prompt`、`recovery`、`token`、`CompactCircuitBreaker`。

#### `summary_prompt.py` - 摘要 Prompt 模板

```python
def build_summary_prompt(msgs: list[Message]) -> list[Message]:
    """把对话 msgs 嵌入到固定模板里。

    返回长度为 1 的列表,仅一条 user 消息，其 content 形如:

      You are summarizing a coding agent conversation. Output in two phases.

      <analysis>
      （在这里写分析草稿，会被丢弃）
      </analysis>

      <summary>
      ## 1 主要请求和意图
      ## 2 关键技术概念
      ## 3 文件和代码段
      ## 4 错误和修复
      ## 5 问题解决过程
      ## 6 所有用户消息原文
      ## 7 待办任务
      ## 8 当前工作(最详细)
      ## 9 可能的下一步
      </summary>

      不要调用任何工具,输出纯文本。

      [conversation]
      <serialize_conversation(msgs) 的输出>

    9 个小节标题在 prompt 中是固定字面字符串，便于 extract_summary 解析与测试匹配。
    """

def serialize_conversation(msgs: list[Message]) -> str:
    """把对话扁平化成可读文本(不暴露 ToolCall.input 原 JSON):
      - 每条 user/assistant 消息:`role: <content>`
      - assistant 工具调用:`[call <name> id=<id> args=<json string>]`
      - tool 消息内的每条 result:`[result id=<id> is_error=<bool>] <content>`
    行间用 \\n 隔开;本函数纯函数,不依赖外部状态,便于单测固定预期文本。
    """

def extract_summary(raw: str) -> str:
    """从模型返回的整段文本里抠出 <summary>...</summary> 之间的正文。

    <analysis> 部分直接丢弃。提取失败时返回原文 + 一个 logging.warning，避免硬失败。
    """
```

职责：维护摘要 prompt 的全文文案、解析模型输出。

依赖：标准库 `re` / `logging`（纯模板 + 字符串解析）。

#### `recovery.py` - 三段恢复

```python
def build_recovery_attachment(
    snapshot: list[FileReadRecord],
    tool_defs: list[ToolDefinition],
) -> str:
    """构造摘要后的"恢复三段"内容。

    调用方必须先在 run_summary 入口拍一次快照
    snapshot = recovery.snapshot()，把快照而非 RecoveryState 传入本函数,
    避免恢复段渲染期间另一个 task 通过 record_file 改变状态导致漂移。

    三段:
      1. 最近读过的文件快照:取 snapshot 前 RECOVERY_FILE_LIMIT 个(已按时间戳倒序),
         单文件 > RECOVERY_TOKENS_PER_FILE token 时保留头部对应字符片段,
         截掉尾部多余内容,并在尾部追加 (content truncated);
      2. 当前可用工具列表:直接来自入参 tool_defs(与 stream 调用同一列表引用),
         保证恢复段宣称的工具集与 Request.tools 完全一致;
      3. 边界提示消息:固定文案。
    返回纯文本 str。摘要消息与恢复消息合并到同一条 user 消息上输出(见
    layer2.run_summary 拼装规则),避免 user/user 连续违反 anthropic 协议;
    本函数只负责返回"恢复三段"的内容片段,layer2 会与摘要文本拼到同一条
    user 消息上。
    """

def render_file_block(rec: FileReadRecord) -> str:
    """渲染单个文件快照:路径 / 时间戳 / 内容片段(必要时截断)。"""

def render_tools_block(defs: list[ToolDefinition]) -> str:
    """渲染工具列表:每行一个工具名 + 用途 + 参数 schema 摘要。"""

BOUNDARY_NOTICE: str = """\
...固定文案:需要文件原文/错误原文/用户原话时,请使用文件读取工具重新读取对应路径,
不要依据摘要内容做猜测...
"""
```

职责：把 RecoveryState 快照 + tool_defs 组合成一段稳定文本。

依赖：`FileReadRecord`、`forgecode.llm.ToolDefinition`。

#### `token.py` - Token 估算

```python
import math

def estimate_tokens(anchor: int, all_msgs: list[Message], anchor_msg_len: int) -> int:
    """锚定最近一次 provider usage + 之后新增消息的字符增量。

    入参语义:
      - anchor: 上一次主对话路径 stream 真实 usage 之和(int);
      - all_msgs: 当前 conv.messages() 完整列表;
      - anchor_msg_len: 当 anchor 被记录时 conv.length() 的值,
        表示锚点之前已被这份 usage 算进的消息条数;
      - 函数只把 all_msgs[anchor_msg_len:] 这部分的字符累加,避免把已含在 anchor
        里的历史重复计算。
      - 入参 all_msgs 必须是已经经过 offload_and_snip 处理(layer1 之后)的消息
        列表;否则估算偏高,会过早触发 layer2。
      - 返回 anchor + math.ceil(sum(chars(msg)) / ESTIMATE_CHARS_PER_TOKEN)。
    锚点为 0、anchor_msg_len 为 0(首轮 / 摘要后)时退化为纯字符估算。
    """

def usage_anchor(u: Usage) -> int:
    """把 stream 尾事件中的 usage 合并成单一锚点值。

    等价于 u.input_tokens + u.output_tokens + u.cache_read + u.cache_write。
    """

def message_chars(msgs: list[Message]) -> int:
    """计算单段消息列表的字符总量。

    累加 len(content.encode("utf-8")) + 每个 tool_calls[i].input 序列化后的
    字节长度 + 每个 tool_results[i].content 的字节长度。
    """
```

职责：纯函数估算。

依赖：标准库 `math`。

### Agent 主循环改造（`src/forgecode/agent/agent.py`）

Agent 通过 `SessionRuntime` 拿到所有长生命周期状态；Agent 自身只新增轻量字段：

```python
class Agent:
    def __init__(
        self,
        provider: Provider,
        registry: ToolRegistry,
        version: str,
        engine: PermissionEngine,
        *,
        runtime: SessionRuntime | None = None,
    ) -> None:
        self.provider = provider
        self.registry = registry
        self.version = version
        self.engine = engine
        self.runtime = runtime or SessionRuntime(...)  # 测试场景默认值
        # 用 asyncio.Lock 保证 run 与 force_compact 不并发                # 保证 run 与 run_force_compact 不并发
```

主循环关键改动：

1. **本轮迭代开头**：按当前 `permission_mode` 选 `defs = self.registry.definitions()` 或 `read_only_definitions()`，把同一份 `defs` 列表同时作为 `ManageInput.tool_defs` 和 `_stream_once` 的 `Request.tools`，保证恢复段宣称的工具与请求 tools 来自同一引用（`id(defs)` 相同）。`defs` 不缓存到 Agent 字段（避免 mode 切换时复用旧列表），但同一轮迭代内被 `manage_context` 与 `_stream_once` 共用。
2. **每轮 `_stream_once` 之前**：构造 `ManageInput`：`usage_anchor = self.runtime.usage_anchor`、`anchor_msg_len = self.runtime.anchor_msg_len`、`estimated_token = estimate_tokens(usage_anchor, conv.messages(), anchor_msg_len)`、`trigger = TriggerKind.AUTO`。`await manage_context(in_)`，错误走错误流程；`manage_context` 内部已经把消息列表写回 conversation。
3. **`_stream_once` 签名扩展为返回 (text, calls, usage, err)**：把现有 `(text, calls, usage, ok)` 改成 `(text, calls, usage, err: Exception | None)`。错误来源是 `StreamEvent.err`（forgecode 的 `Provider.stream` 是 async generator，错误通过事件流投递）。`_stream_once` 在收到 ev.err 时累加的 text 不写回 Conversation（保证 Conversation 状态与 stream 调用前一致，紧急压缩可以安全地 `replace_history`）。
4. **stream 完成后**（仅主对话路径）：从尾事件中读 `usage`，调 `usage_anchor(usage)` 更新 `self.runtime.usage_anchor`，同时 `self.runtime.anchor_msg_len = conv.length()`。摘要请求结束后**不**更新这两个字段。
5. **ReadFile 工具调用成功后**：在 `_execute_batched` 内、工具 worker task 内同步 `await` 执行：检测 `tool_name == "read_file"` 且 `tool.Result.is_error is False`，把 `ToolCall.input`（dict）取出 `path` 字段（与 `src/forgecode/tool/read_file.py` 定义的参数名一致），`pathlib.Path(path).resolve()` 后用 `await asyncio.to_thread(Path(abs_path).read_bytes)` 拿纯净字节，调 `self.runtime.recovery.record_file(abs_path, b.decode("utf-8", errors="replace"))`。读盘失败 `try/except OSError: pass` 吞掉。调用必须在 `conv.add_tool_results(results)` **之前**完成（同 task 顺序），保证下一次 `manage_context` 能看到本轮 ReadFile 的记录。
6. **错误捕获 / 紧急压缩**：在主循环内捕获 `_stream_once` 返回的 `err`，用 `isinstance(err, PromptTooLongError)` 判断。命中时：
   - 用一个迭代级局部变量 `emergency_retried = False` 锁定一次性重试。若已为 True 则按正常错误上抛。
   - `await manage_context(in_)` with `trigger = TriggerKind.EMERGENCY`：内部先做一次 `offload_and_snip` 再 `force_compact`。
   - 紧急压缩成功后把 `self.runtime.usage_anchor = 0`、`self.runtime.anchor_msg_len = 0`（conversation 已重建），用 `estimate_tokens(0, conv.messages(), 0)` 重新算估算 token；若估算已低于 `context_window - MANUAL_SAFETY_MARGIN` 则置 `emergency_retried = True` 后重试本轮 `_stream_once`；否则视为不可恢复，按错误上抛，不做第二次紧急压缩。
   - 紧急路径里 `force_compact` 内部若遇 PTL 走 `ptl_retry`，全程不调 `auto_tracking` 任何方法。

> **run 与 run_force_compact 互斥**：Agent 在 `run` 入口先 `async with self._run_lock:`；`run_force_compact` 入口也先 `async with self._run_lock:`。保证手动 `/compact` 不与正在进行的 run 并发触发 `manage_context`。

> **run 期间 Registry 不可变**：本章承诺主循环开头算出的 `tool_defs` 在一次 run 调用内保持稳定；MCP 工具的注册/注销只允许发生在 run 之间。如果未来需要 run 中动态增删工具，必须重新约定 `tool_defs` 重算时机并同步刷新恢复段缓存。

> **压缩状态事件 emit**（兑现 spec F24a / F24b）：`Event` 结构新增 `compact: CompactEvent | None` 字段（`src/forgecode/agent/event.py`）。主循环在以下两个时机向事件队列 emit 状态事件，让 TUI 在 LLM 摘要请求还在跑的时候就能立刻显示"压缩中"前缀，避免用户以为程序卡死：
>
> - **自动路径**（主循环步骤 2 内）：若本轮 `estimate_tokens` 已超 `context_window - SUMMARY_RESERVE - AUTO_SAFETY_MARGIN`（即必然要走 layer 2），在 `await manage_context(in_)` **之前** emit `Event(compact=CompactEvent(phase=CompactPhase.BEFORE_AUTO))`；`manage_context` 返回后 emit `Event(compact=CompactEvent(phase=CompactPhase.AFTER_AUTO, before=..., after=..., err=...))`。如果本轮估算未超阈值（只跑 layer 1 / 什么都不做），**不发任何 Compact 事件**——layer 1 是静默操作。
> - **紧急路径**（主循环步骤 6 内）：在 `trigger = TriggerKind.EMERGENCY` 调 `manage_context` **之前** emit `Event(compact=CompactEvent(phase=CompactPhase.BEFORE_EMERGENCY))`；`manage_context` 返回后 emit `Event(compact=CompactEvent(phase=CompactPhase.AFTER_EMERGENCY, before=..., after=..., err=...))`。
> - **手动路径**（`/compact` / `run_force_compact`）：不走 Compact 事件路径，由 TUI `handle_compact` 直接拿到 `(before, after, err)` 元组通过 `App.call_from_thread` / `App.post_message` 回投，文案统一格式见后文 TUI 渲染段。
>
> ```python
> # src/forgecode/agent/event.py
> from dataclasses import dataclass
> from enum import Enum
>
> class CompactPhase(Enum):
>     BEFORE_AUTO       = "before_auto"
>     AFTER_AUTO        = "after_auto"
>     BEFORE_EMERGENCY  = "before_emergency"
>     AFTER_EMERGENCY   = "after_emergency"
>
> @dataclass
> class CompactEvent:
>     phase: CompactPhase
>     before: int = 0    # after 状态有意义;before 状态置 0
>     after: int = 0
>     err: Exception | None = None
>
> @dataclass
> class Event:
>     # ... 既有字段
>     compact: CompactEvent | None = None  # 新增:压缩生命周期事件
> ```

### Conversation 改造（`src/forgecode/conversation.py`）

新增一个整体替换方法，并补充内部 lock 保护：

```python
# Conversation 内部新增 # 无需显式锁
# messages / replace_history / add_xxx 都加锁,
# 防止 replace_history 与 messages 并发时拿到部分写入的列表。

def replace_history(self, msgs: list[Message]) -> None:
    """把内存列表整体替换为传入的 msgs。

    compact 摘要后用这个方法一次性丢弃旧历史并装入"摘要 + 恢复 + 近期原文"。
    不暴露列表引用,用 copy.deepcopy 做深拷贝(含 tool_calls / tool_results 子列表)
    以免外部继续持有旧列表。
    """
```

> **性能评估**：每轮 `manage_context` 都会调 `replace_history`（layer1-only 时也要写回，否则 `offload_and_snip` 的字符串替换不会作用于下一轮）。25 轮 × 数十条消息 × 数百 KB 字符串的深拷贝在毫秒级完成（CPython 3.12 `copy.deepcopy` 性能足够），与摘要 LLM 请求几十秒耗时相比可忽略；不做对象池。

### TUI 命令分发（`src/forgecode/tui/`）

`src/forgecode/tui/stream.py` 现有 `submit()` 内部已经有针对 `/exit` / `/plan` / `/do` 的 `match/case` 分支。本章把这三个命令一并迁移到统一注册表，并新增 `/compact`：

```python
# src/forgecode/tui/commands.py(新文件)

from collections.abc import Awaitable, Callable
from typing import Any

CommandHandler = Callable[[Any], Awaitable[None]]   # 入参为 ForgeCodeApp

def dispatch_command(input_: str) -> tuple[CommandHandler | None, bool]:
    """检查输入是否以 "/" 开头;命中则返回对应命令处理器;
    未以 "/" 开头返回 (None, False);以 "/" 开头但未注册则返回 unknown_command handler。
    """

# BUILTIN_COMMANDS 注册表初始填四项:迁移现有 /exit / /plan / /do,新增 /compact。
BUILTIN_COMMANDS: dict[str, CommandHandler] = {
    "/exit":    handle_exit,
    "/plan":    handle_plan,
    "/do":      handle_do,
    "/compact": handle_compact,
}

async def handle_compact(app: "ForgeCodeApp") -> None:
    """在 asyncio.create_task 里调 app.agent.run_force_compact(...)；
    完成后用 app.call_from_thread / app.post_message 把 (before, after, err)
    抛回 TUI 主循环，由 Update 决定打印系统消息:成功 "已压缩，token 从 X 降至 Y",
    失败 "压缩失败: <err>"。命令路径不调 conv.add_user，不写入对话历史。
    """
```

`ForgeCodeApp` 字段调整：

```python
class ForgeCodeApp(App):
    runtime: SessionRuntime  # 新增:跨 run 持有的长生命周期状态
    agent: Agent             # 新增:常驻 Agent 实例(在 _begin_turn 内复用,不再每轮 new)
```

`_begin_turn` 不再每轮 `Agent(...)`：构造期一次性 `self.agent = Agent(self.provider, self.registry, self.version, self.engine, runtime=self.runtime)`；`_begin_turn` 只调 `await self.agent.run(turn_ctx, self.conv, self.mode)`。

Agent 层新增 `async def run_force_compact(self, conv, tool_defs) -> tuple[int, int]` 给 TUI 调用：内部先 `async with self._run_lock:` 等待主循环空闲，再构造 ManageInput with `trigger = TriggerKind.MANUAL`，调 `manage_context`，从 Output 取 `before_tokens` / `after_tokens` 返回（失败抛异常由 TUI 捕获）。

**TUI 渲染 Compact 事件**（兑现 spec F24a / F24b）：`src/forgecode/tui/stream.py` 的 `_update_streaming` 在 `StreamMsg` 处理上新增 `msg.compact is not None` 分支，按 phase 渲染系统消息后继续 `await self.events.__anext__()` 拉下一帧，**不写入 conversation**：

| Phase | 渲染文案 |
|-|-|
| `BEFORE_AUTO` | `"正在压缩上下文..."` |
| `BEFORE_EMERGENCY` | `"上下文撞墙，自动压缩中..."` |
| `AFTER_AUTO` / `AFTER_EMERGENCY` (err is None) | `"已压缩，token 从 <before> 降至 <after>"` |
| `AFTER_AUTO` / `AFTER_EMERGENCY` (err is not None) | `"压缩失败：<err>"` |

格式化逻辑抽出一个内部函数 `format_compact_notice(phase, before, after, err) -> str`，让 `handle_compact` 的回投路径（手动 `/compact`）也复用同一个函数渲染完成态文案，确保自动 / 紧急 / 手动三条路径的文案风格一致。

### config 改造（`src/forgecode/config/`）

- `ProviderConfig` 增加 `context_window: int = 0` 字段并支持从 YAML 读取（`yaml.safe_load` 后手动映射或 dataclass 自动 from_dict）。
- 新增 `effective_context_window(p)` 函数：配置 > 0 返回配置值；否则按 protocol 给默认值（anthropic→200000，openai→128000，其他 protocol→200000 作为保守默认）。
- `tests/test_config.py` 增加：未配置 / 配置为 0 / 配置为正数 / 未知 protocol 四种情况的断言。

### `.forgecode/config.yaml.example` 更新

在 providers 列表里给每个 provider 加上 `context_window` 示例值与注释：

```yaml
providers:
  - name: claude
    protocol: anthropic
    api_key: sk-ant-xxx
    model: claude-sonnet-4-5
    context_window: 200000   # 可选，未配置时按 protocol 默认（anthropic 200000、openai 128000）
```

## 模块交互

**正常路径（自动触发）：**

```
用户输入 (TUI)
    │ 非 / 开头
    ▼
Agent.run() asyncio task
    │
    ├─[迭代 N 开头]→ registry.definitions() / read_only_definitions() ──→ defs（本轮复用）
    │
    │   ┌─────────────────────────────────────────────────┐
    │   │            compact.manage_context               │
    │   │  ┌──────────────────────────────────────────┐   │
    │   │  │ 1. layer1.offload_and_snip               │   │
    │   │  │    - 查 ContentReplacementState 账本     │   │
    │   │  │    - 新 id：判断 single / aggregate      │   │
    │   │  │    - 落盘到 spill_dir/<tool_use_id>      │   │
    │   │  │    - 写入账本（冻结决策）                │   │
    │   │  └──────────────────────────────────────────┘   │
    │   │              │                                   │
    │   │              ▼                                   │
    │   │  ┌──────────────────────────────────────────┐   │
    │   │  │ 2. token.estimate_tokens                 │   │
    │   │  │    = anchor + chars / 3.5                │   │
    │   │  └──────────────────────────────────────────┘   │
    │   │              │                                   │
    │   │              ▼                                   │
    │   │  estimated >= window-20000-13000 且未熔断？      │
    │   │              │ 是                                │
    │   │              ▼                                   │
    │   │  ┌──────────────────────────────────────────┐   │
    │   │  │ 3. layer2.auto_compact                   │   │
    │   │  │    a. build_summary_prompt（无工具）     │   │
    │   │  │    b. provider.stream → <summary> 解析   │   │
    │   │  │    c. build_recovery_attachment(3 段)    │   │
    │   │  │    d. pick_recent_tail + 配对修正        │   │
    │   │  │    e. 拼接成 new_msgs                    │   │
    │   │  │    f. conversation.replace_history      │   │
    │   │  │    g. 成功→失败计数清零；失败→+1，熔断   │   │
    │   │  └──────────────────────────────────────────┘   │
    │   └─────────────────────────────────────────────────┘
    │
    ├─→ _stream_once: provider.stream(Request(messages, tools=defs))
    │       │
    │       ├─正常完成 → 读尾事件 usage → usage_anchor 更新
    │       │
    │       └─PromptTooLongError → 紧急压缩路径（见下）
    │
    └─→ _execute_batched 工具调用
            │
            └─ReadFile 成功 → asyncio.to_thread(read_bytes) → recovery.record_file
```

**紧急压缩路径（provider 撞墙）：**

```
provider.stream 投递 ev.err 命中 PromptTooLongError
    │
    ▼
_stream_once 返回 err（已累加的 text 不写入 Conversation，保证状态原子）
    │
    ▼
主循环:emergency_retried 已为 True? → 是:按错误上抛
    │ 否
    ▼
manage_context(trigger=EMERGENCY)
    │   - 跳过阈值检查、跳过熔断器
    │   - 先强制跑一次 offload_and_snip（layer1）把大工具结果挪走
    │   - 再 force_compact → run_summary → replace_history
    │     若 run_summary 内部撞 PTL → 走 F27 的 ptl_retry（不调 auto_tracking）
    ▼
重置锚点:runtime.usage_anchor=0、runtime.anchor_msg_len=0
重新估算:est = estimate_tokens(0, conv.messages(), 0)
    │
    ▼
est < context_window - MANUAL_SAFETY_MARGIN？
    ├─是 → emergency_retried=True → 重试本轮 _stream_once
    │       ├─成功 → 继续主循环
    │       └─再次 PTL → 按错误上抛,不再做第二次紧急压缩
    └─否 → 视为不可恢复,按错误上抛
```

**手动压缩路径：**

```
TUI 输入 "/compact"
    │
    ▼
dispatch_command 命中 → 不发 LLM
    │
    ▼
agent.run_force_compact
    │
    ▼
manage_context(trigger=MANUAL)
    │   - 同 Emergency 路径
    ▼
返回 (before, after)
    │
    ▼
TUI push 系统消息 "已压缩，token 从 X 降至 Y"
```

**摘要请求自身 PTL：**

```
summarize_once 收到 PromptTooLongError
    │
    ▼
group_by_user_turn(msgs) → groups
    │
    ├─第 1~3 次：每次丢最旧的 1 组 → 重试 summarize_once
    │
    └─第 4 次起：丢 math.ceil(len(剩余) * 0.2) 组 → 重试
        │
        ├─成功 → 返回
        └─groups 全空 → 抛错误（上层熔断计数 + 1）
```

## 文件组织

```
src/forgecode/compact/
├── __init__.py        — 重导出 manage_context / TriggerKind / 几个 State 类型
├── compact.py         — manage_context 主入口、TriggerKind 枚举、编排两层调用
├── layer1.py          — offload_and_snip / spill_single / build_preview
├── layer2.py          — auto_compact / force_compact / run_summary / summarize_once / ptl_retry / pick_recent_tail / group_by_user_turn
├── summary_prompt.py  — build_summary_prompt 模板 + serialize_conversation + extract_summary 解析
├── recovery.py        — FileReadRecord / RecoveryState / build_recovery_attachment / BOUNDARY_NOTICE
├── token.py           — estimate_tokens / usage_anchor / message_chars
├── state.py           — ContentReplacementState (decide_once) / CompactCircuitBreaker / SessionContext
└── const.py           — 全部硬编码常量

tests/compact/
├── test_compact.py        — manage_context 集成单测（fake_provider 驱动）
├── test_layer1.py         — 单条 / 聚合 / 幂等 / 决策冻结 / 落盘失败降级
├── test_layer2.py         — 摘要流程 / PTL 重试 / 熔断计数 / 近期原文边界 / 配对修正
├── test_summary_prompt.py — Prompt 文本断言 + <summary> 解析
├── test_recovery.py       — 文件快照排序 / 截断 / 工具集合一致性 / 并发写 / BOUNDARY_NOTICE 稳定
├── test_state.py          — 决策冻结 / 熔断计数 / 并发
└── test_token.py          — 锚点 + 字符增量 / usage 合并
```

`src/forgecode/agent/agent.py` 改动：
- 新增 `runtime: SessionRuntime | None` 关键字参数与 `self._run_lock: asyncio.Lock`；构造时若未传 runtime 给一个默认实例以便保留对现有测试的兼容。
- 把 `_stream_once` 签名改成返回 `(text, calls, usage, err)`；错误由内部从 `StreamEvent.err` 捕获。
- 主循环本轮迭代开头按 mode 选 `defs = registry.definitions()` 或 `read_only_definitions()`，同一份列表（`id(defs)` 不变）传给 `ManageInput.tool_defs` 与 `Request.tools`。
- 每轮 `_stream_once` 前 `await manage_context(in_)` with `trigger = TriggerKind.AUTO`。
- 主对话路径 `_stream_once` 完成后更新 `runtime.usage_anchor` 与 `runtime.anchor_msg_len`；摘要路径不更新。
- 在工具结果回填阶段对 ReadFile 调用 `asyncio.to_thread(Path(p).read_bytes)` 纯净字节并写入 `recovery`（同 task、`add_tool_results` 之前）。
- 捕获 `PromptTooLongError` → `manage_context(trigger=EMERGENCY)` → 重新估算后同迭代重试一次。
- 新增 `async def run_force_compact(self, conv, tool_defs) -> tuple[int, int]` 给 TUI 调；入口先 `async with self._run_lock:`。

`src/forgecode/agent/runtime.py`（新文件）：定义 `SessionRuntime` dataclass 与构造工厂。

`src/forgecode/agent/event.py`（新文件或修改 `__init__.py`）：定义 `CompactPhase`、`CompactEvent`；`Event` dataclass 追加 `compact: CompactEvent | None = None`。

`tests/agent/test_agent.py` 改动：
- 已有 `fake_provider` 扩展能力：① 在脚本最后一帧之前 yield `StreamEvent(usage=Usage(...))`；② 支持按调用次数 yield 错误（包括包装好的 `PromptTooLongError`）。
- 新增"撞墙后紧急压缩成功"与"紧急压缩后再次撞墙上抛"两个用例。

`src/forgecode/conversation.py` 改动：新增 `# 无需显式锁`；新增 `replace_history(new_messages)`，做深拷贝；已有 `add_xxx` / `messages` / `length` / `last_role` 全部加锁。

`tests/test_conversation.py` 改动：新增 `replace_history` 的直接断言用例。

`src/forgecode/llm/__init__.py` 改动：
- 新增 `class PromptTooLongError(Exception)` 哨兵异常。
- `ToolDefinition` 已是导出类型，无需改动。

`src/forgecode/llm/anthropic_provider.py` / `src/forgecode/llm/openai_provider.py` 改动：捕获 provider SDK 抛出的"上下文过长"错误（`anthropic.BadRequestError` 且 message 含 `prompt is too long`；`openai.BadRequestError` 且 `code == "context_length_exceeded"`），包装成 `PromptTooLongError(orig)` 并通过 `yield StreamEvent(err=wrapped)` 投递（async generator 错误走事件流，不直接 raise）。

`tests/llm/test_anthropic_provider.py` / `tests/llm/test_openai_provider.py`：注入 mock SDK 客户端，断言：① 典型 `prompt_too_long` / `context_length_exceeded` 被 stream 转换成 wrapped 错误投递到 `StreamEvent.err`；② `isinstance(ev.err, PromptTooLongError)` 命中且 `ev.err.__cause__` 是原 SDK 异常；③ 其他 4xx/5xx 错误不被错误地包装为 PTL。

`src/forgecode/tui/commands.py`（新文件）：`dispatch_command` + `handle_exit` / `handle_plan` / `handle_do` / `handle_compact` + 未知命令兜底。
`src/forgecode/tui/stream.py`：`submit()` 内原 `match/case` 改用 `dispatch_command` 调用；命令路径不调 `conv.add_user`，不写入对话历史。
`src/forgecode/tui/app.py`：`ForgeCodeApp` 新增 `runtime: SessionRuntime` 与 `agent: Agent` 字段；`__init__` 构造期一次性构造 Agent 并保存。
`tests/tui/test_tui.py`：① `/compact` 走命令路径不发 LLM；② `/unknown` 友好提示；③ 迁移后 `/exit` / `/plan` / `/do` 行为不回归三个用例。

`src/forgecode/config/config.py`：`ProviderConfig` 追加 `context_window: int = 0`，加 `effective_context_window(p)`；现有字段顺序与 yaml 键名不变。
`src/forgecode/config/protocol_defaults.py`（新文件）：`DEFAULT_ANTHROPIC_CONTEXT_WINDOW = 200000`、`DEFAULT_OPENAI_CONTEXT_WINDOW = 128000`。
`tests/test_config.py`：新增四种情况断言。

`src/forgecode/cli.py`：启动阶段调 `new_session_context(workspace)`、`ContentReplacementState()`、`RecoveryState()`、`CompactCircuitBreaker()`，组装为 `SessionRuntime`；待 provider 选定后注入 `effective_context_window(p)`；把 `SessionRuntime` 交给 `ForgeCodeApp`。

`scripts/smoke.py`（若存在）：同样按新签名构造 Agent；smoke 场景的 `context_window` 可固定 200000。

`.gitignore`：追加 `.forgecode/sessions/`，避免开发者跑一次 forgecode 后 `git status` 出现一大坨 session 子目录。

`.forgecode/config.yaml.example`：新增 `context_window` 字段示例与注释。

## 技术决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 包结构与命名 | `forgecode.compact` 单子包，子模块按职责拆分（layer1 / layer2 / recovery / token） | 上下文管理逻辑高度内聚，对外只暴露 `manage_context` 等少量函数。单子包简化导入路径，多模块保证可读性。再拆 sub-sub-package 会引入循环引用风险（layer2 既要 token 又要 recovery）。 |
| `ContentReplacementState` 临界区 | `offload_and_snip` 持 `_lock` 全程；账本读写不暴露给外部，杜绝 TOCTOU 翻转 | 账本对外只通过 `decide_once` 这一个高层方法操作（持锁 + 回调内决策 + 同临界区写入），消除"读账本→落盘→写账本"之间的并发翻转窗口。 |
| `CompactCircuitBreaker` 独立于 `ContentReplacementState` | 拆成两个 class | 熔断只用于自动路径，手动 / 紧急完全绕过；放一起会让"是否应该读熔断字段"在调用点变得模糊。两个 class 都内嵌 `# 无需显式锁` 保证并发安全。 |
| 9 部分 + 两阶段摘要 prompt 内嵌 | 直接写在 `summary_prompt.py` 的常量字符串里 | Prompt 是产品规范的一部分，不需要从外部加载；放代码里方便 review 与版本回滚。也避免在测试里读文件。9 个小节标题用固定字面字符串，便于 `extract_summary` 与单测匹配。 |
| 摘要请求不传 tools | `Request.tools = None` | 摘要本身是"压缩历史"的语义动作，模型不应该在摘要阶段发起新工具调用。保留 tools 会让模型混淆任务，且消耗额外 token。 |
| ReadFile 后用 `Path.read_bytes` 重读纯净字节 | 工具 worker task 内同步 `await asyncio.to_thread(...)` | 工具返回字符串带行号前缀（forgecode 现有实现），直接拿来做恢复段会让模型把行号当成代码的一部分。重读一次磁盘成本可忽略；同步顺序保证下一次 `manage_context` 能观察到本轮记录。 |
| 主循环本轮迭代开头算 `tool_defs` | 局部变量复用，不缓存到 Agent 字段 | F17 要求恢复段声明的工具集合和 stream 调用的 tools 严格一致。同一轮迭代按 mode 选好后，把同一份列表（`id(defs)` 相同）同时传给 `ManageInput.tool_defs` 与 `Request.tools`，引用一致即逐项一致。 |
| `estimate_tokens` 用 3.5 字符/token | 硬编码 `ESTIMATE_CHARS_PER_TOKEN=3.5` | 锚定真实 usage 已经是主力，字符比例只用于两次真实请求之间的近似。3.5 是英文+代码混合场景下的常用经验值，过细的差异会被锚点纠正。引入 `tiktoken` 会显著增加依赖与冷启动成本。 |
| 紧急压缩只重试一次 | 同迭代内 `emergency_retried` 锁定一次性重试 | 紧急压缩已经丢掉了一大段历史，如果重试还失败说明问题不是 token 而是其他（如单条 user 消息就超长）。多次重试只会让用户等更久。重试前必须重估 token 低于 `context_window - MANUAL_SAFETY_MARGIN`，否则视为不可恢复。 |
| `session_id` 不持久化 | 进程启动生成 `<unix_ts>-<short_random>`（`secrets.token_hex(4)`） | 单进程会话边界等于进程边界，不需要恢复。`.forgecode/sessions/` 留作调试副产物，外部脚本/用户决定清理时机。 |
| 阈值硬编码 + 仅 `context_window` 走 config | 单项 config 暴露 | `context_window` 由 provider 决定，跨 provider 必须可配。其余阈值若开放为配置会指数级放大测试矩阵，且没有跨用户的差异化需求。本章不开放为配置项；调整属于代码变更。 |
| Layer 1 落盘失败降级为不替换 | 不进 `_seen_ids`，下次重试 | 磁盘问题是瞬时的可恢复故障，不应该让对话因此中断。N6 错误隔离的直接体现。 |
| Layer 2 PTL 重试中按"用户提交 + 一组往返"分组 | `group_by_user_turn` 抽成独立函数 | F27 的语义保证最早被丢的是最旧的一整轮交互，不会把同一轮的 user/assistant/tool 拆成半截。独立函数便于单元测试。 |
| Conversation 内部 `RLock` + `replace_history` 深拷贝 | 加锁 + `copy.deepcopy(msgs)` | 摘要后 compact 把 `new_msgs` 交出去就不应该再被外部改动；Conversation 也不应该暴露内部列表引用。深拷贝在 25 轮 × 数百 KB 量级下耗时毫秒级，与摘要 LLM 请求耗时相比可忽略；不再做对象池。 |
| TUI 命令分发用 `dict[str, handler]` | 极简注册表（4 项：/exit、/plan、/do、/compact） | 本章只有这几个内置命令，O(1) 查找已经够用；`click` / `typer` 等命令框架不在本章范围。 |
| 命令路径不写入 conversation | UI 层 push 系统消息，不调 `conv.add_user` | `/compact` 等命令不属于对话语义，进入 conversation 会污染下一轮 LLM 输入。系统消息只在 TUI 视图层（`RichLog`）展示。 |
| 摘要 + 恢复段合并为一条 user 消息 | `run_summary` 输出新对话首条是单条 user，content 内嵌 9 部分摘要 + 三段恢复 | Anthropic 协议禁止 user/user 连续；分两条会导致 400 错误。合并后续接近期原文（无论首条是 user / assistant / tool 都不破坏交替）。摘要写在前、三段恢复紧随其后，全部装在一个 user.content 字符串里。 |
| `pick_recent_tail` 配对修正与 role 衔接 | 截断点前推 + 必要时插入 assistant 占位 | 截断点夹在 tool_use/tool_result 中间时，向前推到 tool_use 之前；若拼接后导致 summary(user) 紧接近期原文首条 user，则在 recovery 段后、近期原文前插入一条 assistant 衔接占位，保证 Anthropic user/assistant 交替约束。 |
| `ProviderConfig` 新增独立函数 `effective_context_window(p)` | 函数而非构造时折算 | 配置加载时不知道 protocol 默认值表，把默认值表收敛到函数里，让 config 加载逻辑保持纯字段映射。也便于后续追加新 protocol 默认值。Python dataclass 也可以做成 `@property`，但当前简单函数足够。 |
| `PromptTooLongError` 作为 `llm` 包哨兵异常 | `isinstance` 判断 | 不同 provider 抛出的具体异常结构差异大（`anthropic.BadRequestError` vs `openai.BadRequestError`），统一成单一异常后 agent 主循环只需要一处判断。anthropic/openai provider 通过 `yield StreamEvent(err=wrapped)` 把 PTL 错误投递到事件流，主循环从 `StreamEvent.err` 用 `isinstance` 检测；同时 `wrapped.__cause__ = orig` 保留原异常供调试。 |
| `context_window` 注入时机 | provider 选定后由 `forgecode.cli` 注入 `SessionRuntime`，本会话内不变 | forgecode 启动期 TUI 可能选 provider，等用户选定后才能确定 `context_window`；本章不支持运行期切 provider；切换 provider 等同于重新启动进程。 |
| `context_window` 下界检查 | 必须 > `SUMMARY_RESERVE + AUTO_SAFETY_MARGIN`（即 > 33000） | 低于此值时 `context_window - 33000` 为非正数，自动阈值判断永远成立，每轮都会触发摘要导致死循环；`manage_context` 在入口对 `context_window` 做 sanity check，过小时跳过自动 layer2 并写一条 `logging.warning`。 |