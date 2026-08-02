"""Stable LAAP runtime API.

This package is the migration boundary for the canonical Agent runtime.
Implementation remains in :mod:`laap.agent_core` during the compatibility
migration; callers should import from ``laap.runtime`` going forward.
"""

from .agent import Agent, AgentConfig, AgentMode, AgentState, LAAPAgent
from .contracts import AgentLifecycle, AgentRuntime
from .adapter import AgentLifecycleAdapter
from .factory import create_runtime_agent, wrap_runtime_agent
from .psi_gateway import PSITurnGateway, PSITurnReceipt
from .subject_policy import RuntimePath, requires_psi
from .cognitive_runtime import (
    CognitiveTurn, CognitiveRuntime, BridgeCognitiveRuntime,
    AGIAgentCognitiveRuntime,
)

__all__ = [
    "Agent", "AgentConfig", "AgentMode", "AgentState", "LAAPAgent",
    "AgentRuntime", "AgentLifecycle", "AgentLifecycleAdapter",
    "create_runtime_agent", "wrap_runtime_agent", "PSITurnGateway", "PSITurnReceipt",
    "RuntimePath", "requires_psi", "CognitiveTurn", "CognitiveRuntime",
    "BridgeCognitiveRuntime", "AGIAgentCognitiveRuntime",
]
