"""Hermes body interface for the LAAP Aether orchestration layer."""

from __future__ import annotations

import logging
from typing import Any, Dict

from laap.orchestration.cognitive_bus import ArisCognitiveBus

logger = logging.getLogger("laap.orchestration.body")


class HermesBodyInterface:
    """Session-aware body adapter that exposes ARIS cognition to the outside world."""

    def __init__(self, cognitive_bus: ArisCognitiveBus) -> None:
        self.bus = cognitive_bus
        self.session_context: Dict[str, Any] = {}

    async def before_turn(
        self, user_message: str, session_id: str = "default"
    ) -> str:
        """Process a user turn, update session history, and return the response."""
        context = {
            "session_id": session_id,
            "history": self.session_context.get("history", []),
            "tools_available": ["terminal", "read_file", "write_file", "search_files"],
        }
        result = await self.bus.process(user_message, context)
        self.session_context.setdefault("history", []).append(
            {
                "user": user_message,
                "aris": result["response"],
                "psi_state": result["psi_state"],
            }
        )
        return result["response"]

    async def execute_tool(self, tool_name: str, params: Dict) -> Dict:
        """Execute a tool by name with the supplied parameters (mock implementation)."""
        logger.info("HermesBody executing tool: %s with %s", tool_name, params)
        return {
            "tool": tool_name,
            "status": "executed",
            "result": f"Mock result for {tool_name}",
        }
