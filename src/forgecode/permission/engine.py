"""权限引擎：前四层判定流水线 + 配置加载。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from forgecode.conversation.history import ToolCall
from forgecode.permission import Category, Decision, Mode, parse_mode
from forgecode.permission.blacklist import hits_blacklist
from forgecode.permission.rule import RuleSet
from forgecode.permission.sandbox import resolve_root, sandbox_ok
from forgecode.permission.settings import (
    SettingsError,
    categorize,
    extract_target,
    friendly_name,
    load_settings,
    to_rule_set,
)


@dataclass
class Engine:
    """前四层判定引擎。"""

    root: str  # 项目根（绝对、已解析符号链接）
    blacklist: list  # 黑名单正则（内置，不可配）
    user: RuleSet
    project: RuleSet
    local: RuleSet
    local_path: str  # 本地层配置文件路径
    _start_mode: Mode = field(default=Mode.DEFAULT)

    def start_mode(self) -> Mode:
        return self._start_mode

    def check(
        self,
        mode: Mode,
        call: ToolCall,
        read_only: bool,
    ) -> tuple[Decision, str]:
        """前四层判定流水线。返回 (裁决, 原因)。"""
        cat = categorize(call.name, read_only)
        friendly = friendly_name(call.name)
        target, is_file, ok = extract_target(call)

        # ① 黑名单（仅命令执行类工具）
        if cat == Category.EXEC and target and hits_blacklist(target):
            return Decision.DENY, f"命中危险命令黑名单：{target[:80]}"

        # ② 沙箱（仅文件类工具）
        if is_file:
            if not ok:
                return Decision.DENY, "无法解析文件路径参数，安全拒绝"
            if not sandbox_ok(self.root, target):
                return Decision.DENY, f"路径在项目目录之外：{target}"

        # ③ 规则引擎（三级优先级：local → project → user）
        for rule_set, layer_name in [
            (self.local, "本地"),
            (self.project, "项目"),
            (self.user, "用户"),
        ]:
            d, hit = rule_set.match(friendly, target)
            if hit:
                if d == Decision.DENY:
                    return Decision.DENY, f"匹配 {layer_name} deny 规则"
                return Decision.ALLOW, ""

        # ④ 模式兜底（只产 Allow/Ask）
        return _mode_fallback(mode, cat, friendly), _ask_reason(mode, cat)


def _mode_fallback(mode: Mode, cat: Category, friendly: str = "") -> Decision:
    """F5 模式兜底矩阵。只产 Allow/Ask。"""
    if cat == Category.READ or mode == Mode.BYPASS:
        return Decision.ALLOW
    if mode == Mode.ACCEPT_EDITS and cat == Category.WRITE:
        return Decision.ALLOW
    return Decision.ASK


def _ask_reason(mode: Mode, cat: Category) -> str:
    """生成 Ask 触发原因文案。"""
    cat_names = {
        Category.READ: "只读",
        Category.WRITE: "文件写",
        Category.EXEC: "命令执行",
    }
    return f"{mode} 模式下 {cat_names.get(cat, '未知')} 类操作需确认"


# ── 引擎构造 ──────────────────────────────────────

# 配置文件路径模板
CONFIG_USER = "~/.forgecode/settings.yaml"
CONFIG_PROJECT = ".forgecode/settings.yaml"
CONFIG_LOCAL = ".forgecode/settings.local.yaml"


def new_engine(root_str: str) -> tuple[Engine, Exception | None]:
    """构造权限引擎。

    即使 resolve_root 失败也返回非 None 的空规则安全引擎 + err。
    配置文件格式错误只降级该文件为空，不致引擎构造失败（N5）。
    唯一致命错：项目根不可解析（返回退化引擎 + err）。
    """
    # 项目根
    try:
        root = resolve_root(root_str)
        fatal_err: Exception | None = None
    except Exception as e:
        root = str(Path(root_str).expanduser().absolute())
        fatal_err = e

    # 加载三层配置
    user_home = str(Path.home())
    user_path = Path(CONFIG_USER.replace("~", user_home))
    project_path = Path(root) / CONFIG_PROJECT
    local_path = Path(root) / CONFIG_LOCAL

    user_settings = _safe_load(user_path)
    project_settings = _safe_load(project_path)
    local_settings = _safe_load(local_path)

    user_rules = to_rule_set(user_settings)
    project_rules = to_rule_set(project_settings)
    local_rules = to_rule_set(local_settings)

    # 启动默认模式：local > project > user
    start_mode = Mode.DEFAULT
    for settings in [local_settings, project_settings, user_settings]:
        if settings.default_mode:
            m, ok = parse_mode(settings.default_mode)
            if ok:
                start_mode = m
                break

    # 黑名单从模块常量导入
    from forgecode.permission.blacklist import _BLACKLIST  # noqa: PLC0415

    engine = Engine(
        root=root,
        blacklist=_BLACKLIST,
        user=user_rules,
        project=project_rules,
        local=local_rules,
        local_path=str(local_path),
        _start_mode=start_mode,
    )

    return engine, fatal_err


def _safe_load(path: Path):  # noqa: F811
    """安全加载配置：文件缺失/格式非法→空 Settings（N5）。"""
    try:
        return load_settings(str(path))
    except SettingsError:
        from forgecode.permission.settings import Settings

        return Settings()
