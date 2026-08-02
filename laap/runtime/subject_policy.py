"""Policy separating PSI-owned subject behavior from infrastructure work."""

from __future__ import annotations

from enum import StrEnum


class RuntimePath(StrEnum):
    INPUT = "input"
    DECISION = "decision"
    TOOL_ACTION = "tool_action"
    MEMORY_MUTATION = "memory_mutation"
    RSI_ACTION = "rsi_action"
    OUTPUT = "output"
    INFRASTRUCTURE = "infrastructure"


_PSI_REQUIRED = frozenset({
    RuntimePath.INPUT,
    RuntimePath.DECISION,
    RuntimePath.TOOL_ACTION,
    RuntimePath.MEMORY_MUTATION,
    RuntimePath.RSI_ACTION,
    RuntimePath.OUTPUT,
})


def requires_psi(path: RuntimePath | str) -> bool:
    """Return whether a runtime path represents subject behavior."""
    try:
        path = RuntimePath(path)
    except ValueError:
        raise ValueError(f"Unknown runtime path: {path!r}") from None
    return path in _PSI_REQUIRED


__all__ = ["RuntimePath", "requires_psi"]
