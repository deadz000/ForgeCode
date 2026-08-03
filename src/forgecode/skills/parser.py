"""SKILL.md / tool.json 解析。"""

from __future__ import annotations

import json
import re
import warnings
from pathlib import Path
from typing import Any

import yaml

from forgecode.skills.types import Skill, SkillMeta, SkillSource, ToolSpec

_NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")
_TOOL_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]*$")


def parse_skill_dir(dir_path: Path, source: SkillSource) -> Skill:
    """解析单个 Skill 目录，失败时抛异常由调用方跳过。"""
    skill_md = dir_path / "SKILL.md"
    if not skill_md.is_file():
        raise FileNotFoundError(f"no SKILL.md in {dir_path}")

    meta_dict, body = _parse_frontmatter_and_body(skill_md.read_text(encoding="utf-8"))
    meta = _build_meta(meta_dict)

    tool_specs: list[ToolSpec] = []
    tool_json = dir_path / "tool.json"
    if tool_json.is_file():
        tool_specs = _parse_tool_json(tool_json.read_bytes(), dir_path.resolve())

    return Skill(
        meta=meta,
        prompt_body=body,
        source_dir=dir_path.resolve(),
        source=source,
        tool_specs=tool_specs,
    )


def _parse_frontmatter_and_body(data: str) -> tuple[dict[str, Any], str]:
    lines = data.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("SKILL.md 必须以 --- 开头的 YAML frontmatter 开始")

    end = -1
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end < 0:
        raise ValueError("SKILL.md frontmatter 缺少结束 ---")

    frontmatter = "\n".join(lines[1:end])
    parsed = yaml.safe_load(frontmatter) or {}
    if not isinstance(parsed, dict):
        raise ValueError("SKILL.md frontmatter 必须是 YAML 对象")

    body_lines = lines[end + 1 :]
    while body_lines and not body_lines[0].strip():
        body_lines.pop(0)
    body = "\n".join(body_lines)
    return parsed, body


def _build_meta(raw: dict[str, Any]) -> SkillMeta:
    meta = SkillMeta(
        name=str(raw.get("name", "")),
        description=str(raw.get("description", "")),
        allowed_tools=[str(x) for x in (raw.get("allowed_tools") or [])],
        mode=_normalize_mode(raw.get("mode")),
        fork_context=_normalize_fork_context(raw.get("fork_context")),
        model=raw.get("model"),
    )

    if not _NAME_RE.fullmatch(meta.name) or not (1 <= len(meta.name) <= 32):
        raise ValueError(f"非法 skill name: {meta.name!r}")
    if not meta.description.strip():
        raise ValueError(f"skill {meta.name}: description 不能为空")
    for tool in meta.allowed_tools:
        if not tool:
            raise ValueError(f"skill {meta.name}: 非法 allowed_tools 项 {tool!r}")
    if meta.model is not None and not isinstance(meta.model, str):
        raise ValueError(f"skill {meta.name}: model 必须是字符串")
    return meta


def _normalize_mode(value: Any) -> str:
    if value in (None, "", "inline"):
        return "inline"
    if value == "fork":
        return "fork"
    warnings.warn(f"未知 mode {value!r}，按 inline 处理", stacklevel=3)
    return "inline"


def _normalize_fork_context(value: Any) -> str:
    if value in (None, "", "none"):
        return "none"
    if value in ("recent", "full"):
        return value
    warnings.warn(f"未知 fork_context {value!r}，按 none 处理", stacklevel=3)
    return "none"


def _parse_tool_json(data: bytes, base_dir: Path) -> list[ToolSpec]:
    try:
        obj = json.loads(data)
    except json.JSONDecodeError as e:
        raise ValueError(f"tool.json 解析失败: {e}") from e

    if not isinstance(obj, dict) or not isinstance(obj.get("tools"), list):
        raise ValueError("tool.json 必须包含 tools 数组")

    specs: list[ToolSpec] = []
    for item in obj["tools"]:
        if not isinstance(item, dict):
            raise ValueError("tool.json 的每个工具必须是对象")
        name = item.get("name")
        description = item.get("description")
        input_schema = item.get("input_schema")
        command = item.get("command")
        if not isinstance(name, str) or not _TOOL_NAME_RE.fullmatch(name):
            raise ValueError(f"非法专属工具名: {name!r}")
        if not isinstance(command, list) or not command or not all(isinstance(x, str) and x for x in command):
            raise ValueError(f"专属工具 {name}: command 必须是非空 argv 数组")
        if not isinstance(input_schema, dict):
            raise ValueError(f"专属工具 {name}: input_schema 必须是对象")
        specs.append(
            ToolSpec(
                name=name,
                description=str(description or ""),
                input_schema=input_schema,
                command=list(command),
                base_dir=base_dir,
            )
        )
    return specs
