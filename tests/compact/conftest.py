"""compact 包共享测试 fixtures。"""

from __future__ import annotations

import pytest


@pytest.fixture
def tmp_workspace(tmp_path):
    """临时工作区，用于会话目录创建测试。"""
    return str(tmp_path)
