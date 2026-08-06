"""Tmux 后端：split-window / new-session 启动 Pane 队员。"""

from __future__ import annotations

import asyncio
import os
import shlex
import sys

from forgecode.team.backend import SpawnRequest
from forgecode.team.types import BackendType


def build_member_cmd(req: SpawnRequest) -> str:
    """构造 --team-member 子进程命令行（F15）。"""
    parts = [
        shlex.quote(sys.executable),
        "-m",
        "forgecode",
        "--team-member",
        "--team",
        shlex.quote(req.team_name),
        "--member",
        shlex.quote(req.member_name),
        "--agent-id",
        shlex.quote(req.agent_id),
        "--session-dir",
        shlex.quote(req.session_dir),
        "--worktree",
        shlex.quote(req.worktree_path),
    ]
    if req.agent_type:
        parts += ["--agent-type", shlex.quote(req.agent_type)]
    if req.model:
        parts += ["--model", shlex.quote(req.model)]
    if req.plan_mode_required:
        parts.append("--plan-mode")
    return " ".join(parts)


class TmuxBackend:
    """tmux 后端实现（F15/F16）。"""

    def type(self) -> BackendType:
        return BackendType.TMUX

    async def spawn(self, req: SpawnRequest) -> tuple[str, str]:
        """在 tmux 会话内横向 split；会话外 detached 新会话。返回 (pane_id, agent_id)。"""
        cmd = build_member_cmd(req)
        inside = bool(os.environ.get("TMUX"))
        if inside:
            proc = await asyncio.create_subprocess_exec(
                "tmux",
                "split-window",
                "-h",
                "-P",
                "-F",
                "#{pane_id}",
                "--",
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        else:
            session_name = f"forgecode-team-{req.team_name}-{req.member_name}"
            proc = await asyncio.create_subprocess_exec(
                "tmux",
                "new-session",
                "-d",
                "-s",
                session_name,
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        out, err = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"tmux spawn 失败: {err.decode().strip()}")
        if inside:
            pane_id = out.decode().strip()
            return pane_id, req.agent_id
        # detached 新会话：查第一个 pane id
        pane_id = await self._pane_id_of_session(session_name)
        return pane_id, req.agent_id

    async def _pane_id_of_session(self, session_name: str) -> str:
        proc = await asyncio.create_subprocess_exec(
            "tmux",
            "display-message",
            "-p",
            "-t",
            session_name,
            "#{pane_id}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, _ = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError("tmux 无法解析新会话 pane id")
        return out.decode().strip()

    async def wake(self, pane_id: str, agent_id: str) -> None:
        """回车唤醒目标 pane 的 stdin reader（F15）。"""
        if not pane_id:
            return
        try:
            proc = await asyncio.create_subprocess_exec(
                "tmux",
                "send-keys",
                "-t",
                pane_id,
                "",
                "Enter",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.communicate()
        except OSError:
            pass

    async def kill(self, pane_id: str, agent_id: str) -> None:
        """杀掉目标 pane；忽略 pane 不存在错误。"""
        if not pane_id:
            return
        try:
            proc = await asyncio.create_subprocess_exec(
                "tmux",
                "kill-pane",
                "-t",
                pane_id,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.communicate()
        except OSError:
            pass
