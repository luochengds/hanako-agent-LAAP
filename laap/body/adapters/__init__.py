"""LAAP Body Layer — 外部框架适配器。

提供 Body 层与 Hermes 等外部执行框架之间的可选适配器。
默认行为为 no-op / 透传，确保 LAAP 在外部依赖不可用时仍能正常启动。
"""

from __future__ import annotations

from laap.body.adapters.hermes import HermesBodyAdapter

__all__ = ["HermesBodyAdapter"]
