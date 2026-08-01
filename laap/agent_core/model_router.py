"""laap/agent_core/model_router.py — 已迁移到 laap.llm.router (shim)

本文件原是旧版智能路由 (4 复杂度等级)。
现已统一到 `laap.llm.router.ModelRouter`。

向后兼容:
    from laap.agent_core.model_router import ModelRouter
    仍然可用, 实际指向 laap.llm.router.ModelRouter。
"""
from __future__ import annotations
import warnings

warnings.warn(
    "laap.agent_core.model_router 已统一到 laap.llm.router。"
    "请改用 `from laap.llm.router import ModelRouter, route_task, classify_task`。",
    DeprecationWarning,
    stacklevel=2,
)

from laap.llm.router import (
    ModelRouter, get_router, route_task, classify_task,
    SIMPLE_PATTERNS, COMPLEX_PATTERNS, CRITICAL_PATTERNS,
)

__all__ = [
    "ModelRouter", "get_router", "route_task", "classify_task",
    "SIMPLE_PATTERNS", "COMPLEX_PATTERNS", "CRITICAL_PATTERNS",
]
