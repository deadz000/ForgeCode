"""hook.Loader 测试：字段校验、加载错误、双层合并。"""

from __future__ import annotations

from pathlib import Path

from forgecode.hook import Event, load


def _write(tmp_path: Path, rel: str, text: str) -> Path:
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def test_load_valid_yaml(tmp_path):
    """合法 hooks.yaml → Engine 含 2 条 rule。"""
    _write(
        tmp_path,
        ".forgecode/hooks.yaml",
        """
hooks:
  - name: a
    event: SessionStart
    action:
      type: prompt
      text: hello
  - name: b
    event: Stop
    action:
      type: shell
      command: echo hi
""",
    )
    eng = load(tmp_path)
    assert eng is not None
    assert len(eng.rules) == 2
    assert [r.name for r in eng.rules] == ["a", "b"]
    assert eng.sources == [str(tmp_path / ".forgecode" / "hooks.yaml")]


def test_load_no_files(tmp_path):
    """无 hooks.yaml → 返回 None。"""
    assert load(tmp_path) is None


def test_load_missing_file_ok(tmp_path):
    """文件不存在不报错。"""
    assert load(tmp_path) is None


def test_load_skip_bad_keep_good(tmp_path, capsys):
    """字段缺失/未知事件/无效 action.type → 跳过该条，其余正常。"""
    _write(
        tmp_path,
        ".forgecode/hooks.yaml",
        """
hooks:
  - name: ""          # 空 name
    event: SessionStart
    action: {type: prompt, text: x}
  - name: bad-event
    event: UnknownEvent
    action: {type: prompt, text: x}
  - name: bad-action
    event: SessionStart
    action: {type: bogus}
  - name: good
    event: SessionStart
    action: {type: prompt, text: ok}
""",
    )
    eng = load(tmp_path)
    assert eng is not None
    assert [r.name for r in eng.rules] == ["good"]
    err = capsys.readouterr().err
    assert 'unknown event "UnknownEvent"' in err


def test_load_all_of_any_of_conflict(tmp_path, capsys):
    """all_of + any_of 同时存在 → 跳过该条。"""
    _write(
        tmp_path,
        ".forgecode/hooks.yaml",
        """
hooks:
  - name: conflict
    event: PreToolUse
    if:
      all_of: [{field: tool_name, match: {type: exact, value: write_file}}]
      any_of: [{field: tool_name, match: {type: exact, value: read_file}}]
    action: {type: prompt, text: x}
""",
    )
    assert load(tmp_path) is None
    assert "cannot have both all_of and any_of" in capsys.readouterr().err


def test_load_async_blocking_event(tmp_path, capsys):
    """async + PreToolUse → 跳过并提示。"""
    _write(
        tmp_path,
        ".forgecode/hooks.yaml",
        """
hooks:
  - name: bad-async
    event: PreToolUse
    async: true
    action: {type: shell, command: echo x}
  - name: good
    event: SessionStart
    action: {type: shell, command: echo ok}
""",
    )
    eng = load(tmp_path)
    assert eng is not None
    assert [r.name for r in eng.rules] == ["good"]
    assert "async not allowed for blocking events" in capsys.readouterr().err


def test_load_duplicate_name_across_files(tmp_path, monkeypatch, capsys):
    """跨文件同名冲突 → 项目级保留、用户级跳过。"""
    _write(
        tmp_path,
        ".forgecode/hooks.yaml",
        """
hooks:
  - name: same
    event: SessionStart
    action: {type: prompt, text: project}
""",
    )
    user_home = tmp_path / "home"
    _write(
        user_home,
        ".forgecode/hooks.yaml",
        """
hooks:
  - name: same
    event: Stop
    action: {type: prompt, text: user}
  - name: user-only
    event: Stop
    action: {type: prompt, text: user2}
""",
    )
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: user_home))
    eng = load(tmp_path)
    assert eng is not None
    assert [r.name for r in eng.rules] == ["same", "user-only"]
    assert eng.rules[0].event is Event.SESSION_START
    assert "duplicate name" in capsys.readouterr().err
    # 两个来源文件
    assert len(eng.sources) == 2


def test_load_invalid_regex(tmp_path, capsys):
    """条件内非法正则 → 跳过该条。"""
    _write(
        tmp_path,
        ".forgecode/hooks.yaml",
        """
hooks:
  - name: bad-regex
    event: PreToolUse
    if:
      all_of:
        - field: tool_name
          match: {type: regex, value: "[invalid"}
    action: {type: prompt, text: x}
""",
    )
    assert load(tmp_path) is None
    assert "invalid regex" in capsys.readouterr().err


def test_load_invalid_timeout(tmp_path, capsys):
    """timeout 格式非法 → 跳过该条。"""
    _write(
        tmp_path,
        ".forgecode/hooks.yaml",
        """
hooks:
  - name: bad-timeout
    event: SessionStart
    timeout: xxx
    action: {type: prompt, text: x}
""",
    )
    assert load(tmp_path) is None
    assert "invalid timeout" in capsys.readouterr().err


def test_load_timeout_units(tmp_path):
    """timeout 单位解析：30s / 5m / 裸浮点。"""
    _write(
        tmp_path,
        ".forgecode/hooks.yaml",
        """
hooks:
  - name: a
    event: SessionStart
    timeout: 5m
    action: {type: prompt, text: x}
  - name: b
    event: Stop
    timeout: 1.5
    action: {type: prompt, text: x}
""",
    )
    eng = load(tmp_path)
    assert eng is not None
    assert eng.rules[0].timeout_s == 300.0
    assert eng.rules[1].timeout_s == 1.5


def test_load_condition_compiled(tmp_path):
    """if 条件被编译为 Condition + Matcher。"""
    _write(
        tmp_path,
        ".forgecode/hooks.yaml",
        """
hooks:
  - name: cond
    event: PreToolUse
    if:
      all_of:
        - field: tool_name
          match: {type: exact, value: write_file}
        - field: tool_input.path
          match: {type: glob, value: "**/*.py"}
    action: {type: prompt, text: x}
""",
    )
    eng = load(tmp_path)
    assert eng is not None
    rule = eng.rules[0]
    assert rule.condition is not None
    assert len(rule.condition.atoms) == 2
    assert rule.condition.atoms[0].field == "tool_name"


def test_load_rule_order_preserved(tmp_path):
    """按 yaml 声明顺序保留。"""
    _write(
        tmp_path,
        ".forgecode/hooks.yaml",
        """
hooks:
  - name: z
    event: SessionStart
    action: {type: prompt, text: z}
  - name: a
    event: Stop
    action: {type: prompt, text: a}
""",
    )
    eng = load(tmp_path)
    assert [r.name for r in eng.rules] == ["z", "a"]
