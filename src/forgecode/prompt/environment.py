"""环境信息采集与渲染。"""

from __future__ import annotations

import os
import platform
import subprocess
from dataclasses import dataclass
from datetime import date


@dataclass
class Environment:
    """运行环境信息，供模型感知当前上下文。"""

    working_dir: str = ""
    platform: str = ""
    date: str = ""
    git_status: str = ""
    version: str = ""
    model: str = ""

    def render(self) -> str:
        """渲染为「环境信息」文本段。

        逐行 Key: Value，空值项省略。
        """
        lines: list[str] = ["## 环境信息"]
        items = [
            ("工作目录", self.working_dir),
            ("平台", self.platform),
            ("日期", self.date),
            ("Git 状态", self.git_status),
            ("应用版本", self.version),
            ("当前模型", self.model),
        ]
        for label, value in items:
            if value:
                lines.append(f"- {label}: {value}")
        return "\n".join(lines)


def gather_environment(version: str, model: str) -> Environment:
    """采集当前运行环境信息。

    - working_dir: os.getcwd()，捕获 OSError 留空。
    - platform: sys.platform。
    - date: 当日 ISO 日期。
    - git_status: git status --porcelain 摘要，2s 超时；失败/非 git 目录则留空。
    - version / model: 由调用方传入。
    - 不读取任何环境变量（避免密钥泄漏）。
    """
    try:
        cwd = os.getcwd()
    except OSError:
        cwd = ""

    git_summary = _collect_git_status()

    return Environment(
        working_dir=cwd,
        platform=platform.system().lower() or "",
        date=date.today().isoformat(),
        git_status=git_summary,
        version=version,
        model=model,
    )


def _collect_git_status() -> str:
    """采集 git status --porcelain 摘要。

    返回码非零 / FileNotFoundError / TimeoutExpired / 非 git 目录 → 返回 ""。
    有输出时取前 20 行摘要。
    """
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=2.0,
        )
    except FileNotFoundError:
        return ""
    except subprocess.TimeoutExpired:
        return ""
    except OSError:
        return ""

    if result.returncode != 0:
        return ""

    output = result.stdout.strip()
    if not output:
        return "（工作区干净）"

    lines = output.split("\n")
    if len(lines) > 20:
        return f"{len(lines)} 个文件有改动"
    return f"{len(lines)} 个文件有改动:\n" + "\n".join(f"  {line}" for line in lines)
