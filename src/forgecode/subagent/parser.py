"""SubAgent 角色定义解析：frontmatter + body → Definition。

与 skills/parser.py 的 frontmatter 解析几乎一致，独立实现避免跨包依赖。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import yaml

from forgecode.permission import Mode, parse_mode
from forgecode.subagent.definition import Definition, Source

# 角色名：字母/数字/连字符/下划线，长度 1-32，允许大写（Explore / Plan）
AGENT_NAME_REGEX = re.compile(r"^[A-Za-z][A-Za-z0-9\-_]{0,31}$")

_MODEL_TIERS = {"inherit", "haiku", "sonnet", "opus"}


def parse_frontmatter_and_body(data: str) -> tuple[dict[str, Any], str]:
    """解析以 --- 开头的 YAML frontmatter 与正文。失败抛 ValueError。"""
    lines = data.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("agent 定义必须以 --- 开头的 YAML frontmatter 开始")

    end = -1
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end < 0:
        raise ValueError("agent frontmatter 缺少结束 ---")

    frontmatter = "\n".join(lines[1:end])
    parsed = yaml.safe_load(frontmatter) or {}
    if not isinstance(parsed, dict):
        raise ValueError("agent frontmatter 必须是 YAML 对象")

    body_lines = lines[end + 1 :]
    while body_lines and not body_lines[0].strip():
        body_lines.pop(0)
    body = "\n".join(body_lines)
    return parsed, body


def parse_definition(data: bytes, file_path: str, source: Source) -> Definition:
    """解析角色定义文件字节流为 Definition。字段非法时 stderr 警告并降级。"""
    try:
        text = data.decode("utf-8-sig")  # 去 BOM
    except UnicodeDecodeError:
        text = data.decode("utf-8", errors="replace")

    try:
        fm, body = parse_frontmatter_and_body(text)
    except ValueError as e:
        raise ValueError(f"{file_path}: {e}") from e

    name = str(fm.get("name", "")).strip()
    if not name or not AGENT_NAME_REGEX.fullmatch(name):
        raise ValueError(f"{file_path}: 非法 name {name!r}")
    description = str(fm.get("description", "")).strip()
    if not description:
        raise ValueError(f"{file_path}: description 不能为空")

    # tools / disallowedTools 白名单黑名单
    tools = _str_list(fm.get("tools"), f"{name}.tools")
    disallowed = _str_list(fm.get("disallowedTools"), f"{name}.disallowedTools")

    # model：非法档位警告并降级 inherit
    model_raw = str(fm.get("model") or "").strip()
    model: str = model_raw if model_raw in _MODEL_TIERS else "inherit"
    if model_raw and model_raw not in _MODEL_TIERS:
        print(
            f'subagent "{name}": unknown model {model_raw!r}, defaulting to inherit',
            file=sys.stderr,
        )

    # maxTurns
    max_turns_raw = fm.get("maxTurns") or 0
    try:
        max_turns = int(max_turns_raw)
    except (TypeError, ValueError):
        print(f'subagent "{name}": invalid maxTurns {max_turns_raw!r}, defaulting to 0', file=sys.stderr)
        max_turns = 0

    # permissionMode：dontAsk 单独识别；未知值警告并降级 default
    mode_str = str(fm.get("permissionMode") or "").strip()
    dont_ask = False
    permission_mode = Mode.DEFAULT
    if mode_str == "dontAsk":
        dont_ask = True
    elif mode_str:
        m, ok = parse_mode(mode_str)
        if not ok:
            print(
                f'subagent "{name}": unknown permissionMode {mode_str!r}, defaulting to default',
                file=sys.stderr,
            )
        else:
            permission_mode = m

    background = bool(fm.get("background") or False)

    # isolation：合法值 "" / "worktree"，非法值警告并回落 ""
    isolation_raw = str(fm.get("isolation") or "").strip()
    isolation: str = isolation_raw if isolation_raw in ("", "worktree") else ""
    if isolation_raw and isolation_raw not in ("", "worktree"):
        print(
            f'subagent "{name}": unknown isolation {isolation_raw!r}, defaulting to no isolation',
            file=sys.stderr,
        )

    return Definition(
        name=name,
        description=description,
        tools=tools,
        disallowed_tools=disallowed,
        model=model,  # type: ignore[arg-type]
        max_turns=max_turns,
        permission_mode=permission_mode,
        dont_ask=dont_ask,
        background=background,
        isolation=isolation,
        system_prompt=body,
        file_path=file_path,
        source=source,
    )


def parse_file(path: str, source: Source) -> Definition:
    """按路径读取并解析一个角色定义文件。"""
    return parse_definition(Path(path).read_bytes(), path, source)


def _str_list(value: Any, label: str) -> list[str]:
    """把 frontmatter 字段规范为字符串列表；非法元素跳过。"""
    if value is None:
        return []
    if not isinstance(value, list):
        print(f"subagent {label}: must be a list, skipped", file=sys.stderr)
        return []
    out: list[str] = []
    for x in value:
        if isinstance(x, str) and x:
            out.append(x)
        else:
            print(f"subagent {label}: invalid item {x!r}, skipped", file=sys.stderr)
    return out
