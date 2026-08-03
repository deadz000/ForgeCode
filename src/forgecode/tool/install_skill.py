"""InstallSkill 工具：下载并安装第三方 Skill zip。"""

from __future__ import annotations

from forgecode.skills.install import install_from_url
from forgecode.tool import Result, _parse_args


class InstallSkillTool:
    """从 URL 安装 Skill zip 到 ~/.forgecode/skills/。"""

    read_only = False
    is_system = False

    def __init__(self, catalog, work_dir, on_reloaded=None) -> None:
        self._catalog = catalog
        self._work_dir = work_dir
        self._on_reloaded = on_reloaded

    def name(self) -> str:
        return "install_skill"

    def description(self) -> str:
        return "从 URL 下载 Skill zip 并安装到用户级技能目录。"

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "URL of a Skill zip"},
            },
            "required": ["source"],
        }

    async def execute(self, args: str) -> Result:
        try:
            data = _parse_args(args)
        except ValueError as e:
            return Result(content=str(e), is_error=True)

        source = data.get("source")
        if not isinstance(source, str) or not source:
            return Result(content="缺少必填参数: source", is_error=True)

        try:
            name = await install_from_url(
                source,
                self._catalog,
                self._work_dir,
                on_reloaded=self._on_reloaded,
            )
        except Exception as e:
            return Result(content=f"install failed: {e}", is_error=True)

        return Result(content=f"Skill {name} installed to ~/.forgecode/skills/{name}.")
