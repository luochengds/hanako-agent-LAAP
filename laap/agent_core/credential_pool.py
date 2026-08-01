"""laap/agent_core/credential_pool.py — 已迁移到 laap.llm.credential_pool (shim)

本文件原是旧版凭证池 (5 provider, 配额管理)。
现已统一到 `laap.llm.credential_pool.CredentialPool` (26 provider, 别名 + 持久化)。

向后兼容:
    from laap.agent_core.credential_pool import CredentialPool
    仍然可用, 实际指向 laap.llm.credential_pool.CredentialPool。

注意: 旧版的配额管理 (quota/used) 已合入新版, 通过 add_key(provider, key, quota=...) 设置。
"""
from __future__ import annotations
import warnings

warnings.warn(
    "laap.agent_core.credential_pool 已统一到 laap.llm.credential_pool。"
    "请改用 `from laap.llm.credential_pool import CredentialPool, credential_pool`。",
    DeprecationWarning,
    stacklevel=2,
)

from laap.llm.credential_pool import (
    CredentialPool, credential_pool, get_api_key, has_api_key,
)

__all__ = ["CredentialPool", "credential_pool", "get_api_key", "has_api_key"]
