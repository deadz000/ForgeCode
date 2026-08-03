"""SkillTool 子进程执行单测。"""

from __future__ import annotations

import json
import sys

import pytest

from forgecode.tool.skill_tool import new_skill_tool


@pytest.mark.asyncio
async def test_skill_tool_echo(tmp_path):
    script = tmp_path / "echo_args.py"
    script.write_text(
        "import json, sys\ndata = json.load(sys.stdin)\nprint('ok:' + data.get('msg', ''))\n",
        encoding="utf-8",
    )
    tool = new_skill_tool(
        name="echo_args",
        description="echo",
        input_schema={"type": "object"},
        command=[sys.executable, str(script)],
        base_dir=tmp_path,
    )
    result = await tool.execute(json.dumps({"msg": "hello"}))
    assert not result.is_error
    assert result.content == "ok:hello"
