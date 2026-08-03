"""subagent.Catalog 单测：三层加载与同名覆盖。"""

from __future__ import annotations

import pytest

from forgecode.subagent.catalog import load_catalog
from forgecode.subagent.definition import Source
from forgecode.subagent.embed import builtin_definitions


def test_builtin_definitions() -> None:
    defs = builtin_definitions()
    names = [d.name for d in defs]
    assert names == ["Explore", "Plan", "general-purpose"]
    assert all(d.source is Source.BUILTIN for d in defs)


def test_catalog_loads_builtins(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home" / ".forgecode").mkdir(parents=True)
    c = load_catalog(str(tmp_path))
    assert c.resolve("Explore") is not None
    assert c.resolve("general-purpose") is not None


def test_project_overrides_builtin(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home" / ".forgecode").mkdir(parents=True)
    proj_agents = tmp_path / ".forgecode" / "agents"
    proj_agents.mkdir(parents=True)
    (proj_agents / "explore.md").write_text(
        "---\nname: Explore\ndescription: 项目级覆盖\n---\nproject body",
        encoding="utf-8",
    )
    c = load_catalog(str(tmp_path))
    d = c.resolve("Explore")
    assert d is not None
    assert d.source is Source.PROJECT
    assert "project body" in d.system_prompt


def test_user_overrides_builtin(tmp_path, monkeypatch) -> None:
    from pathlib import Path

    home = tmp_path / "home"
    # Windows 上 Path.home() 读 USERPROFILE 而非 HOME → 直接替换类方法
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    user_agents = home / ".forgecode" / "agents"
    user_agents.mkdir(parents=True)
    (user_agents / "explore.md").write_text(
        "---\nname: Explore\ndescription: 用户级覆盖\n---\nuser body",
        encoding="utf-8",
    )
    c = load_catalog(str(tmp_path))
    d = c.resolve("Explore")
    assert d is not None
    assert d.source is Source.USER


def test_fork_definition() -> None:
    c = load_catalog(".")
    d = c.fork_definition()
    assert d.is_fork() is True
    assert d.name == "__fork__"


def test_bad_file_skipped(capsys: pytest.CaptureFixture[str], tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home" / ".forgecode").mkdir(parents=True)
    proj_agents = tmp_path / ".forgecode" / "agents"
    proj_agents.mkdir(parents=True)
    (proj_agents / "bad.md").write_text("no frontmatter here", encoding="utf-8")
    (proj_agents / "ok.md").write_text(
        "---\nname: ok\ndescription: fine\n---\n",
        encoding="utf-8",
    )
    c = load_catalog(str(tmp_path))
    assert c.resolve("ok") is not None
    assert c.resolve("bad") is None
    captured = capsys.readouterr()
    assert "skipped" in captured.err
