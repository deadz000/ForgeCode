"""iTerm2 后端：it2 CLI 启动 Pane 队员（仅 macOS）。"""

from __future__ import annotations

import asyncio

from forgecode.team.backend import SpawnRequest
from forgecode.team.backend.tmux import build_member_cmd
from forgecode.team.types import BackendType


class Iterm2Backend:
    """iTerm2 后端实现（F17）。

    实测 it2 CLI 参数以官方文档为准；命令构造以 README 描述实现。
    """

    def type(self) -> BackendType:
        return BackendType.ITERM2

    async def spawn(self, req: SpawnRequest) -> tuple[str, str]:
        cmd = build_member_cmd(req)
        proc = await asyncio.create_subprocess_exec(
            "it2",
            "split",
            "--new-pane",
            "--command",
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"it2 spawn 失败: {err.decode().strip()}")
        pane_id = out.decode().strip()
        return pane_id, req.agent_id

    async def wake(self, pane_id: str, agent_id: str) -> None:
        if not pane_id:
            return
        try:
            proc = await asyncio.create_subprocess_exec(
                "it2",
                "send-text",
                "--pane",
                pane_id,
                "",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.communicate()
        except OSError:
            pass

    async def kill(self, pane_id: str, agent_id: str) -> None:
        if not pane_id:
            return
        try:
            proc = await asyncio.create_subprocess_exec(
                "it2",
                "close-pane",
                "--pane",
                pane_id,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.communicate()
        except OSError:
            pass
