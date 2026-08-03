"""SKILL.md / tool.json 解析单测。"""

from __future__ import annotations

import pytest

from forgecode.skills.parser import parse_skill_dir
from forgecode.skills.types import SkillSource


def _write_skill(tmp_path, name="demo", extra=""):
    d = tmp_path / name
    d.mkdir()
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: demo skill\n{extra}---\n\nbody\n",
        encoding="utf-8",
    )
    return d


def test_parse_skill_dir_minimal(tmp_path):
    d = _write_skill(tmp_path)
    skill = parse_skill_dir(d, SkillSource.USER)
    assert skill.meta.name == "demo"
    assert skill.meta.mode == "inline"
    assert skill.prompt_body == "body"


def test_parse_skill_dir_invalid_name(tmp_path):
    d = _write_skill(tmp_path, name="BadName")
    with pytest.raises(ValueError):
        parse_skill_dir(d, SkillSource.USER)


def test_parse_skill_dir_with_tool_json(tmp_path):
    d = _write_skill(tmp_path)
    (d / "tool.json").write_text(
        '{"tools": [{"name": "parse_resume", "description": "parse", '
        '"input_schema": {"type": "object"}, "command": ["parse.py"]}]}',
        encoding="utf-8",
    )
    skill = parse_skill_dir(d, SkillSource.USER)
    assert len(skill.tool_specs) == 1
    assert skill.tool_specs[0].name == "parse_resume"


def test_parse_skill_dir_no_skill_md(tmp_path):
    with pytest.raises(FileNotFoundError):
        parse_skill_dir(tmp_path / "missing", SkillSource.USER)
