"""LAAP SDK 适配器集合。"""

from __future__ import annotations

__all__ = [
    "HermesAdapter",
    "OpenClawAdapter",
    "ClaudeCodeAdapter",
    "GenericAdapter",
]


def __getattr__(name: str):
    """Lazy load adapters to avoid circular imports."""
    if name == "HermesAdapter":
        from laap.sdk.adapters.hermes import HermesAdapter

        return HermesAdapter
    elif name == "OpenClawAdapter":
        from laap.sdk.adapters.openclaw import OpenClawAdapter

        return OpenClawAdapter
    elif name == "ClaudeCodeAdapter":
        from laap.sdk.adapters.claude_code import ClaudeCodeAdapter

        return ClaudeCodeAdapter
    elif name == "GenericAdapter":
        from laap.sdk.adapters.generic import GenericAdapter

        return GenericAdapter
    raise AttributeError(f"module 'laap.sdk.adapters' has no attribute {name!r}")
