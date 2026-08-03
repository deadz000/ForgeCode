"""Skill 自动注册为 Slash Command。"""

from __future__ import annotations

import sys
from functools import partial
from typing import Protocol

from forgecode.command.command import Command, Kind


class SkillRunner(Protocol):
    async def execute(self, ctx, ui, name: str, args: str) -> None: ...


def register_skills_as_commands(reg, items, executor: SkillRunner) -> None:
    for item in items:
        if reg.lookup(item.name) is not None:
            print(f"[skills] warn: skip command /{item.name}: conflict with builtin", file=sys.stderr)
            continue
        handler = partial(_run_skill, executor=executor, name=item.name)
        reg.register(
            Command(
                name=item.name,
                description=f"{item.description} [skill]",
                kind=Kind.PROMPT,
                handler=handler,
                is_skill=True,
            )
        )


def remove_skill_commands(reg) -> None:
    reg.remove_if(lambda cmd: getattr(cmd, "is_skill", False))


async def _run_skill(ui, executor: SkillRunner, name: str) -> None:
    await executor.execute(ui, ui, name, "")
