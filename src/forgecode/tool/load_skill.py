"""LoadSkill 系统工具：把 Skill 的完整 SOP 钉到 ActiveSkills。"""

from __future__ import annotations

import warnings

from forgecode.tool import Result, _parse_args
from forgecode.tool.skill_tool import new_skill_tool


class LoadSkillTool:
    """激活一个 Skill，注册其专属工具，并把最新 SOP 写入环境上下文。"""

    read_only = True
    is_system = True

    def __init__(self, catalog, active, registry) -> None:
        self._catalog = catalog
        self._active = active
        self._registry = registry

    def name(self) -> str:
        return "load_skill"

    def description(self) -> str:
        return "从 Catalog 激活一个 Skill，把完整 SOP 钉到环境上下文，并注册该 Skill 的专属工具。"

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Skill name to activate"},
            },
            "required": ["name"],
        }

    async def execute(self, args: str) -> Result:
        try:
            data = _parse_args(args)
        except ValueError as e:
            return Result(content=str(e), is_error=True)

        name = data.get("name")
        if not isinstance(name, str) or not name:
            return Result(content="缺少必填参数: name", is_error=True)

        skill = self._catalog.get(name)
        if skill is None:
            return Result(content=f"unknown skill: {name}", is_error=True)

        body = _fresh_body(skill)
        self._active.activate(skill.meta.name, body)

        count = 0
        for spec in skill.tool_specs:
            self._registry.register_skill_tool(
                new_skill_tool(
                    name=spec.name,
                    description=spec.description,
                    input_schema=spec.input_schema,
                    command=spec.command,
                    base_dir=spec.base_dir,
                )
            )
            count += 1

        return Result(
            content=(
                f"Skill {name} activated. SOP pinned to env context. {count} specialized tools registered."
            )
        )


def _fresh_body(skill):
    from forgecode.skills.parser import _parse_frontmatter_and_body

    try:
        raw = (skill.source_dir / "SKILL.md").read_text(encoding="utf-8")
        _, body = _parse_frontmatter_and_body(raw)
        return body
    except Exception as e:
        warnings.warn(f"skill {skill.meta.name}: reload SKILL.md failed, use cache: {e}", stacklevel=3)
        return skill.prompt_body
