"""Skill 正文渲染：$ARGUMENTS 替换 + allowed_tools 建议工具提示。"""

from __future__ import annotations

from forgecode.skills.types import Skill


def render_body(skill: Skill, args: str) -> str:
    """把 Skill body 渲染为最终注入文本。"""
    body = skill.prompt_body
    allowed = skill.meta.allowed_tools
    if allowed:
        hint = (
            "This skill is designed to use only these tools: "
            + ", ".join(allowed)
            + ". Prefer them over other tools when possible."
        )
        body = hint + "\n\n---\n\n" + body

    if "$ARGUMENTS" in body:
        body = body.replace("$ARGUMENTS", args)
    elif args.strip():
        body = body.rstrip() + "\n\n## User Request\n\n" + args

    return body
