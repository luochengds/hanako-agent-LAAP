"""Bridge module: incorporates the quantum cognition engine into the existing
PSICognition class as a selectable backend mode.

Usage:
    from laap.agent_core.quantum_cognition.bridge import enable_quantum_cognition

    # In agent.py or your entry point:
    enable_quantum_cognition(agent, mode='hybrid')

This patches the existing PSICognition-based flow without breaking any
existing tests or backward compatibility.
"""

from __future__ import annotations

import logging
from typing import Optional

from .psi_quantum import (
    PsiQuantumCognition,
    QuantumCognitionConfig,
    QuantumMode,
)

logger = logging.getLogger('quantum_cognition.bridge')


def enable_quantum_cognition(
    agent: object,
    mode: str = 'hybrid',
    dim_state: int = 8,
    **kwargs,
) -> PsiQuantumCognition:
    """Enable the quantum cognition engine on an existing agent.

    Replaces ``agent.psi_cognition`` (or creates it) with a quantum-aware
    ``PsiQuantumCognition`` instance.  The original heuristic methods
    (``perceive``, ``select_intention``, ``integrate``) remain accessible
    via ``agent.psi_cognition_classic`` for fallback.

    Parameters
    ----------
    agent : object
        The agent instance.  Must have a ``psi_cognition`` attribute (or
        one will be created).
    mode : str
        Quantum mode: 'pure_quantum', 'hybrid', or 'classic'.
    dim_state : int
        Hilbert space dimension for the consciousness state.
    **kwargs
        Additional ``QuantumCognitionConfig`` parameters.

    Returns
    -------
    PsiQuantumCognition
        The created quantum cognition engine.

    Example
    -------
    >>> from laap.agent_core.quantum_cognition.bridge import enable_quantum_cognition
    >>> qe = enable_quantum_cognition(my_agent, mode='hybrid', dim_state=10)
    >>> my_agent.psi_cognition = qe  # transparent replacement
    """
    cfg = QuantumCognitionConfig(
        mode=mode,
        dim_state=dim_state,
        **kwargs,
    )

    # Preserve classic PSICognition as fallback
    if hasattr(agent, 'psi_cognition'):
        agent.psi_cognition_classic = getattr(agent, 'psi_cognition')

    quantum_engine = PsiQuantumCognition(cfg)
    agent.psi_cognition = quantum_engine

    logger.info(
        f"[bridge] Quantum cognition enabled: mode={mode}, "
        f"dim={dim_state}, agent={getattr(agent, 'name', 'unknown')}"
    )

    return quantum_engine


def get_quantum_stats(agent: object) -> dict:
    """Get quantum cognition statistics from an agent.

    Works whether the agent has quantum cognition enabled or not
    (falls back to classic stats).

    Parameters
    ----------
    agent : object
        Agent instance.

    Returns
    -------
    dict
        Cognitive statistics.
    """
    if hasattr(agent, 'psi_cognition') and isinstance(
        getattr(agent, 'psi_cognition'), PsiQuantumCognition
    ):
        return agent.psi_cognition.get_stats()

    if hasattr(agent, 'psi_cognition'):
        klass = getattr(agent, 'psi_cognition')
        if hasattr(klass, 'get_stats'):
            return klass.get_stats()

    return {'error': 'No cognition engine found'}
