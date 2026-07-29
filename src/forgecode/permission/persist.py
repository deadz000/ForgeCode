"""权限持久化：永久放行规则写入本地层配置文件。"""

from __future__ import annotations

import os
from pathlib import Path

import yaml

from forgecode.conversation.history import ToolCall
from forgecode.permission.engine import Engine
from forgecode.permission.settings import (
    Settings,
    extract_target,
    friendly_name,
    load_settings,
    parse_rule,
)


def rule_for(call: ToolCall, root: str) -> tuple[str, bool]:
    """为一次工具调用生成精确 allow 规则字符串。返回 (rule_str, ok)。"""
    friendly = friendly_name(call.name)
    target, is_file, ok = extract_target(call)

    if not ok:
        return "", False

    if call.name == "bash":
        # 将命令中的 glob 元字符转义，防止被误解析为通配
        escaped = _escape_glob_metachars(target)
        return f"{friendly}({escaped})", True

    if is_file:
        # 转换为相对 root 的路径
        try:
            rel = os.path.relpath(target, root)
        except ValueError:
            rel = target
        rel = rel.replace("\\", "/")
        return f"{friendly}({rel})", True

    return "", False


def _escape_glob_metachars(s: str) -> str:
    """转义 glob 元字符 * ? [ ]。"""
    for ch in "*?[]":
        s = s.replace(ch, "\\" + ch)
    return s


def persist_local_allow(engine: Engine, call: ToolCall) -> None:
    """永久放行：把精确 allow 规则写入本地层配置文件 + 同步内存。"""
    rule_str, ok = rule_for(call, engine.root)
    if not ok:
        return

    r, rok = parse_rule(rule_str)
    if not rok:
        return
    r.allow = True

    # 加载/创建本地层文件
    local_file = Path(engine.local_path)
    settings = _load_or_create(local_file)

    # 去重追加
    existing = set(settings.permissions.allow)
    if rule_str not in existing:
        settings.permissions.allow.append(rule_str)

    # 写回文件
    local_file.parent.mkdir(parents=True, exist_ok=True)
    yaml_data = {
        "default_mode": str(engine.start_mode()),
        "permissions": {
            "allow": settings.permissions.allow,
            "deny": settings.permissions.deny,
        },
    }
    local_file.write_text(
        yaml.dump(yaml_data, allow_unicode=True, default_flow_style=False),
        encoding="utf-8",
    )

    # 同步内存
    if not any(existing.tool == r.tool and existing.pattern == r.pattern for existing in engine.local.allow):
        engine.local.allow.append(r)


def _load_or_create(path: Path) -> Settings:
    """加载配置，缺失则返回空。"""
    try:
        return load_settings(str(path))
    except Exception:
        return Settings()
