# -*- coding: utf-8 -*-
"""LAAP CLI subcommand: `laap reach`

Exposes Agent-Reach operations through LAAP's CLI:
    laap reach doctor          — full health report
    laap reach status          — compact JSON summary
    laap reach channels        — list channels
    laap reach install [...]   — run installer
    laap reach skill install   — install SKILL.md into LAAP skills dir
    laap reach verify          — run integration smoke tests
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from laap.config.paths import get_laap_root

logger = logging.getLogger(__name__)


def run(args) -> None:
    action = getattr(args, "action", "doctor")

    try:
        from laap.integrations.agent_reach import (
            AgentReachBridge, register_all,
        )
        from laap.integrations.agent_reach import skill_loader
    except ImportError as e:
        print(f"[error] Agent-Reach integration not available: {e}")
        print(f"  Run: pip install -e {get_laap_root() / 'Agent-Reach'}")
        sys.exit(1)
        return

    bridge = AgentReachBridge()

    if action in ("doctor", "status", "channels"):
        if not bridge.available:
            print(f"[error] Agent-Reach unavailable: {bridge.init_error}")
            sys.exit(1)
            return

    if action == "doctor":
        print(bridge.doctor_report())

    elif action == "status":
        print(json.dumps(bridge.summary(), ensure_ascii=False, indent=2))

    elif action == "channels":
        print(json.dumps(bridge.channels(), ensure_ascii=False, indent=2))

    elif action == "install":
        # Pass through extra args after `install`
        extra = getattr(args, "args", []) or []
        channels = ""
        env = "auto"
        safe = False
        dry_run = False
        # Very small arg parser for the passthrough
        i = 0
        while i < len(extra):
            a = extra[i]
            if a == "--safe":
                safe = True
            elif a == "--dry-run":
                dry_run = True
            elif a == "--env":
                env = extra[i + 1] if i + 1 < len(extra) else "auto"
                i += 1
            elif a.startswith("--channels"):
                # support both --channels=x and --channels x
                if "=" in a:
                    channels = a.split("=", 1)[1]
                else:
                    channels = extra[i + 1] if i + 1 < len(extra) else ""
                    i += 1
            i += 1
        print("Running Agent-Reach installer...")
        print("=" * 50)
        out = bridge.install(
            channels=channels, env=env, safe=safe, dry_run=dry_run,
        )
        print(out)

    elif action == "read":
        extra = getattr(args, "args", []) or []
        if not extra:
            print("Usage: laap reach read <url>")
            sys.exit(1)
            return
        url = extra[0]
        print(bridge.read_url(url))

    elif action == "search":
        extra = getattr(args, "args", []) or []
        if not extra:
            print("Usage: laap reach search <query>")
            sys.exit(1)
            return
        query = " ".join(extra)
        print(bridge.search(query))

    elif action == "skill":
        extra = getattr(args, "args", []) or []
        sub = extra[0] if extra else "install"
        if sub == "install":
            status = skill_loader.install_skill(force=True)
            print(f"Skill: {status} → {skill_loader.LAAP_AGENT_REACH_DIR}")
        elif sub in ("uninstall", "remove"):
            status = skill_loader.uninstall_skill()
            print(f"Skill: {status}")
        else:
            print(f"Usage: laap reach skill [install|uninstall]")

    elif action == "verify":
        from laap.integrations.agent_reach import verify as verify_mod
        sys.exit(verify_mod.main())

    elif action == "tools":
        # Show what tools would be registered
        from laap.tools.tool_registry import ToolRegistry
        reg = ToolRegistry()
        register_all(reg)
        reach_tools = [t for t in reg.list() if t.category == "reach"]
        print(f"Registered Agent-Reach tools ({len(reach_tools)}):")
        for t in sorted(reach_tools, key=lambda x: x.name):
            desc = (t.description or "")[:80]
            print(f"  - {t.name}: {desc}")

    else:
        print(f"Unknown action: {action}")
        print("Available: doctor, status, channels, install, read, search,")
        print("           skill, verify, tools")
        sys.exit(1)
