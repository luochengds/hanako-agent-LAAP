# -*- coding: utf-8 -*-
"""Bridge between LAAP and Agent-Reach.

The adapter is intentionally thin: it never reimplements Agent-Reach
functionality, only translates calls and shapes the output for LAAP's
PSI/Harness consumers.

Design notes:
    - Agent-Reach's `doctor` returns a flat dict; we keep that shape but
      add a `summary` block so LAAP's metacognitive layer can read
      channel readiness in one glance.
    - `read_url` and `search` dispatch to the matching channel's own
      `read`/`search` methods when they exist; otherwise they fall back
      to the upstream tools (Jina Reader / Exa via mcporter) exactly as
      Agent-Reach's SKILL.md documents. This preserves Agent-Reach's
      "no wrapper layer" design principle.
    - Failures degrade to plain text — never raise — so a tool error
      cannot crash the PSI kernel loop.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import urllib.request
from typing import Any, Dict, Optional

from laap.config.paths import get_laap_root

logger = logging.getLogger("laap.integrations.agent_reach")

# Agent-Reach is installed as an editable package (pip install -e Agent-Reach).
# Import lazily inside methods so that environments without Agent-Reach still
# import this module safely (the bridge will report unavailable on first use).


def _require_agent_reach():
    """Import agent_reach or raise a helpful error."""
    try:
        import agent_reach  # noqa: F401
        from agent_reach import AgentReach as _AgentReach
        from agent_reach.config import Config as _Config
        from agent_reach.channels import get_all_channels as _get_all
        return _AgentReach, _Config, _get_all
    except ImportError as e:
        raise RuntimeError(
            "Agent-Reach is not installed. Run: "
            f"pip install -e {get_laap_root() / 'Agent-Reach'}"
        ) from e


class AgentReachBridge:
    """LAAP-side facade over Agent-Reach.

    Provides:
        doctor()         → dict of per-channel status
        doctor_report()  → pretty text report
        read_url(url)    → markdown content from any URL (Jina Reader)
        search(query)    → Exa semantic search (via mcporter)
        transcribe(src)  → Whisper transcription (Groq → OpenAI)
        install(opts)    → run installer non-interactively
        channels()       → list of registered channels with tier/backend info
    """

    def __init__(self) -> None:
        self._agent_reach = None
        self._config = None
        self._channels = None
        self._init_error: Optional[str] = None
        try:
            AgentReach, Config, get_all_channels = _require_agent_reach()
            self._config = Config()
            self._agent_reach = AgentReach(self._config)
            self._channels = get_all_channels()
        except Exception as e:  # pragma: no cover — environment-dependent
            self._init_error = str(e)
            logger.warning("AgentReachBridge init failed: %s", e)

    @property
    def available(self) -> bool:
        return self._agent_reach is not None

    @property
    def init_error(self) -> Optional[str]:
        return self._init_error

    # ── Health ──────────────────────────────────────────────────────

    def doctor(self) -> Dict[str, dict]:
        """Return Agent-Reach's per-channel status dict.

        Shape: {channel_name: {status, name, message, tier, backends, active_backend}}
        """
        if not self.available:
            return {"_error": {"status": "error", "message": self._init_error or "unavailable"}}
        try:
            return self._agent_reach.doctor()
        except Exception as e:
            logger.error("doctor() failed: %s", e)
            return {"_error": {"status": "error", "message": str(e)}}

    def doctor_report(self) -> str:
        """Return the rich-text formatted Agent-Reach status report."""
        if not self.available:
            return f"Agent-Reach unavailable: {self._init_error}"
        try:
            return self._agent_reach.doctor_report()
        except Exception as e:
            return f"Agent-Reach doctor_report failed: {e}"

    def summary(self) -> Dict[str, Any]:
        """Compact one-glance summary for LAAP's metacognitive monitor."""
        results = self.doctor()
        if "_error" in results:
            return {"available": False, "error": results["_error"]["message"]}
        ok = sum(1 for r in results.values() if r.get("status") == "ok")
        warn = sum(1 for r in results.values() if r.get("status") == "warn")
        off = sum(1 for r in results.values() if r.get("status") in ("off", "error"))
        return {
            "available": True,
            "version": _safe_version(),
            "total_channels": len(results),
            "ok": ok,
            "warn": warn,
            "off": off,
            "channels": {
                name: {
                    "status": r.get("status"),
                    "active_backend": r.get("active_backend"),
                    "tier": r.get("tier"),
                }
                for name, r in results.items()
            },
        }

    # ── Channels ────────────────────────────────────────────────────

    def channels(self) -> list:
        """List all registered Agent-Reach channels."""
        if not self.available:
            return []
        out = []
        for ch in self._channels or []:
            out.append({
                "name": getattr(ch, "name", ""),
                "description": getattr(ch, "description", ""),
                "backends": list(getattr(ch, "backends", []) or []),
                "tier": getattr(ch, "tier", 0),
                "active_backend": getattr(ch, "active_backend", None),
            })
        return out

    def channel_for_url(self, url: str) -> Optional[Dict[str, Any]]:
        """Find the channel that can handle a given URL."""
        if not self.available:
            return None
        for ch in self._channels or []:
            try:
                if ch.can_handle(url):
                    return {
                        "name": getattr(ch, "name", ""),
                        "description": getattr(ch, "description", ""),
                        "active_backend": getattr(ch, "active_backend", None),
                    }
            except Exception:
                continue
        return None

    # ── Read / Search / Transcribe ──────────────────────────────────

    def read_url(self, url: str, *, timeout: int = 30) -> str:
        """Read any URL via Jina Reader (Agent-Reach's universal backend).

        Mirrors the SKILL.md command: `curl https://r.jina.ai/URL`.
        Returns markdown text. Never raises — failures return error text.
        """
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        try:
            # Prefer channel's own read() if it has one (e.g. WebChannel)
            if self.available:
                for ch in self._channels or []:
                    try:
                        if getattr(ch, "name", "") == "web" and hasattr(ch, "read"):
                            return ch.read(url)
                    except Exception:
                        pass
            # Fallback: direct Jina Reader call
            jina_url = f"https://r.jina.ai/{url}"
            req = urllib.request.Request(
                jina_url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                    "Accept": "text/plain",
                },
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except Exception as e:
            return f"[AgentReach read_url error] {url}: {e}"

    def search(self, query: str, *, max_results: int = 5) -> str:
        """Run an Exa semantic search via mcporter (Agent-Reach's search backend).

        Mirrors the SKILL.md flow: `mcporter call exa.search(query=...)`.
        Returns formatted text result. Never raises.
        """
        mcporter = shutil.which("mcporter")
        if not mcporter:
            return (
                "[AgentReach search error] mcporter not installed. "
                "Run: npm install -g mcporter && mcporter config add exa https://mcp.exa.ai/mcp"
            )
        try:
            # Use mcporter's CLI to invoke Exa search
            result = subprocess.run(
                [mcporter, "call", f"exa.search(query={query}, numResults={max_results})"],
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                text=True,
            )
            output = (result.stdout or "") + (result.stderr or "")
            if result.returncode != 0:
                return f"[AgentReach search error] mcporter returned {result.returncode}: {output}"
            return output.strip() or "[AgentReach search] no results"
        except subprocess.TimeoutExpired:
            return f"[AgentReach search error] timeout for query: {query}"
        except Exception as e:
            return f"[AgentReach search error] {e}"

    def transcribe(self, source: str, *, provider: str = "auto") -> str:
        """Transcribe audio/video URL or local file via Whisper (Groq → OpenAI).

        Delegates to Agent-Reach's `agent_reach.transcribe.transcribe`.
        """
        if not self.available:
            return f"[AgentReach transcribe error] unavailable: {self._init_error}"
        try:
            from agent_reach.transcribe import transcribe as _transcribe
            return _transcribe(source, provider=provider, config=self._config)
        except Exception as e:
            return f"[AgentReach transcribe error] {e}"

    # ── Install / Setup ─────────────────────────────────────────────

    def install(self, *, safe: bool = False, dry_run: bool = False,
                channels: str = "", env: str = "auto") -> str:
        """Run Agent-Reach installer non-interactively.

        Args mirror `agent-reach install` flags. Returns captured stdout.
        """
        if not self.available:
            return f"[AgentReach install error] unavailable: {self._init_error}"
        agent_reach_bin = shutil.which("agent-reach")
        if not agent_reach_bin:
            return (
                "[AgentReach install error] agent-reach CLI not on PATH. "
                f"Run: pip install -e {get_laap_root() / 'Agent-Reach'}"
            )
        cmd = [agent_reach_bin, "install", "--env", env]
        if safe:
            cmd.append("--safe")
        if dry_run:
            cmd.append("--dry-run")
        if channels:
            cmd.extend(["--channels", channels])
        try:
            result = subprocess.run(
                cmd, capture_output=True, encoding="utf-8",
                errors="replace", timeout=600, text=True,
            )
            return (result.stdout or "") + (result.stderr or "")
        except Exception as e:
            return f"[AgentReach install error] {e}"


def _safe_version() -> str:
    try:
        import agent_reach
        return getattr(agent_reach, "__version__", "unknown")
    except Exception:
        return "unknown"


# ── Singleton ──────────────────────────────────────────────────────

_default_bridge: Optional[AgentReachBridge] = None


def get_bridge() -> AgentReachBridge:
    """Return a process-wide AgentReachBridge singleton."""
    global _default_bridge
    if _default_bridge is None:
        _default_bridge = AgentReachBridge()
    return _default_bridge
