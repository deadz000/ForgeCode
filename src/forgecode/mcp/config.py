"""MCP 客户端：配置加载、变量展开、字段校验。"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml

# ── 对外类型 ──────────────────────────────────────


@dataclass
class ServerConfig:
    """单个 MCP server 的完整定义（已展开 ${VAR}、已校验）。"""

    type: Literal["stdio", "http"]
    command: str = ""  # stdio 必填
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    url: str = ""  # http 必填
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class Config:
    """mcp_servers 在内存中的归一化形式（已合并）。"""

    servers: dict[str, ServerConfig] = field(default_factory=dict)


# ── 内部类型 ──────────────────────────────────────


@dataclass
class _RawServer:
    type: str | None = None
    command: str | None = None
    args: list[str] | None = None
    env: dict[str, str] | None = None
    url: str | None = None
    headers: dict[str, str] | None = None


# ── 配置加载 ──────────────────────────────────────


def load_config(root: str) -> Config:
    """加载并合并两层 MCP 配置，永不抛出。"""
    # 用户级
    user_servers: dict[str, _RawServer] = {}
    try:
        user_path = Path.home() / ".forgecode" / "mcp.yaml"
    except Exception:
        user_path = None
    if user_path is not None:
        user_servers = _load_file(user_path)

    # 项目级
    project_path = Path(root) / ".forgecode" / "mcp.yaml"
    project_servers = _load_file(project_path)

    # 对每层做变量展开
    for name, srv in user_servers.items():
        _apply_expansion(name, srv)
    for name, srv in project_servers.items():
        _apply_expansion(name, srv)

    # 合并
    merged = _merge_servers(user_servers, project_servers)

    # 校验 → 组装 Config
    result: dict[str, ServerConfig] = {}
    for name, srv in merged.items():
        validated = _validate_server(name, srv)
        if validated is not None:
            result[name] = validated

    return Config(servers=result)


# ── 文件加载 ──────────────────────────────────────


def _load_file(path: Path) -> dict[str, _RawServer]:
    """加载 YAML 中的 mcp_servers 段。不存在 / 格式非法 → 返回空 {}。"""
    if not path.exists():
        return {}

    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        _warn(f"load {path} failed: {e}")
        return {}

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        _warn(f"load {path} failed: {e}")
        return {}

    if not isinstance(data, dict):
        return {}

    raw = data.get("mcp_servers")
    if not isinstance(raw, dict):
        return {}

    result: dict[str, _RawServer] = {}
    for name, item in raw.items():
        if not isinstance(item, dict):
            continue
        result[str(name)] = _RawServer(
            type=item.get("type"),
            command=item.get("command"),
            args=_parse_str_list(item.get("args")),
            env=_parse_str_map(item.get("env")),
            url=item.get("url"),
            headers=_parse_str_map(item.get("headers")),
        )
    return result


# ── 变量展开 ──────────────────────────────────────

_EXPAND_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _expand_vars(s: str) -> tuple[str, list[str]]:
    """展开 ${VAR} → 环境变量值；返回 (结果, 未定义变量列表)。"""
    undefined: list[str] = []

    def _replace(m: re.Match[str]) -> str:
        var = m.group(1)
        if var in os.environ:
            return os.environ[var]
        undefined.append(var)
        return ""

    return _EXPAND_RE.sub(_replace, s), undefined


def _apply_expansion(name: str, srv: _RawServer) -> None:
    """对 env / headers 的值做变量展开，原地修改。"""
    warned: set[str] = set()

    if srv.env:
        for k, v in list(srv.env.items()):
            expanded, undef = _expand_vars(v)
            srv.env[k] = expanded
            for var in undef:
                if var not in warned:
                    warned.add(var)
                    _warn(f"undefined env var ${{{var}}} referenced by server {name}")

    if srv.headers:
        for k, v in list(srv.headers.items()):
            expanded, undef = _expand_vars(v)
            srv.headers[k] = expanded
            for var in undef:
                if var not in warned:
                    warned.add(var)
                    _warn(f"undefined env var ${{{var}}} referenced by server {name}")


# ── 合并 ──────────────────────────────────────────


def _merge_servers(user: dict[str, _RawServer], project: dict[str, _RawServer]) -> dict[str, _RawServer]:
    """server 名维度合并：project 层同名完整覆盖 user 层。"""
    result = dict(user)
    result.update(project)
    return result


# ── 校验 ──────────────────────────────────────────


def _validate_server(name: str, srv: _RawServer) -> ServerConfig | None:
    """校验并转换为 ServerConfig；非法返回 None。"""
    stype = srv.type
    if stype not in ("stdio", "http"):
        _warn(f"skip server {name}: type must be 'stdio' or 'http', got {stype!r}")
        return None

    if stype == "stdio":
        cmd = srv.command
        if not cmd or not isinstance(cmd, str):
            _warn(f"skip server {name}: stdio type requires 'command'")
            return None
        return ServerConfig(
            type="stdio",
            command=cmd,
            args=srv.args or [],
            env=srv.env or {},
        )

    # http
    url = srv.url
    if not url or not isinstance(url, str):
        _warn(f"skip server {name}: http type requires 'url'")
        return None
    return ServerConfig(
        type="http",
        url=url,
        headers=srv.headers or {},
    )


# ── 辅助 ──────────────────────────────────────────


def _parse_str_list(val: object) -> list[str]:
    if not isinstance(val, list):
        return []
    return [str(v) for v in val]


def _parse_str_map(val: object) -> dict[str, str]:
    if not isinstance(val, dict):
        return {}
    return {str(k): str(v) for k, v in val.items()}


def _warn(msg: str) -> None:
    print(f"[mcp] warn: {msg}", file=sys.stderr)
