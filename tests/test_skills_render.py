"""Skill render_body 单测。"""

from __future__ import annotations

from forgecode.skills.render import render_body
from forgecode.skills.types import Skill, SkillMeta, SkillSource


def _skill(body, allowed=None):
    return Skill(
        meta=SkillMeta(name="demo", description="demo", allowed_tools=allowed or []),
        prompt_body=body,
        source_dir=__file__,
        source=SkillSource.USER,
    )


def test_render_placeholder_replaced():
    out = render_body(_skill("Do $ARGUMENTS now"), "the thing")
    assert "Do the thing now" in out


def test_render_no_placeholder_appends_request():
    out = render_body(_skill("Do it"), "the thing")
    assert "## User Request" in out
    assert "the thing" in out


def test_render_empty_args_keeps_body():
    out = render_body(_skill("Do $ARGUMENTS"), "")
    assert "Do " in out


def test_render_allowed_tools_hint():
    out = render_body(_skill("body", allowed=["read_file", "grep"]), "")
    assert "This skill is designed to use only these tools: read_file, grep" in out
    assert "---" in out
