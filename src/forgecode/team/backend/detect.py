"""后端一次性检测（F14）：按优先级决定，不做运行时回退。"""

from __future__ import annotations

import os
import shutil

from forgecode.team.types import BackendType


def detect() -> BackendType:
    """按优先级检测后端：
    1. $TMUX → tmux
    2. $TERM_PROGRAM == "iTerm.app" && it2 可执行 → iterm2
    3. tmux 二进制在 PATH → tmux
    4. 否则 → in-process
    """
    if os.environ.get("TMUX"):
        return BackendType.TMUX
    if os.environ.get("TERM_PROGRAM") == "iTerm.app" and shutil.which("it2"):
        return BackendType.ITERM2
    if shutil.which("tmux"):
        return BackendType.TMUX
    return BackendType.IN_PROCESS
