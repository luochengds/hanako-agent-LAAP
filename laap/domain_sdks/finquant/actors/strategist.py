"""LAAP FinQuant Domain SDK — Strategist cognitive actor.

Instantiates strategies from the species library and validates them
by running a backtest via the zero-token harness. Emits a validated
event when backtest metrics clear the acceptance thresholds, or a
rejected event otherwise.

Subscribes: ``finquant.strategy.proposed``
Publishes:  ``finquant.strategy.validated``, ``finquant.strategy.rejected``
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from laap.orchestration.actor import AgentCell, ActorSystem, Capability
from laap.orchestration.primitives import AetherMessage, MessageType
from laap.domain_sdks.finquant.topics import (
    STRATEGY_PROPOSED,
    STRATEGY_REJECTED,
    STRATEGY_VALIDATED,
)

logger = logging.getLogger("laap.domain_sdks.finquant.actors.strategist")


class StrategistActor:
    """Cognitive actor that validates proposed strategies via backtest."""

    ACTOR_ID = "finquant_strategy_strategist"
    CAPABILITIES: List[Capability] = [
        Capability(
            name="finquant.strategy.generate",
            confidence=0.9,
            cost_estimate=0.0,
            schema={"intent": "dict"},
        )
    ]

    # Minimum acceptance thresholds for backtest metrics.
    DEFAULT_MIN_SHARPE: float = 0.5
    DEFAULT_MAX_DRAWDOWN: float = 0.25  # 25%

    def __init__(
        self,
        harness_registry: Any = None,
        species_library: Any = None,
        cognitive_bus: Any = None,
        min_sharpe: float = DEFAULT_MIN_SHARPE,
        max_drawdown: float = DEFAULT_MAX_DRAWDOWN,
    ) -> None:
        self.harness_registry = harness_registry
        self.species_library = species_library
        self.cognitive_bus = cognitive_bus
        self.min_sharpe = min_sharpe
        self.max_drawdown = max_drawdown

    # ── Message handlers ───────────────────────────────────────────

    async def on_strategy_proposed(
        self, message: AetherMessage, actor: AgentCell
    ) -> None:
        """Instantiate the proposed strategy and validate it via backtest."""
        try:
            payload = getattr(message, "payload", None) or {}
            proposal = payload.get("strategy", payload)
            template_id = proposal.get("template_id", "")
            params = proposal.get("parameters", {}) or {}
            data = proposal.get("data", [])

            if not template_id:
                await self._emit(
                    actor,
                    STRATEGY_REJECTED,
                    {"reason": "missing_template_id", "proposal": proposal},
                )
                return

            # Instantiate strategy from species library (if available).
            instance = None
            if self.species_library is not None:
                try:
                    instance = self.species_library.instantiate(
                        template_id, **params
                    )
                except Exception as exc:
                    await self._emit(
                        actor,
                        STRATEGY_REJECTED,
                        {
                            "reason": f"instantiate_failed:{exc}",
                            "template_id": template_id,
                        },
                    )
                    return

            # Run backtest via harness (if available).
            backtest: Dict[str, Any] = {}
            if self.harness_registry is not None and data:
                try:
                    backtest = await self.harness_registry.invoke(
                        "finquant.backtest.run", data=data, **params
                    )
                except Exception as exc:
                    logger.warning(
                        "[%s] backtest failed: %s", self.ACTOR_ID, exc
                    )
                    backtest = {"error": str(exc)}

            metrics = backtest.get("metrics", backtest) if isinstance(backtest, dict) else {}
            sharpe = float(metrics.get("sharpe", metrics.get("sharpe_ratio", 0.0)))
            drawdown = abs(float(metrics.get("max_drawdown", 0.0)))

            accepted = sharpe >= self.min_sharpe and drawdown <= self.max_drawdown

            result_payload: Dict[str, Any] = {
                "template_id": template_id,
                "parameters": params,
                "metrics": metrics,
                "instance_rendered": bool(instance is not None),
                "sharpe": sharpe,
                "max_drawdown": drawdown,
            }

            if accepted:
                await self._emit(actor, STRATEGY_VALIDATED, result_payload)
            else:
                result_payload["reason"] = (
                    f"sharpe_{sharpe:.2f}<{self.min_sharpe:.2f}"
                    if sharpe < self.min_sharpe
                    else f"drawdown_{drawdown:.2%}>{self.max_drawdown:.2%}"
                )
                await self._emit(actor, STRATEGY_REJECTED, result_payload)
        except Exception as exc:
            # Never raise from a handler — log and skip.
            logger.warning(
                "[%s] on_strategy_proposed failed: %s: %s",
                self.ACTOR_ID,
                type(exc).__name__,
                exc,
            )

    # ── Lifecycle ──────────────────────────────────────────────────

    async def start(self, actor_system: ActorSystem) -> Optional[AgentCell]:
        """Spawn this actor in *actor_system*. Defensive: returns None on failure."""
        try:
            actor = actor_system.spawn(
                actor_id=self.ACTOR_ID,
                capabilities=self.CAPABILITIES,
            )
            actor.on(MessageType.INVOKE, self._bind(self.on_strategy_proposed))
            logger.info("[%s] spawned", self.ACTOR_ID)
            return actor
        except Exception as exc:
            logger.warning(
                "[%s] failed to spawn: %s: %s",
                self.ACTOR_ID,
                type(exc).__name__,
                exc,
            )
            return None

    def describe(self) -> Dict[str, Any]:
        """Return a dict describing this actor (for CLI / docs)."""
        return {
            "actor_id": self.ACTOR_ID,
            "capabilities": [
                {
                    "name": c.name,
                    "confidence": c.confidence,
                    "cost_estimate": c.cost_estimate,
                    "schema": dict(c.schema),
                }
                for c in self.CAPABILITIES
            ],
            "subscribes": [STRATEGY_PROPOSED],
            "publishes": [STRATEGY_VALIDATED, STRATEGY_REJECTED],
            "thresholds": {
                "min_sharpe": self.min_sharpe,
                "max_drawdown": self.max_drawdown,
            },
        }

    # ── Internals ──────────────────────────────────────────────────

    def _bind(self, handler):
        """Adapt a (message, actor) handler to the AgentCell (message) signature."""

        async def _wrapped(message: AetherMessage) -> None:
            await handler(message, _wrapped_actor_ref)

        _wrapped_actor_ref: Optional[AgentCell] = None
        return _wrapped

    async def _emit(
        self,
        actor: AgentCell,
        topic: str,
        payload: Dict[str, Any],
    ) -> None:
        """Emit an AetherMessage on the given topic. Defensive — never raises."""
        try:
            msg = AetherMessage(
                msg_type=MessageType.EMIT,
                sender=actor.address if actor else None,
                payload={"topic": topic, **payload},
            )
            if self.cognitive_bus is not None:
                try:
                    publish = getattr(self.cognitive_bus, "publish", None)
                    if publish is not None:
                        await publish(topic, msg)
                        return
                except Exception as exc:
                    logger.warning(
                        "[%s] cognitive_bus publish failed: %s", self.ACTOR_ID, exc
                    )
            system = getattr(actor, "_system", None)
            if system is not None:
                await system.broadcast(msg)
        except Exception as exc:
            logger.warning(
                "[%s] emit on '%s' failed: %s: %s",
                self.ACTOR_ID,
                topic,
                type(exc).__name__,
                exc,
            )


__all__ = ["StrategistActor"]
