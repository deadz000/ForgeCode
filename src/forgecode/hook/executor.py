"""Hook 动作执行器：shell / prompt / http / subagent(占位)。"""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass

import httpx

from forgecode.hook.rule import (
    ActionType,
    HttpAction,
    Payload,
    PromptAction,
    Rule,
    ShellAction,
    SubagentAction,
)


@dataclass
class ExecutionResult:
    """单条 hook 动作的执行结果。"""

    blocked: bool = False
    reason: str = ""
    prompt: str = ""  # 仅 prompt 动作非空
    err: Exception | None = None  # hook 自身失败（不拦截）


class Executor:
    """四类动作的执行入口；payload JSON 序列化保证 key 字典序（N6）。"""

    def __init__(self) -> None:
        # 默认 timeout=30s，可被 rule.timeout_s 覆盖
        self._http_client = httpx.AsyncClient(timeout=30.0)

    async def run(self, rule: Rule, payload: Payload, *, blocking: bool) -> ExecutionResult:
        """按 action.type 分发到对应内部方法。"""
        action = rule.action
        if action.type is ActionType.SHELL:
            assert action.shell is not None
            return await self._run_shell(action.shell, payload, blocking, rule.timeout_s)
        if action.type is ActionType.PROMPT:
            assert action.prompt is not None
            return self._run_prompt(action.prompt)
        if action.type is ActionType.HTTP:
            assert action.http is not None
            return await self._run_http(action.http, payload, blocking, rule.timeout_s)
        if action.type is ActionType.SUBAGENT:
            assert action.subagent is not None
            return self._run_subagent(action.subagent)
        return ExecutionResult(err=RuntimeError(f"unknown action type: {action.type}"))

    async def _run_shell(
        self,
        sa: ShellAction,
        payload: Payload,
        blocking: bool,
        timeout: float,
    ) -> ExecutionResult:
        """执行 shell 命令：payload 经 stdin 传入，returncode==2 表达拦截。"""
        payload_json = _marshal_sorted(payload)
        try:
            proc = await asyncio.create_subprocess_shell(
                sa.command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as e:
            return ExecutionResult(err=e)

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(payload_json), timeout=timeout)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return ExecutionResult(err=TimeoutError(f"hook command timed out after {timeout}s"))

        code = proc.returncode or 0
        if blocking and code == 2:
            # 拦截信号：stderr（或 stdout）去尾换行作为拒绝原因（Windows 行尾含 \r）
            reason = (stderr or stdout).decode(errors="replace").rstrip("\r\n")
            return ExecutionResult(blocked=True, reason=reason)
        if code == 0:
            return ExecutionResult()
        return ExecutionResult(err=RuntimeError(f"exit {code}: {stderr.decode(errors='replace')}"))

    def _run_prompt(self, pa: PromptAction) -> ExecutionResult:
        """prompt 动作：直接返回文本，交由 Engine 累加进 reminder 队列。"""
        return ExecutionResult(prompt=pa.text)

    async def _run_http(
        self,
        ha: HttpAction,
        payload: Payload,
        blocking: bool,
        timeout: float,
    ) -> ExecutionResult:
        """http 动作：请求 2xx 且 body 含 decision=block 时表达拦截。"""
        if ha.body is None:
            body = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        else:
            try:
                body = ha.body.format_map(payload)
            except (KeyError, IndexError, ValueError, TypeError) as e:
                return ExecutionResult(err=RuntimeError(f"http body template render failed: {e}"))

        try:
            resp = await self._http_client.request(
                ha.method or "POST",
                ha.url,
                content=body,
                headers=ha.headers,
                timeout=timeout,
            )
        except httpx.HTTPError as e:
            return ExecutionResult(err=e)

        if 200 <= resp.status_code < 300:
            try:
                data = json.loads(resp.text)
            except json.JSONDecodeError as e:
                return ExecutionResult(err=e)
            if isinstance(data, dict) and data.get("decision") == "block":
                return ExecutionResult(blocked=True, reason=str(data.get("reason", "")))
        return ExecutionResult()

    def _run_subagent(self, sa: SubagentAction) -> ExecutionResult:
        """subagent 动作：本期占位——仅记一行 stderr 日志，不报错不拦截。"""
        print(
            f"[hook subagent] not yet implemented, skipped: {sa.agent_name}",
            file=sys.stderr,
        )
        return ExecutionResult()


def _marshal_sorted(payload: Payload) -> bytes:
    """payload 序列化：key 字典序 + UTF-8 编码。"""
    return json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
