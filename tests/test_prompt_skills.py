"""prompt skills_block 渲染单测。"""

from __future__ import annotations

from forgecode.prompt.skills_block import (
    ActiveSkillEntry,
    SkillCatalogItem,
    render_active_skills_block,
    render_skills_catalog,
)


def test_render_skills_catalog_empty():
    assert render_skills_catalog([]) == ""


def test_render_skills_catalog_non_empty():
    out = render_skills_catalog([SkillCatalogItem("commit", "commit changes")])
    assert "## Available Skills" in out
    assert "- commit: commit changes" in out
    assert "LoadSkill" in out


def test_render_active_skills_block_empty():
    assert render_active_skills_block([]) == ""


def test_render_active_skills_block_non_empty():
    out = render_active_skills_block([ActiveSkillEntry("commit", "sop body")])
    assert "## Active Skills" in out
    assert "### Skill: commit" in out
    assert "sop body" in out
