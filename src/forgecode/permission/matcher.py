"""规则匹配器：精确 / glob / 正则 / 反向四种类型的统一接口。

供权限规则与 Hook 条件表达式共用同一套匹配语义（N7）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol


class Matcher(Protocol):
    """规则匹配的统一接口；四种实现：ExactMatcher / GlobMatcher / RegexMatcher / NotMatcher。"""

    def match(self, s: str) -> bool: ...
    def __str__(self) -> str: ...  # 调试 / /hooks 输出用


@dataclass(frozen=True)
class ExactMatcher:
    """精确匹配：整串相等。"""

    value: str

    def match(self, s: str) -> bool:
        return s == self.value

    def __str__(self) -> str:
        return f"={self.value}"


@dataclass(frozen=True)
class GlobMatcher:
    """glob 匹配：command 模式走 match_command（整串通配），否则走 match_path。"""

    pattern: str
    is_command: bool  # True 走 match_command，False 走 match_path

    def match(self, s: str) -> bool:
        if self.is_command:
            return match_command(self.pattern, s)
        return match_path(self.pattern, s)

    def __str__(self) -> str:
        return self.pattern


@dataclass(frozen=True)
class RegexMatcher:
    """正则匹配：search 语义（子串命中即 True）。"""

    src: str
    compiled: re.Pattern[str]

    def match(self, s: str) -> bool:
        return self.compiled.search(s) is not None

    def __str__(self) -> str:
        return f"~{self.src}"


@dataclass(frozen=True)
class NotMatcher:
    """反向匹配：对 inner matcher 取反。"""

    inner: Matcher

    def match(self, s: str) -> bool:
        return not self.inner.match(s)

    def __str__(self) -> str:
        return f"!{self.inner}"


def compile_matcher(pattern: str, *, is_command: bool) -> Matcher:
    """解析单条匹配描述串，返回 Matcher。失败抛 ValueError。

    描述串规则：
      "=value"  -> ExactMatcher
      "~regex"  -> RegexMatcher
      "!inner"  -> NotMatcher（对 compile_matcher(inner) 取反，支持嵌套）
      "value"   -> GlobMatcher（沿用现有 wildcard / match_path 语义）
    """
    if not pattern:
        raise ValueError("empty matcher pattern")
    head, rest = pattern[0], pattern[1:]
    if head == "=":
        return ExactMatcher(rest)
    if head == "~":
        try:
            return RegexMatcher(rest, re.compile(rest))
        except re.error as e:
            raise ValueError(f"invalid regex: {e}") from e
    if head == "!":
        return NotMatcher(compile_matcher(rest, is_command=is_command))
    return GlobMatcher(pattern, is_command)


# ── glob 匹配底层（由 rule.py 迁入，语义不变）──────────────────


def match_command(pattern: str, target: str) -> bool:
    """命令串匹配：* 匹配任意字符含空格，** 等价 *；按空格分段对齐。"""
    if not pattern:
        return True

    pattern = pattern.replace("**", "*")
    pattern_segs = pattern.split()
    target_segs = target.split()
    if len(pattern_segs) != len(target_segs):
        return False
    for ps, ts in zip(pattern_segs, target_segs, strict=False):
        if not _glob_match(ps, ts):
            return False
    return True


def match_path(pattern: str, target: str) -> bool:
    """文件路径匹配：* 段内、** 跨段。"""
    if not pattern:
        return True
    return _match_path_segments(pattern, target)


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
