# -*- coding: utf-8 -*-
"""Smoke tests for the LAAP × Agent-Reach integration.

Run:
    python -m laap.integrations.agent_reach.verify

Exit code 0 = all checks passed; 1 = at least one failed.
Each check prints [PASS]/[FAIL] with a short detail line.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure d:\LAAP is on sys.path so `laap` imports resolve when running
# this script directly from the repo root.
_LAAP_ROOT = Path(__file__).resolve().parents[3]
if str(_LAAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_LAAP_ROOT))


def _ok(label: str, detail: str = "") -> bool:
    print(f"[PASS] {label}" + (f" — {detail}" if detail else ""))
    return True


def _fail(label: str, detail: str = "") -> bool:
    print(f"[FAIL] {label}" + (f" — {detail}" if detail else ""))
    return False


def check_agent_reach_import() -> bool:
    try:
        import agent_reach
        from agent_reach import AgentReach
        return _ok("Agent-Reach import",
                    f"v{getattr(agent_reach, '__version__', '?')}")
    except Exception as e:
        return _fail("Agent-Reach import", str(e))


def check_laap_adapter_import() -> bool:
    try:
        from laap.integrations.agent_reach import (
            AgentReachBridge, register_all,
        )
        return _ok("LAAP adapter import",
                    "AgentReachBridge + register_all exported")
    except Exception as e:
        return _fail("LAAP adapter import", str(e))


def check_bridge_init() -> bool:
    try:
        from laap.integrations.agent_reach import AgentReachBridge
        b = AgentReachBridge()
        if not b.available:
            return _fail("Bridge init", f"unavailable: {b.init_error}")
        return _ok("Bridge init", "agent_reach loaded")
    except Exception as e:
        return _fail("Bridge init", str(e))


def check_doctor() -> bool:
    try:
        from laap.integrations.agent_reach import AgentReachBridge
        b = AgentReachBridge()
        report = b.doctor()
        if not isinstance(report, dict):
            return _fail("Doctor dict", f"got {type(report).__name__}")
        if "_error" in report:
            return _fail("Doctor dict", report["_error"]["message"])
        return _ok("Doctor dict",
                    f"{len(report)} channels probed")
    except Exception as e:
        return _fail("Doctor dict", str(e))


def check_summary() -> bool:
    try:
        from laap.integrations.agent_reach import AgentReachBridge
        b = AgentReachBridge()
        s = b.summary()
        if not s.get("available"):
            return _fail("Summary", s.get("error", "unavailable"))
        detail = (
            f"ok={s['ok']} warn={s['warn']} off={s['off']} "
            f"total={s['total_channels']}"
        )
        return _ok("Summary", detail)
    except Exception as e:
        return _fail("Summary", str(e))


def check_channels_list() -> bool:
    try:
        from laap.integrations.agent_reach import AgentReachBridge
        b = AgentReachBridge()
        chs = b.channels()
        if not isinstance(chs, list):
            return _fail("Channels list", f"got {type(chs).__name__}")
        names = [c.get("name") for c in chs]
        # Expect at least the zero-config channels
        required = {"web", "youtube", "github", "rss", "v2ex", "exa_search"}
        missing = required - set(names)
        if missing:
            return _fail("Channels list",
                          f"missing expected: {sorted(missing)}")
        return _ok("Channels list", f"{len(chs)} channels registered")
    except Exception as e:
        return _fail("Channels list", str(e))


def check_url_routing() -> bool:
    try:
        from laap.integrations.agent_reach import AgentReachBridge
        b = AgentReachBridge()
        cases = [
            ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "youtube"),
            ("https://github.com/Panniantong/Agent-Reach", "github"),
            ("https://example.com/some/page", "web"),
        ]
        for url, expected in cases:
            ch = b.channel_for_url(url)
            if not ch or ch.get("name") != expected:
                return _fail(
                    "URL routing",
                    f"{url} → {ch}, expected {expected}",
                )
        return _ok("URL routing", "youtube/github/web matched")
    except Exception as e:
        return _fail("URL routing", str(e))


def check_tool_registration() -> bool:
    try:
        from laap.tools.tool_registry import ToolRegistry
        from laap.integrations.agent_reach import register_all
        reg = ToolRegistry()
        register_all(reg)
        expected = {
            "agent_reach_doctor", "agent_reach_status",
            "agent_reach_channels", "agent_reach_read_url",
            "agent_reach_search", "agent_reach_transcribe",
            "agent_reach_install",
        }
        actual = {t.name for t in reg.list()}
        missing = expected - actual
        if missing:
            return _fail("Tool registration",
                          f"missing: {sorted(missing)}")
        # Idempotency check
        register_all(reg)
        return _ok("Tool registration",
                    f"{len(expected)} tools (idempotent)")
    except Exception as e:
        return _fail("Tool registration", str(e))


def check_tool_dispatch() -> bool:
    try:
        from laap.tools.tool_registry import ToolRegistry
        from laap.integrations.agent_reach import register_all
        reg = ToolRegistry()
        register_all(reg)
        # status tool should always return valid JSON
        result = reg.call("agent_reach_status")
        import json
        parsed = json.loads(result)
        if "available" not in parsed:
            return _fail("Tool dispatch", f"no 'available' key: {result[:120]}")
        return _ok("Tool dispatch",
                    f"agent_reach_status → available={parsed.get('available')}")
    except Exception as e:
        return _fail("Tool dispatch", str(e))


def check_skill_install() -> bool:
    try:
        from laap.integrations.agent_reach import skill_loader
        status = skill_loader.install_skill(force=True)
        if status == "installed":
            shim = skill_loader.LAAP_AGENT_REACH_DIR / "agent_reach.py"
            if not shim.exists():
                return _fail("Skill install", "shim file missing")
            return _ok("Skill install",
                        f"installed at {skill_loader.LAAP_AGENT_REACH_DIR}")
        return _fail("Skill install", status)
    except Exception as e:
        return _fail("Skill install", str(e))


CHECKS = [
    check_agent_reach_import,
    check_laap_adapter_import,
    check_bridge_init,
    check_doctor,
    check_summary,
    check_channels_list,
    check_url_routing,
    check_tool_registration,
    check_tool_dispatch,
    check_skill_install,
]


def main() -> int:
    print()
    print("  LAAP × Agent-Reach integration — verification")
    print("  " + "=" * 50)
    print()
    results = [fn() for fn in CHECKS]
    passed = sum(1 for r in results if r)
    total = len(results)
    print()
    print(f"  Result: {passed}/{total} checks passed")
    print()
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
