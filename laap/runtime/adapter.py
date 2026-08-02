"""Adapters that normalize legacy and new Agent lifecycle surfaces."""

from __future__ import annotations

from typing import Any, Dict


class AgentLifecycleAdapter:
    """Expose the stable runtime contract around an arbitrary Agent backend.

    The adapter is intentionally thin: it does not alter backend behavior and
    only fills lifecycle fields that older API/CLI code expects.
    """

    def __init__(self, backend: Any):
        self.backend = backend

    @property
    def id(self) -> str:
        value = getattr(self.backend, "id", None)
        if value is None:
            value = getattr(self.backend, "_agent_id", "")
        return str(value)

    @property
    def config(self) -> Any:
        return getattr(self.backend, "config", None)

    @property
    def alive(self) -> bool:
        value = getattr(self.backend, "alive", None)
        if value is not None:
            return bool(value)
        return bool(getattr(self.backend, "running", True))

    @property
    def step_count(self) -> int:
        value = getattr(self.backend, "step_count", None)
        if value is not None:
            return int(value)
        status = self.status()
        return int(status.get(
            "steps",
            status.get("step_count", status.get("total_turns", 0)),
        ) or 0)

    def run(self, task: str) -> str:
        return self.backend.run(task)

    def status(self) -> Dict[str, Any]:
        status_fn = getattr(self.backend, "status", None)
        if callable(status_fn):
            result = status_fn()
            return dict(result) if isinstance(result, dict) else {"status": result}
        get_status = getattr(self.backend, "get_status", None)
        if callable(get_status):
            result = get_status()
            return dict(result) if isinstance(result, dict) else {"status": result}
        return {
            "id": self.id,
            "alive": self.alive,
            "steps": 0,
        }

    def __getattr__(self, name: str) -> Any:
        return getattr(self.backend, name)


__all__ = ["AgentLifecycleAdapter"]
