"""laap/agent_core/model_registry.py — 已迁移到 laap.llm.registry (shim)

本文件原是旧版模型注册表 (4 tier, 25 模型, 成本/能力元数据)。
现已统一到 `laap.llm.registry.ModelRegistry` (88+ 模型, 含连接信息 + 成本/tier)。

向后兼容:
    from laap.agent_core.model_registry import ModelRegistry, ModelTier, ModelEntry
    仍然可用, 实际指向 laap.llm.registry 的实现。
"""
from __future__ import annotations
import warnings

warnings.warn(
    "laap.agent_core.model_registry 已统一到 laap.llm.registry。"
    "请改用 `from laap.llm.registry import ModelRegistry, ModelTier, ModelEntry, get_registry`。",
    DeprecationWarning,
    stacklevel=2,
)

from laap.llm.registry import (
    ModelRegistry, ModelTier, ModelEntry, get_registry, get_model,
)

__all__ = [
    "ModelRegistry", "ModelTier", "ModelEntry", "get_registry", "get_model",
]
