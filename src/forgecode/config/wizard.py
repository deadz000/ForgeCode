"""交互式配置向导：首次使用引导用户创建 forgecode.yaml。"""

from __future__ import annotations

import getpass
from pathlib import Path

import yaml

from forgecode.config.schema import AppConfig, ProviderConfig


def _prompt(prompt_text: str, default: str | None = None) -> str:
    """带默认值提示的输入函数。"""
    if default:
        result = input(f"{prompt_text} [{default}]: ").strip()
        return result if result else default
    while True:
        result = input(f"{prompt_text}: ").strip()
        if result:
            return result
        print("  此项不能为空，请重新输入。")


def run_wizard() -> AppConfig:
    """
    交互式配置向导。

    优先引导用户创建全局配置（~/.forgecode/forgecode.yaml），
    用户可选择改为在项目目录创建（./forgecode.yaml）。
    """
    print()
    print("=" * 50)
    print("  未找到 forgecode.yaml，我们来创建第一个配置")
    print("=" * 50)
    print()

    # ── 选择配置位置 ──
    choice = input("创建全局配置 (~/.forgecode/forgecode.yaml)？[Y/n]: ").strip().lower()
    if choice in ("n", "no"):
        target_dir = Path.cwd()
        print(f"  将在当前目录创建: {target_dir / 'forgecode.yaml'}")
    else:
        target_dir = Path.home() / ".forgecode"
        target_dir.mkdir(parents=True, exist_ok=True)
        print(f"  将在全局目录创建: {target_dir / 'forgecode.yaml'}")

    print()

    # ── 逐字段收集 ──
    name = _prompt("供应商名称 (name)")
    protocol = _prompt("协议类型 (anthropic / openai)", "anthropic")

    # 根据协议给出默认 base_url
    default_url = (
        "https://api.anthropic.com" if protocol.lower() == "anthropic" else "https://api.openai.com/v1"
    )
    model = _prompt("模型名称 (model)")
    base_url = _prompt("API 地址 (base_url)", default_url)
    api_key = getpass.getpass("认证密钥 (api_key): ").strip()
    if not api_key:
        api_key = getpass.getpass("密钥不能为空，请重新输入认证密钥 (api_key): ").strip()
        if not api_key:
            raise ValueError("api_key 为必填项，向导取消。")

    thinking_input = input("启用扩展思考？[y/N]: ").strip().lower()
    thinking = thinking_input in ("y", "yes")

    # ── 构造配置 ──
    provider = ProviderConfig(
        name=name,
        protocol=protocol.lower(),
        model=model,
        base_url=base_url,
        api_key=api_key,
        thinking=thinking,
    )

    # ── 写入 YAML ──
    yaml_path = target_dir / "forgecode.yaml"
    yaml_data = {
        "providers": [
            {
                "name": provider.name,
                "protocol": provider.protocol,
                "model": provider.model,
                "base_url": provider.base_url,
                "api_key": provider.api_key,
                "thinking": provider.thinking,
            }
        ]
    }
    yaml_path.write_text(
        yaml.dump(yaml_data, allow_unicode=True, default_flow_style=False),
        encoding="utf-8",
    )

    print()
    print(f"  ✓ 配置已保存到: {yaml_path}")
    print()

    return AppConfig(providers=[provider], active_provider_name=provider.name)
