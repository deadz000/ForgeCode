"""配置加载：YAML 设置、友好名映射、工具分类、参数提取。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from forgecode.conversation.history import ToolCall
from forgecode.permission import Category
from forgecode.permission.rule import RuleSet, parse_rule


@dataclass
class PermissionsBlock:
    allow: list[str] = field(default_factory=list)
    deny: list[str] = field(default_factory=list)


@dataclass
class Settings:
    default_mode: str = ""
    permissions: PermissionsBlock = field(default_factory=PermissionsBlock)


class SettingsError(Exception):
    """配置文件格式错误（非致命，调用方降级）。"""

    pass


def load_settings(path: str) -> Settings:
    """加载 YAML 配置文件。文件不存在→空；格式非法→抛出 SettingsError。"""
    p = Path(path)
    if not p.exists():
        return Settings()

    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
    except Exception as e:
        raise SettingsError(f"读取配置文件失败 {path}: {e}") from e

    if data is None:
        return Settings()
    if not isinstance(data, dict):
        raise SettingsError(f"配置文件顶层应为字典: {path}")

    permissions_data = data.get("permissions", {})
    if not isinstance(permissions_data, dict):
        raise SettingsError(f"permissions 应为字典: {path}")

    return Settings(
        default_mode=str(data.get("default_mode", "")),
        permissions=PermissionsBlock(
            allow=_parse_str_list(permissions_data.get("allow")),
            deny=_parse_str_list(permissions_data.get("deny")),
        ),
    )


def _parse_str_list(val: object) -> list[str]:
    """安全解析字符串列表。"""
    if not isinstance(val, list):
        return []
    return [str(v) for v in val if isinstance(v, str)]


def to_rule_set(s: Settings) -> RuleSet:
    """将 Settings 转换为 RuleSet（跳过非法规则条目）。"""
    rs = RuleSet()
    for entry in s.permissions.allow:
        r, ok = parse_rule(entry)
        if ok:
            r.allow = True
            rs.allow.append(r)
    for entry in s.permissions.deny:
        r, ok = parse_rule(entry)
        if ok:
            r.allow = False
            rs.deny.append(r)
    return rs


# ── 友好名映射 ────────────────────────────────────

_FRIENDLY_MAP: dict[str, str] = {
    "bash": "Bash",
    "read_file": "Read",
    "write_file": "Write",
    "edit_file": "Edit",
    "glob": "Glob",
    "grep": "Grep",
}


def friendly_name(internal: str) -> str:
    """内部名→友好名；未知原样返回。"""
    return _FRIENDLY_MAP.get(internal, internal)


# ── 工具分类 ──────────────────────────────────────


def categorize(internal: str, read_only: bool) -> Category:
    """判定工具类别（N7 最严：未知按 EXEC）。"""
    if read_only:
        return Category.READ
    if internal in ("write_file", "edit_file"):
        return Category.WRITE
    # bash + 未知工具 → EXEC
    return Category.EXEC


# ── 参数提取 ──────────────────────────────────────


def extract_target(call: ToolCall) -> tuple[str, bool, bool]:
    """从工具调用中提取目标字符串。返回 (target, is_file, ok)。"""
    try:
        data = json.loads(call.input) if isinstance(call.input, str) else call.input
    except json.JSONDecodeError:
        return ("", False, False)
    if not isinstance(data, dict):
        return ("", False, False)

    name = call.name

    if name == "bash":
        command = data.get("command", "")
        if not isinstance(command, str):
            return ("", False, False)
        return (command, False, True)

    if name in ("read_file", "write_file", "edit_file"):
        path = data.get("path", "")
        if not isinstance(path, str) or not path:
            return ("", False, False)
        return (path, True, True)

    if name in ("glob", "grep"):
        path = data.get("path", ".")
        if not isinstance(path, str):
            path = "."
        return (path, True, True)

    # 未知工具
    return ("", False, False)
