"""权限规则：Rule/RuleSet、parse_rule、glob 匹配。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from forgecode.permission import Decision


@dataclass
class Rule:
    tool: str  # 友好名：Bash/Read/Write/Edit/Glob/Grep
    pattern: str  # 模式段；"" 匹配该工具全部调用
    allow: bool  # True=allow, False=deny


@dataclass
class RuleSet:
    allow: list[Rule] = field(default_factory=list)
    deny: list[Rule] = field(default_factory=list)

    def match(self, friendly: str, target: str) -> tuple[Decision, bool]:
        """先 deny 再 allow；返回 (Allow|Deny, 命中?)。"""
        for r in self.deny:
            if r.tool == friendly and _match_pattern(r.pattern, target):
                return Decision.DENY, True
        for r in self.allow:
            if r.tool == friendly and _match_pattern(r.pattern, target):
                return Decision.ALLOW, True
        return Decision.ALLOW, False


def parse_rule(s: str) -> tuple[Rule, bool]:
    """解析 'Tool(pattern)' 或 'Tool' 格式的规则字符串。"""
    s = s.strip()
    if not s:
        return Rule("", "", False), False

    # 查找括号
    idx = s.find("(")
    if idx < 0:
        return Rule(tool=s, pattern="", allow=True), True

    if not s.endswith(")"):
        return Rule("", "", False), False

    tool = s[:idx].strip()
    pattern = s[idx + 1 : -1].strip()
    if not tool:
        return Rule("", "", False), False

    return Rule(tool=tool, pattern=pattern, allow=True), True


def _match_pattern(pattern: str, target: str) -> bool:
    """glob 匹配：空模式匹配一切；* 段内 / ** 跨段（仅文件路径）。"""
    if not pattern:
        return True

    # 文件路径按 / 分段匹配
    if "/" in target or "/" in pattern:
        return _match_path_segments(pattern, target)

    # 命令串匹配：* 匹配任意字符含空格，** 等价 *
    pattern = pattern.replace("**", "*")
    # 按空格分段
    pattern_segs = pattern.split()
    target_segs = target.split()
    if len(pattern_segs) != len(target_segs):
        return False
    for ps, ts in zip(pattern_segs, target_segs, strict=False):
        if not _glob_match(ps, ts):
            return False
    return True


def _match_path_segments(pattern: str, target: str) -> bool:
    """文件路径按 / 分段匹配，** 跨段。"""
    pat_segs = pattern.split("/")
    tgt_segs = target.split("/")

    # 递归匹配
    return _seg_match(pat_segs, 0, tgt_segs, 0)


def _seg_match(
    pat_segs: list[str],
    pi: int,
    tgt_segs: list[str],
    ti: int,
) -> bool:
    if pi == len(pat_segs):
        return ti == len(tgt_segs)
    if pat_segs[pi] == "**":
        # ** 匹配 0 或多个段
        for k in range(ti, len(tgt_segs) + 1):
            if _seg_match(pat_segs, pi + 1, tgt_segs, k):
                return True
        return False
    if ti >= len(tgt_segs):
        return False
    if not _glob_match(pat_segs[pi], tgt_segs[ti]):
        return False
    return _seg_match(pat_segs, pi + 1, tgt_segs, ti + 1)


def _glob_match(pat: str, seg: str) -> bool:
    """单段 glob 匹配：* 匹配任意字符。"""
    if not pat:
        return not seg
    # 转义 glob 为正则
    regex = "^" + re.escape(pat).replace(r"\*", ".*") + "$"
    return bool(re.match(regex, seg))
