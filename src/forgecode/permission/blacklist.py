"""危险命令黑名单（启发式、非完备、不可配置放开——N1）。"""

import re

# 黑名单正则列表（内置常量，任何配置/模式无法增删或关闭）
_BLACKLIST: list[re.Pattern] = [
    # rm -rf / ~ $HOME /*
    re.compile(r"rm\s+(-[a-zA-Z]*[rf][a-zA-Z]*\s+)+(/|~|\$HOME|/\*)"),
    # dd of=/dev/*
    re.compile(r"dd\s+.*of=/dev/[a-zA-Z]"),
    # fork bomb :(){ :|:& };:
    re.compile(r":[\(\)]\s*\{.*\|.*&\s*\};?\s*:"),
    # mkfs.*
    re.compile(r"\bmkfs\."),
    # redirect > /dev/sd* /dev/nvme* /dev/hd* /dev/disk*
    re.compile(r">\s*/dev/(sd|hd|nvme|disk)"),
    # chmod -R 777 /
    re.compile(r"chmod\s+-R\s+0?777\s+/"),
    # format C: / D: (Windows)
    re.compile(r"format\s+[A-Z]:", re.IGNORECASE),
]


def hits_blacklist(command: str) -> bool:
    """检查命令是否命中黑名单。"""
    return any(p.search(command) for p in _BLACKLIST)
