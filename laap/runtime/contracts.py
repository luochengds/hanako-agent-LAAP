"""Stable contracts shared by current and legacy Agent implementations."""

from __future__ import annotations

from typing import Any, Dict, Protocol, runtime_checkable


@runtime_checkable
class AgentRuntime(Protocol):
    """Minimum lifecycle contract required by API, CLI and adapters."""

    id: str
    config: Any

    def run(self, task: str) -> str:
        ...

    def status(self) -> Dict[str, Any]:
        ...


@runtime_checkable
class AgentLifecycle(AgentRuntime, Protocol):
    """Optional richer lifecycle fields exposed by legacy-compatible agents."""

    alive: bool
    step_count: int


__all__ = ["AgentRuntime", "AgentLifecycle"]
