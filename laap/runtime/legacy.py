"""Compatibility exports for legacy LAAP Agent implementations.

These names keep historical CLI/API behavior stable while callers migrate to
``laap.runtime.Agent``.  New runtime code should not import this module.
"""

from laap.agent.base import Agent, AgentConfig
from laap.agent.lifelike import LifelikeAgent, LifelikeConfig
from laap.agent.codex import CodexAgent, CodexConfig

__all__ = [
    "Agent",
    "AgentConfig",
    "LifelikeAgent",
    "LifelikeConfig",
    "CodexAgent",
    "CodexConfig",
]
