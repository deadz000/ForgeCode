"""本地命令 /skill：列出已加载 Skill。"""

from __future__ import annotations


async def handle_skill(ui) -> None:
    skills = ui.list_catalog_skills()
    if not skills:
        ui.println("No skills loaded.")
        return
    ui.println(f"Available skills ({len(skills)}):")
    for skill in sorted(skills, key=lambda s: s.name):
        ui.println(f"  /{skill.name:<20} {skill.description}")
    ui.println("Type /<skill-name> to invoke a skill.")
