"""权限规则：Rule/RuleSet、parse_rule、匹配器工厂。

匹配语法扩展（与 ch08 共用底层匹配器）：
  - `Bash(git *)`           glob（缺省，向后兼容）
  - `Bash(=git status)`     精确（整串相等）
  - `Bash(!inner)`          反向（对 inner 取反，支持 `!=value`、`!~regex`、`!glob`）
  - `Bash(~regex)`          正则（search 语义）
"""

from __future__ import annotations

from dataclasses import dataclass, field

from forgecode.permission import Decision
from forgecode.permission.matcher import Matcher, compile_matcher


@dataclass
class Rule:
    tool: str  # 友好名：Bash/Read/Write/Edit/Glob/Grep
    matcher: Matcher | None  # None 表示该工具全匹配
    allow: bool  # True=allow, False=deny
    raw: str = ""  # 原始描述串，仅供错误日志与调试


@dataclass
class RuleSet:
    allow: list[Rule] = field(default_factory=list)
    deny: list[Rule] = field(default_factory=list)

    def match(self, friendly: str, target: str) -> tuple[Decision, bool]:
        """先 deny 再 allow；返回 (Allow|Deny, 命中?)。"""
        for r in self.deny:
            if r.tool == friendly and _match_rule(r, target):
                return Decision.DENY, True
        for r in self.allow:
            if r.tool == friendly and _match_rule(r, target):
                return Decision.ALLOW, True
        return Decision.ALLOW, False


def _match_rule(r: Rule, target: str) -> bool:
    """匹配单条规则：matcher 为 None 表示该工具全匹配。"""
    if r.matcher is None:
        return True
    return r.matcher.match(target)


def parse_rule(s: str) -> tuple[Rule | None, str | None]:
    """解析 'Tool(pattern)' 或 'Tool' 格式的规则字符串。

    返回 (rule, err)；解析失败时 (None, err)。调用方负责把 err 打到 stderr。
    """
    s = s.strip()
    if not s:
        return None, "empty rule"

    # 查找括号
    idx = s.find("(")
    if idx < 0:
        return Rule(tool=s, matcher=None, allow=True, raw=s), None

    if not s.endswith(")"):
        return None, f"unclosed parenthesis: {s}"

    tool = s[:idx].strip()
    pattern = s[idx + 1 : -1].strip()
    if not tool:
        return None, "empty tool"

    if not pattern:
        return Rule(tool=tool, matcher=None, allow=True, raw=s), None

    try:
        matcher = compile_matcher(pattern, is_command=(tool == "Bash"))
    except ValueError as e:
        return None, str(e)

    return Rule(tool=tool, matcher=matcher, allow=True, raw=s), None


def escape_glob(s: str) -> str:
    """转义 glob 元字符 * ? [ ]，供自动生成的精确规则使用。"""
    for ch in "*?[]":
        s = s.replace(ch, "\\" + ch)
    return s
