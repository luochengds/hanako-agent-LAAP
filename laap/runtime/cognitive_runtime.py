"""Unified cognitive runtime contract for AGIAgent/PSIDriver migration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Protocol, runtime_checkable


@dataclass
class CognitiveTurn:
    """State created by the cognitive engine for one subject turn."""

    turn_id: int
    user_input: str
    context: Dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class CognitiveRuntime(Protocol):
    """Single cognitive transaction boundary used by Agent Runtime."""

    def begin_turn(self, user_input: str) -> CognitiveTurn:
        ...

    def complete_turn(self, turn: CognitiveTurn, response: str) -> None:
        ...


class BridgeCognitiveRuntime:
    """Adapt the current LAAP Bridge to the unified cognitive contract."""

    def __init__(self, bridge: Any):
        self.bridge = bridge
        self._turn_count = 0

    def begin_turn(self, user_input: str) -> CognitiveTurn:
        self._turn_count += 1
        context = self.bridge.before_turn(user_input)
        if not isinstance(context, dict):
            context = {"result": context}
        return CognitiveTurn(
            turn_id=self._turn_count,
            user_input=user_input,
            context=context,
        )

    def complete_turn(self, turn: CognitiveTurn, response: str) -> None:
        self.bridge.after_turn(response)


__all__ = ["CognitiveTurn", "CognitiveRuntime", "BridgeCognitiveRuntime"]
