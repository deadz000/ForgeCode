"""MCP 配置加载单测：两层合并、变量展开、字段校验、降级。"""

from __future__ import annotations

from pathlib import Path

import yaml

from forgecode.mcp.config import (
    Config,
    _apply_expansion,
    _expand_vars,
    _load_file,
    _merge_servers,
    _RawServer,
    _validate_server,
    load_config,
)

# ── T2.1: 两层合并 ─────────────────────────────────


def test_load_config_no_files():
    """两文件都不存在 → Config.servers 为空。"""
    cfg = load_config("/nonexistent/path")
    assert isinstance(cfg, Config)
    assert cfg.servers == {}


def test_load_config_user_only(tmp_path, monkeypatch):
    """仅用户级文件存在 → 加载成功。"""
    user_dir = tmp_path / ".forgecode"
    user_dir.mkdir()
    user_file = user_dir / "mcp.yaml"
    user_file.write_text(
        yaml.dump({"mcp_servers": {"s1": {"type": "stdio", "command": "echo"}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    cfg = load_config("/nonexistent-project")
    assert "s1" in cfg.servers
    assert cfg.servers["s1"].type == "stdio"
    assert cfg.servers["s1"].command == "echo"


def test_load_config_project_only(tmp_path, monkeypatch):
    """仅项目级文件存在 → 加载成功。"""
    # 让用户级路径指向不存在的目录
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "no-home")

    project_dir = tmp_path / "project"
    project_dir.mkdir(parents=True)
    mcp_dir = project_dir / ".forgecode"
    mcp_dir.mkdir()
    mcp_file = mcp_dir / "mcp.yaml"
    mcp_file.write_text(
        yaml.dump({"mcp_servers": {"p1": {"type": "http", "url": "https://example.com/mcp"}}}),
        encoding="utf-8",
    )

    cfg = load_config(str(project_dir))
    assert "p1" in cfg.servers
    assert cfg.servers["p1"].type == "http"
    assert cfg.servers["p1"].url == "https://example.com/mcp"


def test_merge_project_overrides_user(tmp_path, monkeypatch):
    """项目级同名 server 完整覆盖用户级。"""
    user_dir = tmp_path / ".forgecode"
    user_dir.mkdir()
    user_file = user_dir / "mcp.yaml"
    user_file.write_text(
        yaml.dump(
            {
                "mcp_servers": {
                    "shared": {"type": "stdio", "command": "user-cmd"},
                    "user-only": {"type": "stdio", "command": "user-only-cmd"},
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    project_dir = tmp_path / "project"
    project_dir.mkdir(parents=True)
    mcp_dir = project_dir / ".forgecode"
    mcp_dir.mkdir()
    mcp_file = mcp_dir / "mcp.yaml"
    mcp_file.write_text(
        yaml.dump(
            {
                "mcp_servers": {
                    "shared": {"type": "http", "url": "https://project.example.com"},
                    "project-only": {"type": "stdio", "command": "project-cmd"},
                }
            }
        ),
        encoding="utf-8",
    )

    cfg = load_config(str(project_dir))
    # 同名 shared → 项目级覆盖
    assert cfg.servers["shared"].type == "http"
    assert cfg.servers["shared"].url == "https://project.example.com"
    # 各自独立 server 均存在
    assert "user-only" in cfg.servers
    assert "project-only" in cfg.servers


# ── T2.2: 变量展开 ─────────────────────────────────


def test_expand_vars_defined(monkeypatch):
    """已定义变量展开为环境值。"""
    monkeypatch.setenv("MY_TOKEN", "abc123")
    result, undef = _expand_vars("Bearer ${MY_TOKEN}")
    assert result == "Bearer abc123"
    assert undef == []


def test_expand_vars_undefined():
    """未定义变量展开为空串并记录。"""
    result, undef = _expand_vars("Bearer ${UNDEFINED_VAR}")
    assert result == "Bearer "
    assert "UNDEFINED_VAR" in undef


def test_expand_vars_no_braces():
    """无 ${} 格式原样返回。"""
    result, undef = _expand_vars("no variables here")
    assert result == "no variables here"
    assert undef == []


def test_expand_vars_on_headers_and_env(monkeypatch, capsys):
    """env / headers 值被展开；未定义时 stderr 告警。"""
    monkeypatch.setenv("GITHUB_TOKEN", "gh_token_value")
    srv = _RawServer(
        type="stdio",
        command="npx",
        env={"GITHUB_TOKEN": "${GITHUB_TOKEN}", "OTHER": "${MISSING}"},
        headers={"Authorization": "Bearer ${GITHUB_TOKEN}"},
    )
    _apply_expansion("test-server", srv)
    assert srv.env["GITHUB_TOKEN"] == "gh_token_value"
    assert srv.env["OTHER"] == ""
    assert srv.headers["Authorization"] == "Bearer gh_token_value"

    err = capsys.readouterr().err
    assert "MISSING" in err


def test_command_not_expanded(monkeypatch):
    """command / args 不展开 ${VAR}。"""
    monkeypatch.setenv("CMD", "echo")
    srv = _RawServer(type="stdio", command="${CMD}", args=["${ARG}"])
    _apply_expansion("test", srv)
    # command / args 不受 _apply_expansion 影响（仅 env / headers）
    assert srv.command == "${CMD}"
    assert srv.args == ["${ARG}"]


# ── T2.3: 字段校验 ─────────────────────────────────


def test_validate_stdio_missing_command():
    """stdio 缺 command → 跳过。"""
    srv = _RawServer(type="stdio")
    result = _validate_server("s1", srv)
    assert result is None


def test_validate_http_missing_url():
    """http 缺 url → 跳过。"""
    srv = _RawServer(type="http")
    result = _validate_server("s1", srv)
    assert result is None


def test_validate_invalid_type():
    """type 非法 → 跳过。"""
    srv = _RawServer(type="sse")
    result = _validate_server("s1", srv)
    assert result is None


def test_validate_stdio_ok():
    """合法 stdio → ServerConfig。"""
    srv = _RawServer(type="stdio", command="node", args=["server.js"], env={"NODE_ENV": "prod"})
    result = _validate_server("s1", srv)
    assert result is not None
    assert result.type == "stdio"
    assert result.command == "node"
    assert result.args == ["server.js"]
    assert result.env == {"NODE_ENV": "prod"}


def test_validate_http_ok():
    """合法 http → ServerConfig。"""
    srv = _RawServer(type="http", url="https://mcp.example.com", headers={"X-Key": "val"})
    result = _validate_server("s1", srv)
    assert result is not None
    assert result.type == "http"
    assert result.url == "https://mcp.example.com"
    assert result.headers == {"X-Key": "val"}


# ── T2.4: 文件降级 ─────────────────────────────────


def test_load_file_invalid_yaml(tmp_path):
    """格式非法 YAML → 返回空 {}。"""
    f = tmp_path / "bad.yaml"
    f.write_text(": invalid yaml ::", encoding="utf-8")
    result = _load_file(f)
    assert result == {}


def test_load_file_missing():
    """文件不存在 → 返回空 {}。"""
    result = _load_file(Path("/no/such/file.yaml"))
    assert result == {}


def test_load_file_no_mcp_servers_key(tmp_path):
    """顶层无 mcp_servers → 返回空 {}。"""
    f = tmp_path / "cfg.yaml"
    f.write_text(yaml.dump({"other": "data"}), encoding="utf-8")
    result = _load_file(f)
    assert result == {}


# ── T2.5: 合并逻辑 ─────────────────────────────────


def test_merge_servers_basic():
    """基本合并：user + project → 合并。"""
    user = {"a": _RawServer(type="stdio", command="a-cmd")}
    project = {"b": _RawServer(type="http", url="http://b")}
    merged = _merge_servers(user, project)
    assert "a" in merged
    assert "b" in merged


def test_merge_project_overwrites_user():
    """project 层覆盖 user 层同名。"""
    user = {"s": _RawServer(type="stdio", command="old")}
    project = {"s": _RawServer(type="http", url="http://new")}
    merged = _merge_servers(user, project)
    assert merged["s"].type == "http"
    assert merged["s"].url == "http://new"
