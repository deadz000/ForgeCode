"""Skill Slash Command 注册单测。"""

from __future__ import annotations

import pytest

from forgecode.command import NopUI, Registry, register_builtins
from forgecode.command.skills import register_skills_as_commands, remove_skill_commands
from forgecode.command.ui import SkillSummary


class FakeRunner:
    async def execute(self, ctx, ui, name, args):
        ui.println(f"ran {name}")


def test_register_and_remove_skill_commands():
    reg = Registry()
    register_builtins(reg)
    items = [
        SkillSummary(name="commit", description="commit changes", source="builtin", mode="inline"),
        SkillSummary(name="review", description="review code", source="builtin", mode="fork"),
    ]
    register_skills_as_commands(reg, items, FakeRunner())
    assert reg.lookup("commit") is not None
    assert reg.lookup("review") is not None
    assert reg.lookup("commit").is_skill is True
    remove_skill_commands(reg)
    assert reg.lookup("commit") is None
    assert reg.lookup("review") is None


@pytest.mark.asyncio
async def test_skill_command_handler_runs():
    reg = Registry()
    register_builtins(reg)
    runner = FakeRunner()
    register_skills_as_commands(
        reg,
        [SkillSummary(name="commit", description="commit", source="builtin", mode="inline")],
        runner,
    )
    cmd = reg.lookup("commit")
    ui = NopUI()
    await cmd.handler(ui)
