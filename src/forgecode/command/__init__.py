"""命令系统包：注册中心驱动的斜杠命令分发。"""

from forgecode.command.builtins import register_builtins
from forgecode.command.command import Command, Handler, Kind
from forgecode.command.dispatch import parse
from forgecode.command.registry import Registry
from forgecode.command.ui import UI, NopUI

__all__ = [
    "Kind",
    "Command",
    "Handler",
    "Registry",
    "parse",
    "UI",
    "NopUI",
    "register_builtins",
]
