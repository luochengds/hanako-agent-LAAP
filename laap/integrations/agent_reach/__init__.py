# -*- coding: utf-8 -*-
"""LAAP × Agent-Reach integration adapter.

Agent-Reach is a capability layer that gives AI agents one-click access
to 15+ internet platforms (YouTube, Twitter, Reddit, GitHub, B站, 小红书,
etc.). It handles installation, health-checks, and backend routing; the
actual reading/searching is performed by upstream tools.

This adapter bridges Agent-Reach into LAAP:
    - Registers Agent-Reach as LAAP tools (doctor, status, read, search,
      transcribe, install) following the `register_all(registry)` convention
    - Auto-installs Agent-Reach's SKILL.md into LAAP's skills directory
    - Exposes a bridge class for programmatic use from the PSI/Harness layers

Usage:
    from laap.integrations.agent_reach import register_all, AgentReachBridge

    register_all(registry)              # auto-register tools
    bridge = AgentReachBridge()         # programmatic access
    report = bridge.doctor_report()
"""

from __future__ import annotations

from laap.integrations.agent_reach.adapter import AgentReachBridge
from laap.integrations.agent_reach.tools import register_all

__all__ = ["AgentReachBridge", "register_all"]
__version__ = "1.5.0"  # mirrors bundled Agent-Reach version
