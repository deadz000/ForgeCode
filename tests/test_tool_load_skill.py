"""LoadSkillTool 激活与专属工具注册单测。"""

from __future__ import annotations

import json

import pytest

from forgecode.skills.active import ActiveSkills
from forgecode.skills.parser import parse_skill_dir
from forgecode.skills.types import SkillSource
from forgecode.tool import Registry
from forgecode.tool.load_skill import LoadSkillTool


@pytest.mark.asyncio
async def test_load_skill_activates_and_registers(tmp_path):
    d = tmp_path / "demo"
    d.mkdir()
    (d / "SKILL.md").write_text(
        "---\nname: demo\ndescription: demo\n---\n\nbody\n",
        encoding="utf-8",
    )
    (d / "tool.json").write_text(
        '{"tools": [{"name": "demo_tool", "description": "demo", '
        '"input_schema": {"type": "object"}, "command": ["demo.py"]}]}',
        encoding="utf-8",
    )

    def _get_skill(name):
        if name == "demo":
            return parse_skill_dir(d, SkillSource.USER)
        return None

    catalog = type("Catalog", (), {"get": staticmethod(_get_skill)})()
    active = ActiveSkills()
    registry = Registry()
    tool = LoadSkillTool(catalog, active, registry)
    result = await tool.execute(json.dumps({"name": "demo"}))
    assert not result.is_error
    assert "activated" in result.content
    assert active.names() == ["demo"]
    assert registry.get("demo_tool") is not None


@pytest.mark.asyncio
async def test_load_skill_unknown():
    catalog = type("Catalog", (), {"get": lambda self, name: None})()
    tool = LoadSkillTool(catalog, ActiveSkills(), Registry())
    result = await tool.execute(json.dumps({"name": "missing"}))
    assert result.is_error
    assert "unknown skill: missing" in result.content
