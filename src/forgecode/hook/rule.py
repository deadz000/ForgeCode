"""Hook 数据结构：Rule / Condition / Action / Payload。"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from forgecode.hook.event import Event

if TYPE_CHECKING:
    from forgecode.permission.matcher import Matcher

# 事件分派时携带的上下文数据；条件求值与动作输入都用它。
# 序列化为 JSON 时保证 key 字典序（N6）用 json.dumps(payload, sort_keys=True)。
Payload = dict[str, Any]


class CombineMode(str, enum.Enum):  # noqa: UP042 — str 枚举便于与 YAML 字面量直接对应
    """条件组合方式：all_of / any_of 二选一，不允许混用。"""

    ALL_OF = "all_of"
    ANY_OF = "any_of"


class ActionType(str, enum.Enum):  # noqa: UP042 — str 枚举便于与 YAML 字面量直接对应
    """动作类型：shell / prompt / http / subagent。"""

    SHELL = "shell"
    PROMPT = "prompt"
    HTTP = "http"
    SUBAGENT = "subagent"


@dataclass
class AtomCondition:
    """单条原子条件：字段路径 + 匹配器。"""

    field: str  # 形如 "tool_input.path"
    matcher: Matcher  # 复用 permission.Matcher


@dataclass
class Condition:
    """条件表达式：mode 二选一 + 原子条件数组。"""

    mode: CombineMode  # CombineMode.ALL_OF 或 ANY_OF
    atoms: list[AtomCondition]


@dataclass
class ShellAction:
    """shell 动作：由 sh -c 解释执行，payload 经 stdin 传入。"""

    command: str


@dataclass
class PromptAction:
    """prompt 动作：文本注入下一次 LLM 请求的 reminder 区。"""

    text: str


@dataclass
class HttpAction:
    """http 动作：发送请求，可选 body 模板。"""

    url: str
    method: str = "POST"
    headers: dict[str, str] = field(default_factory=dict)
    body: str | None = None  # 模板字符串；None 表示用 payload JSON


@dataclass
class SubagentAction:
    """subagent 动作：本期占位，仅加载校验。"""

    agent_name: str
    prompt: str


@dataclass
class Action:
    """动作容器：type + 各类型独有字段。"""

    type: ActionType
    shell: ShellAction | None = None
    prompt: PromptAction | None = None
    http: HttpAction | None = None
    subagent: SubagentAction | None = None


@dataclass
class Rule:
    """一条已加载的 hook 规则。"""

    name: str
    event: Event
    action: Action
    condition: Condition | None = None  # None 表示无条件
    only_once: bool = False
    asyncio_mode: bool = False  # 对应 YAML 的 `async`（避免与 Python 关键字冲突）
    timeout_s: float = 30.0
    source: str = ""  # 来源文件路径，供 /hooks 显示
