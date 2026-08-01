"""LAAP FinQuant Domain SDK — Cognitive actors subpackage.

Aggregates the five FinQuant cognitive actors and provides a single
``spawn_all`` entry point that instantiates and spawns every actor
into a given :class:`laap.orchestration.actor.ActorSystem`.

Actors:

- :class:`MarketWatcherActor` — market stream perception & anomaly alerts
- :class:`AnalystActor`       — quantitative analysis dispatch
- :class:`RiskManagerActor`   — VaR/CVaR monitoring & breach alerts
- :class:`StrategistActor`    — strategy validation via backtest
- :class:`ExecutorActor`      — safety-gated order execution

Public API::

    from laap.domain_sdks.finquant.actors import ALL_ACTOR_CLASSES, spawn_all

    cells = await spawn_all(actor_system, harness_registry=reg,
                             safety_policy=policy, connector=conn)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Type

from laap.orchestration.actor import AgentCell, ActorSystem
from laap.domain_sdks.finquant.actors.analyst import AnalystActor
from laap.domain_sdks.finquant.actors.executor import ExecutorActor
from laap.domain_sdks.finquant.actors.market_watcher import MarketWatcherActor
from laap.domain_sdks.finquant.actors.risk_manager import RiskManagerActor
from laap.domain_sdks.finquant.actors.strategist import StrategistActor
from laap.domain_sdks.finquant.species import register_all
from laap.domain_sdk.species import SpeciesLibrary

logger = logging.getLogger("laap.domain_sdks.finquant.actors")


ALL_ACTOR_CLASSES: List[Type[Any]] = [
    MarketWatcherActor,
    AnalystActor,
    RiskManagerActor,
    StrategistActor,
    ExecutorActor,
]


async def spawn_all(
    actor_system: ActorSystem,
    harness_registry: Any = None,
    safety_policy: Any = None,
    connector: Any = None,
    cognitive_bus: Any = None,
) -> Dict[str, Optional[AgentCell]]:
    """Instantiate and spawn every FinQuant cognitive actor.

    Each actor is constructed with the appropriate dependencies and then
    spawned via its ``start()`` method. Failures are tolerated: if one
    actor fails to spawn, the error is logged and the remaining actors
    are still attempted.

    Args:
        actor_system: The ActorSystem to spawn into.
        harness_registry: Harness function registry (for MarketWatcher,
            Analyst, RiskManager, Strategist).
        safety_policy: FinQuantSafetyPolicy (for Executor).
        connector: Financial connector (for Executor).
        cognitive_bus: Optional cognitive bus for message publishing.

    Returns:
        Dict mapping actor_id → spawned AgentCell (or None on failure).
    """
    # Build a species library for the Strategist actor.
    species_library = SpeciesLibrary()
    try:
        register_all(species_library)
    except Exception as exc:
        logger.warning("Failed to register species library for Strategist: %s", exc)

    cells: Dict[str, Optional[AgentCell]] = {}

    # (constructor, kwargs) pairs in spawn order.
    specs: List[tuple] = [
        (
            MarketWatcherActor,
            {
                "harness_registry": harness_registry,
                "cognitive_bus": cognitive_bus,
            },
        ),
        (
            AnalystActor,
            {
                "harness_registry": harness_registry,
                "cognitive_bus": cognitive_bus,
            },
        ),
        (
            RiskManagerActor,
            {
                "harness_registry": harness_registry,
                "cognitive_bus": cognitive_bus,
            },
        ),
        (
            StrategistActor,
            {
                "harness_registry": harness_registry,
                "species_library": species_library,
                "cognitive_bus": cognitive_bus,
            },
        ),
        (
            ExecutorActor,
            {
                "safety_policy": safety_policy,
                "connector": connector,
                "cognitive_bus": cognitive_bus,
            },
        ),
    ]

    for cls, kwargs in specs:
        try:
            actor = cls(**kwargs)
            cell = await actor.start(actor_system)
            cells[actor.ACTOR_ID] = cell
            if cell is None:
                logger.warning("Actor %s did not spawn (returned None)", actor.ACTOR_ID)
        except Exception as exc:
            # Tolerant: log and continue with the next actor.
            actor_id = getattr(cls, "ACTOR_ID", cls.__name__)
            logger.warning(
                "Failed to spawn actor %s: %s: %s",
                actor_id,
                type(exc).__name__,
                exc,
            )
            cells[actor_id] = None

    spawned = sum(1 for c in cells.values() if c is not None)
    logger.info("Spawned %d/%d FinQuant actors", spawned, len(specs))
    return cells


__all__ = [
    "ALL_ACTOR_CLASSES",
    "spawn_all",
    # Actor classes
    "MarketWatcherActor",
    "AnalystActor",
    "RiskManagerActor",
    "StrategistActor",
    "ExecutorActor",
]
