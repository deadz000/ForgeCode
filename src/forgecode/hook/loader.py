"""Hook 加载器：扫描两层 YAML、字段校验、Matcher 编译、合并去重。

所有加载错误一律 stderr 输出后继续启动，不阻断进程（N1/N9）。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import yaml

from forgecode.hook.engine import Engine
from forgecode.hook.event import is_blocking, parse_event
from forgecode.hook.rule import (
    Action,
    ActionType,
    AtomCondition,
    CombineMode,
    Condition,
    HttpAction,
    PromptAction,
    Rule,
    ShellAction,
    SubagentAction,
)
from forgecode.permission.matcher import (
    ExactMatcher,
    GlobMatcher,
    NotMatcher,
    RegexMatcher,
)

# 项目级 / 用户级配置文件相对路径
PROJECT_HOOKS_REL = ".forgecode/hooks.yaml"
USER_HOOKS_REL = ".forgecode/hooks.yaml"

_DURATION_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*([smh]?)$")


def load(project_root: str | Path) -> Engine | None:
    """扫描两层 YAML，构造 Engine；无任何 hook 时返回 None。"""
    project_path = Path(project_root) / PROJECT_HOOKS_REL
    user_path = Path.home() / USER_HOOKS_REL

    rules: list[Rule] = []
    sources: list[str] = []
    seen_names: set[str] = set()

    for path in (project_path, user_path):
        _load_one_file(path, rules, sources, seen_names)

    if not rules:
        return None
    return Engine(rules, sources)


def _load_one_file(path: Path, rules: list[Rule], sources: list[str], seen_names: set[str]) -> None:
    """加载单个 hooks.yaml：解析失败整文件跳过，单条失败跳过该条。"""
    if not path.exists():
        return
    try:
        text = path.read_text(encoding="utf-8")
        data = yaml.safe_load(text)
    except Exception as e:
        print(f"[hook] load error: {path}: {e}", file=sys.stderr)
        return

    if data is None:
        return
    if not isinstance(data, dict) or not isinstance(data.get("hooks"), list):
        print(f"[hook] load error: {path}: top-level 'hooks' list missing", file=sys.stderr)
        return

    for idx, raw in enumerate(data["hooks"]):
        rule = _compile_rule(path, idx, raw, seen_names)
        if rule is not None:
            rules.append(rule)
            if str(path) not in sources:
                sources.append(str(path))


def _compile_rule(path: Path, idx: int, raw: Any, seen_names: set[str]) -> Rule | None:
    """把单条 YAML hook dict 编译为 Rule；失败 stderr 后返回 None。"""
    if not isinstance(raw, dict):
        print(f"[hook] {path}: item #{idx} not an object, skipped", file=sys.stderr)
        return None

    name = raw.get("name")
    if not isinstance(name, str) or not name:
        print(f"[hook] {path}: item #{idx} missing name, skipped", file=sys.stderr)
        return None
    if name in seen_names:
        print(f'hook "{name}": duplicate name, skipped', file=sys.stderr)
        return None

    ev_str = raw.get("event")
    event = parse_event(ev_str) if isinstance(ev_str, str) else None
    if event is None:
        print(f'hook "{name}": unknown event "{ev_str}", skipped', file=sys.stderr)
        return None

    action = _compile_action(name, raw.get("action"))
    if action is None:
        return None

    condition, ok = _compile_condition(name, raw.get("if"))
    if not ok:
        return None

    async_flag = raw.get("async", False)
    if async_flag and is_blocking(event):
        print(
            f'hook "{name}": async not allowed for blocking events, skipped',
            file=sys.stderr,
        )
        return None

    timeout_s = 30.0
    t_val = raw.get("timeout")
    if t_val is not None:
        parsed = _parse_duration(t_val)
        if parsed is None:
            print(f'hook "{name}": invalid timeout {t_val!r}, skipped', file=sys.stderr)
            return None
        timeout_s = parsed

    rule = Rule(
        name=name,
        event=event,
        action=action,
        condition=condition,
        only_once=bool(raw.get("only_once", False)),
        asyncio_mode=bool(async_flag),
        timeout_s=timeout_s,
        source=str(path),
    )
    seen_names.add(name)
    return rule


def _compile_action(name: str, raw: Any) -> Action | None:
    """编译 action 对象：type + 各类型子字段校验。"""
    if not isinstance(raw, dict):
        print(f'hook "{name}": missing action, skipped', file=sys.stderr)
        return None

    atype = raw.get("type")
    if atype == ActionType.SHELL.value:
        command = raw.get("command")
        if not isinstance(command, str) or not command:
            print(f'hook "{name}": shell action needs command, skipped', file=sys.stderr)
            return None
        return Action(type=ActionType.SHELL, shell=ShellAction(command=command))

    if atype == ActionType.PROMPT.value:
        text = raw.get("text")
        if not isinstance(text, str):
            print(f'hook "{name}": prompt action needs text, skipped', file=sys.stderr)
            return None
        return Action(type=ActionType.PROMPT, prompt=PromptAction(text=text))

    if atype == ActionType.HTTP.value:
        url = raw.get("url")
        if not isinstance(url, str) or not url:
            print(f'hook "{name}": http action needs url, skipped', file=sys.stderr)
            return None
        headers_raw = raw.get("headers") or {}
        if not isinstance(headers_raw, dict):
            print(f'hook "{name}": http headers must be a dict, skipped', file=sys.stderr)
            return None
        headers = {str(k): str(v) for k, v in headers_raw.items()}
        body = raw.get("body")
        if body is not None and not isinstance(body, str):
            print(f'hook "{name}": http body must be a string, skipped', file=sys.stderr)
            return None
        method = raw.get("method") or "POST"
        return Action(
            type=ActionType.HTTP,
            http=HttpAction(url=url, method=str(method), headers=headers, body=body),
        )

    if atype == ActionType.SUBAGENT.value:
        agent_name = raw.get("agent_name")
        prompt = raw.get("prompt")
        if not isinstance(agent_name, str) or not agent_name:
            print(
                f'hook "{name}": subagent action needs agent_name, skipped',
                file=sys.stderr,
            )
            return None
        if not isinstance(prompt, str) or not prompt:
            print(f'hook "{name}": subagent action needs prompt, skipped', file=sys.stderr)
            return None
        return Action(
            type=ActionType.SUBAGENT,
            subagent=SubagentAction(agent_name=agent_name, prompt=prompt),
        )

    print(f'hook "{name}": unknown action type {atype!r}, skipped', file=sys.stderr)
    return None


def _compile_condition(name: str, raw_if: Any) -> tuple[Condition | None, bool]:
    """编译 if 条件表达式。返回 (condition_or_None, ok)；ok=False 表示需跳过该 hook。"""
    if raw_if is None:
        return None, True
    if not isinstance(raw_if, dict):
        print(f'hook "{name}": invalid if expression, skipped', file=sys.stderr)
        return None, False

    has_all = "all_of" in raw_if
    has_any = "any_of" in raw_if
    if has_all and has_any:
        print(
            f'hook "{name}": if cannot have both all_of and any_of, skipped',
            file=sys.stderr,
        )
        return None, False

    if has_all:
        mode = CombineMode.ALL_OF
        atom_list = raw_if["all_of"]
    elif has_any:
        mode = CombineMode.ANY_OF
        atom_list = raw_if["any_of"]
    else:
        print(
            f'hook "{name}": if must contain all_of or any_of, skipped',
            file=sys.stderr,
        )
        return None, False

    if not isinstance(atom_list, list):
        print(f'hook "{name}": {mode.value} must be a list, skipped', file=sys.stderr)
        return None, False

    atoms: list[AtomCondition] = []
    for a in atom_list:
        atom = _compile_atom(name, a)
        if atom is None:
            return None, False
        atoms.append(atom)
    return Condition(mode=mode, atoms=atoms), True


def _compile_atom(name: str, raw: Any) -> AtomCondition | None:
    """编译单条原子条件 {field, match}。"""
    if not isinstance(raw, dict):
        print(f'hook "{name}": invalid atom condition, skipped', file=sys.stderr)
        return None
    field_path = raw.get("field")
    if not isinstance(field_path, str) or not field_path:
        print(f'hook "{name}": atom missing field, skipped', file=sys.stderr)
        return None
    match = raw.get("match")
    if not isinstance(match, dict):
        print(f'hook "{name}": atom missing match, skipped', file=sys.stderr)
        return None
    matcher = _compile_match(name, match)
    if matcher is None:
        return None
    return AtomCondition(field=field_path, matcher=matcher)


def _compile_match(name: str, raw: dict[str, Any]) -> Any:
    """把 {type, value} / {type, inner} 编译为 permission.Matcher。

    hook 上下文中的 matcher 都作用于 payload 字段值，glob 统一走 match_path
    （is_command=False，段内 * 不跨 /）。tool_input.command 这类整串通配用 regex 表达。
    """
    mtype = raw.get("type")
    if mtype == "exact":
        value = raw.get("value")
        if not isinstance(value, str):
            print(f'hook "{name}": exact match needs string value, skipped', file=sys.stderr)
            return None
        return ExactMatcher(value)
    if mtype == "glob":
        value = raw.get("value")
        if not isinstance(value, str):
            print(f'hook "{name}": glob match needs string value, skipped', file=sys.stderr)
            return None
        return GlobMatcher(value, is_command=False)
    if mtype == "regex":
        value = raw.get("value")
        if not isinstance(value, str):
            print(f'hook "{name}": regex match needs string value, skipped', file=sys.stderr)
            return None
        try:
            return RegexMatcher(value, re.compile(value))
        except re.error as e:
            print(
                f'hook "{name}": invalid regex {value!r}: {e}, skipped',
                file=sys.stderr,
            )
            return None
    if mtype == "not":
        inner = raw.get("inner")
        if not isinstance(inner, dict):
            print(f'hook "{name}": not match needs inner, skipped', file=sys.stderr)
            return None
        inner_matcher = _compile_match(name, inner)
        if inner_matcher is None:
            return None
        return NotMatcher(inner_matcher)
    print(f'hook "{name}": unknown match type {mtype!r}, skipped', file=sys.stderr)
    return None


def _parse_duration(s: Any) -> float | None:
    """解析 '30s' / '5m' / '1h' / 裸浮点秒；失败返回 None。"""
    if isinstance(s, (int, float)):
        return float(s)
    if not isinstance(s, str):
        return None
    m = _DURATION_RE.match(s.strip())
    if not m:
        return None
    val = float(m.group(1))
    unit = m.group(2)
    if unit == "m":
        val *= 60
    elif unit == "h":
        val *= 3600
    return val
