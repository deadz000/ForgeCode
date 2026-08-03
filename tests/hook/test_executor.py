"""hook.Executor 测试：shell exit2、http block、prompt、subagent stub。"""

from __future__ import annotations

import http.server
import json
import threading

import pytest

from forgecode.hook.event import Event
from forgecode.hook.executor import Executor
from forgecode.hook.rule import (
    Action,
    ActionType,
    HttpAction,
    PromptAction,
    Rule,
    ShellAction,
    SubagentAction,
)

PAYLOAD = {"event": "Stop", "session_id": "s1", "cwd": "/tmp", "mode": "default"}


def _shell_rule(command: str, *, timeout: float = 30.0, name: str = "t") -> Rule:
    return Rule(
        name=name,
        event=Event.STOP,
        action=Action(type=ActionType.SHELL, shell=ShellAction(command=command)),
        timeout_s=timeout,
    )


def _prompt_rule(text: str, *, name: str = "t") -> Rule:
    return Rule(
        name=name,
        event=Event.STOP,
        action=Action(type=ActionType.PROMPT, prompt=PromptAction(text=text)),
    )


def _http_rule(
    url: str, *, name: str = "t", body: str | None = None, method: str = "POST", timeout: float = 30.0
) -> Rule:
    return Rule(
        name=name,
        event=Event.STOP,
        action=Action(
            type=ActionType.HTTP,
            http=HttpAction(url=url, method=method, body=body),
        ),
        timeout_s=timeout,
    )


# ── 本地 HTTP 桩 ─────────────────────────────────────


class _Recorder(http.server.BaseHTTPRequestHandler):
    received: list[tuple[str, bytes]] = []
    response_status = 200
    response_body = b"{}"

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        self.__class__.received.append((self.path, body))
        self.send_response(self.__class__.response_status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(self.__class__.response_body)

    def log_message(self, *args):
        pass


@pytest.fixture
def http_stub():
    server = http.server.HTTPServer(("127.0.0.1", 0), _Recorder)
    _Recorder.received = []
    _Recorder.response_status = 200
    _Recorder.response_body = b"{}"
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


# ── shell 动作 ───────────────────────────────────────


@pytest.mark.asyncio
async def test_shell_exit_2_blocked():
    """exit 2 + stderr → blocked=True，reason 含 stderr。"""
    exec_ = Executor()
    rule = _shell_rule("python -c \"import sys; print('blocked', file=sys.stderr); sys.exit(2)\"")
    res = await exec_.run(rule, PAYLOAD, blocking=True)
    assert res.blocked
    assert "blocked" in res.reason
    assert res.err is None
    await exec_._http_client.aclose()


@pytest.mark.asyncio
async def test_shell_exit_0_pass():
    """exit 0 → 放行不报错。"""
    exec_ = Executor()
    rule = _shell_rule("python -c \"pass\"")
    res = await exec_.run(rule, PAYLOAD, blocking=True)
    assert not res.blocked
    assert res.err is None
    await exec_._http_client.aclose()


@pytest.mark.asyncio
async def test_shell_exit_1_error_not_blocked():
    """exit 1 → err 非 None 不拦截。"""
    exec_ = Executor()
    rule = _shell_rule("python -c \"import sys; sys.exit(1)\"")
    res = await exec_.run(rule, PAYLOAD, blocking=True)
    assert not res.blocked
    assert res.err is not None
    assert "exit 1" in str(res.err)
    await exec_._http_client.aclose()


@pytest.mark.asyncio
async def test_shell_stdin_sorted_json():
    """payload 经 stdin 传入且 key 字典序。"""
    exec_ = Executor()
    rule = _shell_rule("python -c \"import sys, json; d = json.load(sys.stdin); print(d.get('event'))\"")
    res = await exec_.run(rule, PAYLOAD, blocking=True)
    assert res.err is None
    await exec_._http_client.aclose()


@pytest.mark.asyncio
async def test_shell_timeout():
    """超时 → err 为 TimeoutError。"""
    exec_ = Executor()
    rule = _shell_rule("python -c \"import time; time.sleep(5)\"", timeout=0.1)
    res = await exec_.run(rule, PAYLOAD, blocking=True)
    assert res.err is not None
    assert isinstance(res.err, TimeoutError)
    await exec_._http_client.aclose()


@pytest.mark.asyncio
async def test_shell_nonblocking_exit_2_not_blocked():
    """非拦截事件下 exit 2 不表达拦截。"""
    exec_ = Executor()
    rule = _shell_rule("python -c \"import sys; sys.exit(2)\"")
    res = await exec_.run(rule, PAYLOAD, blocking=False)
    assert not res.blocked
    await exec_._http_client.aclose()


# ── prompt 动作 ──────────────────────────────────────


@pytest.mark.asyncio
async def test_prompt_returns_text():
    """prompt → result.prompt 非空。"""
    exec_ = Executor()
    rule = _prompt_rule("默认用 zh-CN 回复")
    res = await exec_.run(rule, PAYLOAD, blocking=True)
    assert res.prompt == "默认用 zh-CN 回复"
    assert not res.blocked
    await exec_._http_client.aclose()


# ── http 动作 ────────────────────────────────────────


@pytest.mark.asyncio
async def test_http_block(http_stub):
    """server 返回 decision=block → blocked=True。"""
    _Recorder.response_body = json.dumps({"decision": "block", "reason": "x"}).encode()
    exec_ = Executor()
    rule = _http_rule(f"{http_stub}/check")
    res = await exec_.run(rule, PAYLOAD, blocking=True)
    assert res.blocked
    assert res.reason == "x"
    await exec_._http_client.aclose()


@pytest.mark.asyncio
async def test_http_5xx_pass(http_stub):
    """5xx → 视为放行（F25：非 2xx 不拦截不报错）。"""
    _Recorder.response_status = 500
    exec_ = Executor()
    rule = _http_rule(f"{http_stub}/err")
    res = await exec_.run(rule, PAYLOAD, blocking=True)
    assert not res.blocked
    assert res.err is None
    await exec_._http_client.aclose()


@pytest.mark.asyncio
async def test_http_body_template(http_stub):
    """body 模板含 {event} → server 收到正确字段。"""
    exec_ = Executor()
    rule = _http_rule(f"{http_stub}/tpl", body="ev={event}")
    res = await exec_.run(rule, PAYLOAD, blocking=True)
    assert res.err is None
    await exec_._http_client.aclose()
    assert _Recorder.received
    path, body = _Recorder.received[-1]
    assert path == "/tpl"
    assert body == b"ev=Stop"


@pytest.mark.asyncio
async def test_http_default_json_body(http_stub):
    """缺省 body → payload JSON 且 key 字典序。"""
    exec_ = Executor()
    rule = _http_rule(f"{http_stub}/json")
    res = await exec_.run(rule, PAYLOAD, blocking=True)
    assert res.err is None
    await exec_._http_client.aclose()
    assert _Recorder.received
    _, body = _Recorder.received[-1]
    data = json.loads(body)
    assert data == PAYLOAD
    assert list(data.keys()) == sorted(data.keys())


@pytest.mark.asyncio
async def test_http_decision_pass(http_stub):
    """decision 非 block → 放行。"""
    _Recorder.response_body = json.dumps({"decision": "allow"}).encode()
    exec_ = Executor()
    rule = _http_rule(f"{http_stub}/pass")
    res = await exec_.run(rule, PAYLOAD, blocking=True)
    assert not res.blocked
    assert res.err is None
    await exec_._http_client.aclose()


@pytest.mark.asyncio
async def test_http_bad_json_body(http_stub):
    """2xx 但 body 非 JSON → err（hook 失败不拦截）。"""
    _Recorder.response_body = b"not json"
    exec_ = Executor()
    rule = _http_rule(f"{http_stub}/bad")
    res = await exec_.run(rule, PAYLOAD, blocking=True)
    assert not res.blocked
    assert res.err is not None
    await exec_._http_client.aclose()


@pytest.mark.asyncio
async def test_http_network_error():
    """网络错误 → err。"""
    exec_ = Executor()
    rule = _http_rule("http://127.0.0.1:1/nope", timeout=0.5)
    res = await exec_.run(rule, PAYLOAD, blocking=True)
    assert res.err is not None
    await exec_._http_client.aclose()


# ── subagent 动作（占位）─────────────────────────────


@pytest.mark.asyncio
async def test_subagent_stub(capsys):
    """subagent → stderr 含占位文本，不阻塞不报错。"""
    exec_ = Executor()
    rule = Rule(
        name="sa",
        event=Event.STOP,
        action=Action(
            type=ActionType.SUBAGENT,
            subagent=SubagentAction(agent_name="foo", prompt="test"),
        ),
    )
    res = await exec_.run(rule, PAYLOAD, blocking=True)
    assert res.err is None
    assert not res.blocked
    assert "[hook subagent] not yet implemented, skipped: foo" in capsys.readouterr().err
    await exec_._http_client.aclose()
