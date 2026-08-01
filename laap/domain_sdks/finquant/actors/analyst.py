"""LAAP FinQuant Domain SDK — Analyst cognitive actor.

Dispatches quantitative analysis requests (indicators, factors,
statistics) to the appropriate zero-token harness function and emits
the computed result.

Subscribes: ``finquant.analysis.request``
Publishes:  ``finquant.analysis.result``
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from laap.orchestration.actor import AgentCell, ActorSystem, Capability
from laap.orchestration.primitives import AetherMessage, MessageType
from laap.domain_sdks.finquant.topics import ANALYSIS_REQUEST, ANALYSIS_RESULT

logger = logging.getLogger("laap.domain_sdks.finquant.actors.analyst")


class AnalystActor:
    """Cognitive actor that services quantitative analysis requests."""

    ACTOR_ID = "finquant_analysis_analyst"
    CAPABILITIES: List[Capability] = [
        Capability(
            name="finquant.analysis.quant",
            confidence=0.95,
            cost_estimate=0.0,
            schema={"request": "dict"},
        )
    ]

    def __init__(
        self,
        harness_registry: Any = None,
        cognitive_bus: Any = None,
    ) -> None:
        self.harness_registry = harness_registry
        self.cognitive_bus = cognitive_bus

    # ── Message handlers ───────────────────────────────────────────

    async def on_analysis_request(
        self, message: AetherMessage, actor: AgentCell
    ) -> None:
        """Dispatch an analysis request to the matching harness function."""
        try:
            payload = getattr(message, "payload", None) or {}
            request = payload.get("request", payload)
            req_type = str(request.get("type", "")).lower()
            data = request.get("data", [])

            result: Dict[str, Any] = {"request_type": req_type}

            if self.harness_registry is None:
                result["error"] = "harness_registry_not_configured"
            elif req_type == "indicators":
                indicators = request.get("indicators", [{"name": "sma", "period": 20}])
                result["result"] = await self.harness_registry.invoke(
                    "finquant.indicators.compute",
                    data=data,
                    indicators=indicators,
                )
            elif req_type == "factors":
                asset_returns = request.get("asset_returns", [])
                factor_data = request.get("factor_data", {})
                result["result"] = await self.harness_registry.invoke(
                    "finquant.factors.fama_french",
                    asset_returns=asset_returns,
                    factor_data=factor_data,
                )
            elif req_type == "statistics":
                values = request.get("values", [])
                result["result"] = await self.harness_registry.invoke(
                    "finquant.statistics.zscore_test", values=values
                )
            else:
                result["error"] = f"unknown_analysis_type:{req_type}"

            await self._emit(actor, ANALYSIS_RESULT, result)
        except Exception as exc:
            # Never raise from a handler — log and skip.
            logger.warning(
                "[%s] on_analysis_request failed: %s: %s",
                self.ACTOR_ID,
                type(exc).__name__,
                exc,
            )
            try:
                await self._emit(
                    actor,
                    ANALYSIS_RESULT,
                    {"error": str(exc), "actor": self.ACTOR_ID},
                )
            except Exception:
                pass

    # ── Lifecycle ──────────────────────────────────────────────────

    async def start(self, actor_system: ActorSystem) -> Optional[AgentCell]:
        """Spawn this actor in *actor_system*. Defensive: returns None on failure."""
        try:
            actor = actor_system.spawn(
                actor_id=self.ACTOR_ID,
                capabilities=self.CAPABILITIES,
            )
            actor.on(MessageType.INVOKE, self._bind(self.on_analysis_request))
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
            "subscribes": [ANALYSIS_REQUEST],
            "publishes": [ANALYSIS_RESULT],
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


__all__ = ["AnalystActor"]
