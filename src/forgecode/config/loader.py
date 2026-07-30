"""配置加载：YAML 解析、两层合并、供应商选择。"""

from __future__ import annotations

from pathlib import Path

import yaml

from forgecode.config.schema import AppConfig, ProviderConfig


def _global_config_path() -> Path:
    """全局配置文件路径：~/.forgecode/forgecode.yaml"""
    return Path.home() / ".forgecode" / "forgecode.yaml"


def _project_config_path() -> Path:
    """项目级配置文件路径：当前工作目录下的 forgecode.yaml"""
    return Path.cwd() / "forgecode.yaml"


def _load_yaml(path: Path) -> dict[str, object] | None:
    """读取单个 YAML 文件，不存在返回 None。"""
    if not path.exists():
        return None
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data is None:
        return None
    if not isinstance(data, dict):
        raise ValueError(f"配置文件格式错误，应为字典: {path}")
    return data


def _parse_providers(data: dict[str, object]) -> list[ProviderConfig]:
    """从 YAML 数据中解析供应商列表。"""
    raw_list = data.get("providers", [])
    if not isinstance(raw_list, list):
        raise ValueError("配置文件中 providers 应为列表")
    result: list[ProviderConfig] = []
    for entry in raw_list:
        if not isinstance(entry, dict):
            raise ValueError(f"provider 配置项应为字典: {entry}")
        # 校验必填字段
        for field in ("name", "protocol", "model", "base_url", "api_key"):
            if field not in entry:
                raise ValueError(f"provider 缺少必填字段: {field}")
        result.append(
            ProviderConfig(
                name=str(entry["name"]),
                protocol=str(entry["protocol"]).lower(),
                model=str(entry["model"]),
                base_url=str(entry["base_url"]),
                api_key=str(entry["api_key"]),
                thinking=bool(entry.get("thinking", False)),
                context_window=int(entry.get("context_window", 0)),
            )
        )
    return result


def _merge_configs(
    global_data: dict[str, object] | None,
    project_data: dict[str, object] | None,
) -> list[ProviderConfig]:
    """两层合并：项目级同名 provider 覆盖全局级。"""
    globals_list = _parse_providers(global_data) if global_data else []
    projects_list = _parse_providers(project_data) if project_data else []

    # 按 name 建立索引：项目级覆盖全局级
    merged: dict[str, ProviderConfig] = {}
    for p in globals_list:
        merged[p.name] = p
    for p in projects_list:
        merged[p.name] = p  # 同名覆盖

    return list(merged.values())


def load_config(provider_name: str | None = None) -> AppConfig:
    """加载配置，返回 AppConfig。

    加载顺序：全局 YAML → 项目级 YAML 合并。
    若最终 providers 为空，启动配置向导。
    """
    global_data = _load_yaml(_global_config_path())
    project_data = _load_yaml(_project_config_path())

    providers = _merge_configs(global_data, project_data)

    if not providers:
        # 延迟导入，避免反向依赖
        from forgecode.config.wizard import run_wizard

        return run_wizard()

    # 选择活动供应商
    if provider_name is None:
        active_name = providers[0].name
    else:
        matching = [p for p in providers if p.name == provider_name]
        if not matching:
            names = ", ".join(p.name for p in providers)
            raise ValueError(f"未找到供应商 '{provider_name}'，可用: {names}")
        active_name = matching[0].name

    return AppConfig(providers=providers, active_provider_name=active_name)
