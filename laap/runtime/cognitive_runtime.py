"""Unified cognitive runtime contract for AGIAgent/PSIDriver migration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Protocol, runtime_checkable
import os
from pathlib import Path


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


class AGIAgentCognitiveRuntime:
    """Adapt the integrated AGIAgent cognitive pipeline.

    This adapter is the canonical default; the existing Bridge remains an
    explicit compatibility fallback. The AGIAgent pipeline performs the full cognitive assessment before language
    I/O; the response is recorded for the next learning/state persistence step
    without running a second PSI cycle for the same user turn.
    """

    def __init__(self, agent: Any, *, strict_persistence: bool | None = None):
        self.agent = agent
        self._turn_count = 0
        self.strict_persistence = (
            os.environ.get("LAAP_PERSISTENCE_STRICT", "0") == "1"
            if strict_persistence is None else strict_persistence
        )

    @classmethod
    def create(cls, *, name: str = "LAAP-Agent") -> "AGIAgentCognitiveRuntime":
        from laap.agi.core import AGIAgent

        state_dir = os.environ.get("LAAP_AGI_STATE_DIR")
        if state_dir is None:
            try:
                from laap.config.paths import get_state_dir
                state_dir = str(Path(get_state_dir()) / "agi")
            except Exception:
                state_dir = None
        return cls(AGIAgent(name=name, state_dir=state_dir))

    def begin_turn(self, user_input: str) -> CognitiveTurn:
        load_status = getattr(self.agent, "_last_load_status", {}) or {}
        if self.strict_persistence and load_status.get("degraded", False):
            raise RuntimeError(
                "AGIAgent persistence is degraded; strict runtime blocks the subject turn: "
                f"{load_status}"
            )
        self._turn_count += 1
        report = self.agent.process_interaction(user_input, use_psi=True)
        if not isinstance(report, dict):
            report = {"result": report}
        return CognitiveTurn(
            turn_id=self._turn_count,
            user_input=user_input,
            context=report,
        )

    def complete_turn(self, turn: CognitiveTurn, response: str) -> None:
        # The AGIAgent cycle already performs perception/learning for this
        # input. Persist the resulting cognitive state without a duplicate
        # second cycle for the generated response.
        self.agent.last_response = response
        save = getattr(self.agent, "save", None)
        if callable(save):
            save()


__all__ = [
    "CognitiveTurn",
    "CognitiveRuntime",
    "BridgeCognitiveRuntime",
    "AGIAgentCognitiveRuntime",
]
