"""Factories for migrating legacy API/CLI callers to the canonical runtime."""

from __future__ import annotations

from typing import Any, Optional

from .adapter import AgentLifecycleAdapter
from .agent import Agent, AgentConfig
from .psi_gateway import PSITurnGateway


def wrap_runtime_agent(backend: Any) -> AgentLifecycleAdapter:
    """Put an existing Agent implementation behind the mandatory PSI gate."""
    return AgentLifecycleAdapter(backend, psi_gateway=PSITurnGateway.default())


def create_runtime_agent(
    config: Optional[AgentConfig] = None,
    *,
    llm_factory: Any = None,
    **kwargs: Any,
) -> AgentLifecycleAdapter:
    """Create the canonical AGI Agent behind the legacy lifecycle contract.

    ``mode='agi'`` intentionally reuses the existing AGIBrain implementation
    while exposing the new ``laap.runtime`` boundary.  The adapter keeps API
    and CLI fields stable during the migration.
    """
    backend_kwargs = dict(kwargs)
    if llm_factory is not None:
        backend_kwargs["llm_factory"] = llm_factory
    backend = Agent(config=config, mode="agi", **backend_kwargs)
    return wrap_runtime_agent(backend)


__all__ = ["create_runtime_agent", "wrap_runtime_agent"]
