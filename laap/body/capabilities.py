"""LAAP Body — Capabilities Reporter.

Collects and formats an honest inventory of LAAP body subsystems:
tools, LLM providers, gateways, skills, and plugins.  Each capability is
labelled ``stable``, ``beta``, or ``placeholder`` so that users and the
Hermes-driven backfill spec can see what is actually implemented.
"""

from __future__ import annotations

import logging
import os
from typing import Dict, List, Optional

from laap.llm import transports as llm_transports
from laap.plugins.manager import PluginManager
from laap.skills.engine import SkillEngine
from laap.tools.tool_registry import list_tools

logger = logging.getLogger("laap.body.capabilities")


class CapabilitiesReporter:
    """Collect capabilities from LAAP body subsystems and render them."""

    # Tool names/categories considered stable for day-to-day agent work.
    STABLE_TOOLS = frozenset(
        {"filesystem", "terminal", "web_search", "read_file", "run_command", "browser_navigate"}
    )
    # Tool names/categories that exist but are still maturing.
    BETA_TOOLS = frozenset({"shell", "vision", "memory_tool", "kanban", "delegate", "mcp"})
    # Tool names/categories that are not really implemented yet.
    PLACEHOLDER_TOOLS = frozenset({"image_gen", "video_gen", "tts"})

    # Known gateway platforms and their honest status.
    STABLE_GATEWAYS = frozenset()
    BETA_GATEWAYS = frozenset({"FeishuGatewayAdapter"})
    PLACEHOLDER_GATEWAYS = frozenset({"telegram", "discord", "slack", "whatsapp", "sms"})

    # Known LLM transport classes and their honest status.
    STABLE_PROVIDERS = frozenset({"AnthropicTransport", "OpenAITransport"})
    BETA_PROVIDERS = frozenset({"OllamaTransport", "FallbackTransport"})

    SKILL_STATUS = "beta"
    PLUGIN_STATUS = "beta"

    def __init__(
        self,
        skills_dir: Optional[str] = None,
        plugins_dir: Optional[str] = None,
    ) -> None:
        self.items: List[Dict[str, str]] = []
        self.items.extend(self._collect_tools())
        self.items.extend(self._collect_providers())
        self.items.extend(self._collect_gateways())
        self.items.extend(self._collect_skills(skills_dir))
        self.items.extend(self._collect_plugins(plugins_dir))

    @staticmethod
    def _laap_root() -> str:
        """Return the repository root used for default skill/plugin paths."""
        return os.environ.get("LAAP_ROOT") or os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )

    def _classify_tool(self, name: str, category: str) -> str:
        if name in self.STABLE_TOOLS or category in self.STABLE_TOOLS:
            return "stable"
        if name in self.PLACEHOLDER_TOOLS or category in self.PLACEHOLDER_TOOLS:
            return "placeholder"
        if name in self.BETA_TOOLS or category in self.BETA_TOOLS:
            return "beta"
        # Unknown tools are reported cautiously rather than over-promising.
        return "beta"

    def _collect_tools(self) -> List[Dict[str, str]]:
        items: List[Dict[str, str]] = []
        try:
            for tool in list_tools():
                name = tool.get("name", "unknown")
                category = tool.get("category", "general") or "general"
                items.append(
                    {
                        "category": "Tools",
                        "name": name,
                        "status": self._classify_tool(name, category),
                        "description": " ".join((tool.get("description") or "").split())[:70],
                    }
                )
        except Exception as exc:
            logger.warning("Failed to collect tools: %s", exc)
        return items

    def _collect_providers(self) -> List[Dict[str, str]]:
        items: List[Dict[str, str]] = []
        try:
            for name in getattr(llm_transports, "__all__", []):
                if name in ("LLMTransport", "LLMResponse"):
                    continue
                cls = getattr(llm_transports, name, None)
                if name in self.STABLE_PROVIDERS:
                    status = "stable"
                elif name in self.BETA_PROVIDERS:
                    status = "beta"
                else:
                    status = "beta"
                items.append(
                    {
                        "category": "LLM Providers",
                        "name": name,
                        "status": status,
                        "description": " ".join((getattr(cls, "__doc__", "") or "").split())[:70],
                    }
                )
        except Exception as exc:
            logger.warning("Failed to collect LLM providers: %s", exc)
        return items

    def _collect_gateways(self) -> List[Dict[str, str]]:
        items: List[Dict[str, str]] = []
        try:
            from laap import gateway

            for name in sorted(self.BETA_GATEWAYS):
                cls = getattr(gateway, name, None)
                if cls is None:
                    continue
                items.append(
                    {
                        "category": "Gateways",
                        "name": name,
                        "status": "beta",
                        "description": " ".join((getattr(cls, "__doc__", "") or "").split())[:70],
                    }
                )
            for name in sorted(self.PLACEHOLDER_GATEWAYS):
                items.append(
                    {
                        "category": "Gateways",
                        "name": name,
                        "status": "placeholder",
                        "description": "Not implemented",
                    }
                )
        except Exception as exc:
            logger.warning("Failed to collect gateways: %s", exc)
        return items

    def _collect_skills(self, skills_dir: Optional[str]) -> List[Dict[str, str]]:
        items: List[Dict[str, str]] = []
        try:
            if skills_dir is None:
                skills_dir = os.path.join(self._laap_root(), "skills")
            engine = SkillEngine(str(skills_dir))
            engine.load_all()
            for skill in engine.list_skills():
                items.append(
                    {
                        "category": "Skills",
                        "name": skill.name,
                        "status": self.SKILL_STATUS,
                        "description": " ".join((skill.description or "").split())[:70],
                    }
                )
        except Exception as exc:
            logger.debug("Failed to collect skills: %s", exc)
        return items

    def _collect_plugins(self, plugins_dir: Optional[str]) -> List[Dict[str, str]]:
        items: List[Dict[str, str]] = []
        try:
            if plugins_dir is None:
                plugins_dir = os.path.join(self._laap_root(), "plugins")
            manager = PluginManager(str(plugins_dir))
            manager.load_all()
            for plugin in manager.list_plugins():
                status = self.PLUGIN_STATUS if plugin.enabled else "disabled"
                items.append(
                    {
                        "category": "Plugins",
                        "name": plugin.name,
                        "status": status,
                        "description": " ".join((plugin.description or "").split())[:70],
                    }
                )
        except Exception as exc:
            logger.debug("Failed to collect plugins: %s", exc)
        return items

    def to_table(self) -> str:
        """Return a plain-text table of capabilities."""
        if not self.items:
            return "No capabilities discovered."
        lines = [
            f"{'Category':<18} {'Name':<30} {'Status':<12} Description",
            "-" * 78,
        ]
        for item in self.items:
            lines.append(
                f"{item['category']:<18} {item['name']:<30} {item['status']:<12} {item['description']}"
            )
        return "\n".join(lines)

    def to_markdown(self) -> str:
        """Return a markdown grouped list of capabilities."""
        lines = ["# LAAP Capabilities"]
        current_category: Optional[str] = None
        for item in self.items:
            if item["category"] != current_category:
                current_category = item["category"]
                lines.append(f"\n## {current_category}")
            lines.append(
                f"- **{item['name']}** (`{item['status']}`) — {item['description']}"
            )
        return "\n".join(lines)
