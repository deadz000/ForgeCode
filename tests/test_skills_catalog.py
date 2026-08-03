"""Catalog 三层加载与覆盖单测。"""

from __future__ import annotations

from pathlib import Path

from forgecode.skills import Catalog, SkillSource
from forgecode.skills.parser import parse_skill_dir
from forgecode.tool import Registry


def _write_skill(base: Path, name: str, description: str) -> None:
    d = base / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\nbody\n",
        encoding="utf-8",
    )


def _no_home(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")


def test_load_catalog_builtin_only(tmp_path, monkeypatch):
    _no_home(monkeypatch, tmp_path)
    catalog = Catalog.load(tmp_path)
    assert catalog.names() == ["commit", "review", "test"]


def test_load_catalog_user_override(tmp_path, monkeypatch):
    _no_home(monkeypatch, tmp_path)
    user = Path.home() / ".forgecode" / "skills"
    _write_skill(user, "commit", "user override")
    catalog = Catalog.load(tmp_path)
    assert catalog.get("commit").meta.description == "user override"


def test_load_catalog_project_override(tmp_path, monkeypatch):
    _no_home(monkeypatch, tmp_path)
    user = Path.home() / ".forgecode" / "skills"
    project = tmp_path / ".forgecode" / "skills"
    _write_skill(user, "commit", "user override")
    _write_skill(project, "commit", "project override")
    catalog = Catalog.load(tmp_path)
    assert catalog.get("commit").meta.description == "project override"


def test_validate_tools_missing_tool(tmp_path):
    d = tmp_path / "foo"
    d.mkdir()
    (d / "SKILL.md").write_text(
        "---\nname: foo\ndescription: foo\nallowed_tools: [NotExist]\n---\n\nbody\n",
        encoding="utf-8",
    )
    catalog = Catalog()
    catalog.register(parse_skill_dir(d, SkillSource.USER))
    issues = catalog.validate_tools(Registry())
    assert len(issues) == 1
    assert issues[0].tool_name == "NotExist"
