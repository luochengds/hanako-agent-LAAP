"""LAAP — Integrations layer.

Hosts adapters that bridge external capability layers into LAAP's
tool registry, skill system, and MCP fabric.

Available integrations:
    - agent_reach: Internet access layer (15+ platform channels)
    - claw_in_chrome: 浏览器自动化（真实 Chrome + 国产模型供应商预设）
"""

from __future__ import annotations

__all__ = ["agent_reach", "claw_in_chrome"]
