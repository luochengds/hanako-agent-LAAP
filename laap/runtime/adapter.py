"""Adapters that normalize legacy and new Agent lifecycle surfaces."""

from __future__ import annotations

import inspect
from typing import Any, Dict


class AgentLifecycleAdapter:
    """Expose the stable runtime contract around an arbitrary Agent backend.

    The adapter is intentionally thin: it does not alter backend behavior and
    only fills lifecycle fields that older API/CLI code expects.
    """

    def __init__(self, backend: Any, *, psi_gateway: Any = None):
        self.backend = backend
        self.psi_gateway = psi_gateway

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
        if self.psi_gateway is not None:
            return self.psi_gateway.invoke(task, lambda: self.backend.run(task))
        return self.backend.run(task)

    def _call_chat_backend(self, message: str, *args: Any, **kwargs: Any) -> Any:
        """Call backends with their supported chat signature."""
        method = self.backend.chat
        signature = inspect.signature(method)
        parameters = signature.parameters
        accepts_var_kw = any(
            p.kind == inspect.Parameter.VAR_KEYWORD
            for p in parameters.values()
        )
        if not accepts_var_kw:
            kwargs = {k: v for k, v in kwargs.items() if k in parameters}
        positional_capacity = sum(
            p.kind in (inspect.Parameter.POSITIONAL_ONLY,
                        inspect.Parameter.POSITIONAL_OR_KEYWORD)
            for p in parameters.values()
        )
        return method(message, *args[:max(0, positional_capacity - 1)], **kwargs)

    def chat(self, message: str, *args: Any, **kwargs: Any) -> Any:
        operation = lambda: self._call_chat_backend(message, *args, **kwargs)
        if self.psi_gateway is not None:
            return self.psi_gateway.invoke(message, operation)
        return operation()

    def chat_stream(self, message: str, *args: Any, **kwargs: Any) -> Any:
        operation = lambda: self.backend.chat_stream(message, *args, **kwargs)
        if self.psi_gateway is not None:
            return self.psi_gateway.stream(message, operation)
        return operation()

    def execute_tool(self, name: str, **kwargs: Any) -> Any:
        operation = lambda: self.backend.execute_tool(name, **kwargs)
        if self.psi_gateway is not None:
            return self.psi_gateway.invoke(f"tool:{name}", operation)
        return operation()

    def call_tool(self, name: str, **kwargs: Any) -> Any:
        operation = lambda: self.backend.call_tool(name, **kwargs)
        if self.psi_gateway is not None:
            return self.psi_gateway.invoke(f"tool:{name}", operation)
        return operation()

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
