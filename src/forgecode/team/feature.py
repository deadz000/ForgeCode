"""Team feature flags（FORK_TEAMMATE）。"""

from __future__ import annotations

from typing import Any


def fork_teammate_enabled(cfg: Any) -> bool:
    """读 cfg.features.fork_teammate；缺省 False。"""
    features = getattr(cfg, "features", None)
    if features is None:
        return False
    return bool(getattr(features, "fork_teammate", False))
