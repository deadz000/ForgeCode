"""命令系统包：注册中心驱动的斜杠命令分发。"""

from forgecode.command.builtin_skill import handle_skill
from forgecode.command.builtins import register_builtins
from forgecode.command.command import Command, Handler, Kind
from forgecode.command.dispatch import parse
from forgecode.command.registry import Registry
from forgecode.command.skills import register_skills_as_commands, remove_skill_commands
from forgecode.command.ui import UI, NopUI, SkillSummary

__all__ = [
    "Kind",
    "Command",
    "Handler",
    "Registry",
    "parse",
    "SkillSummary",
    "UI",
    "NopUI",
    "handle_skill",
    "register_skills_as_commands",
    "remove_skill_commands",
    "register_builtins",
]
