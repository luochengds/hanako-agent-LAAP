"""LAAP FinQuant Domain SDK — MarketWatcher cognitive actor.

Perceives real-time market data ticks, computes technical indicators
via the zero-token harness, and emits anomaly alerts when price action
deviates significantly from the rolling mean.

Subscribes: ``finquant.market.stream``
Publishes:  ``finquant.market.stream``, ``finquant.market.anomaly``
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from laap.orchestration.actor import AgentCell, ActorSystem, Capability
from laap.orchestration.primitives import AetherMessage, MessageType
from laap.domain_sdks.finquant.topics import MARKET_ANOMALY, MARKET_STREAM

logger = logging.getLogger("laap.domain_sdks.finquant.actors.market_watcher")


class MarketWatcherActor:
    """Cognitive actor that watches the market stream and flags anomalies."""

    ACTOR_ID = "finquant_market_watcher"
    CAPABILITIES: List[Capability] = [
        Capability(
            name="finquant.market.watcher",
            confidence=0.98,
            cost_estimate=0.0,
            schema={"symbols": "list[str]", "timeframe": "str"},
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

    async def on_stream_tick(self, message: AetherMessage, actor: AgentCell) -> None:
        """Process an incoming market tick message.

        Computes indicators and an anomaly z-score via the harness, then
        always re-emits the stream tick and conditionally emits an anomaly
        alert when the z-score is significant.
        """
        try:
            payload = getattr(message, "payload", None) or {}
            tick = payload.get("tick", payload)
            bars = payload.get("data") or [tick]
            symbol = (
                tick.get("symbol", "") if isinstance(tick, dict) else ""
            )

            indicators_result: Dict[str, Any] = {}
            if self.harness_registry is not None and bars:
                try:
                    indicators_result = await self.harness_registry.invoke(
                        "finquant.indicators.compute",
                        data=bars,
                        indicators=[{"name": "sma", "period": 20}],
                    )
                except Exception as exc:
                    logger.warning(
                        "[%s] indicator compute failed: %s", self.ACTOR_ID, exc
                    )

            anomaly: Dict[str, Any] = {}
            if self.harness_registry is not None and bars:
                try:
                    closes = [
                        float(b.get("close", 0.0))
                        if isinstance(b, dict)
                        else float(getattr(b, "close", 0.0))
                        for b in bars
                    ]
                    anomaly = await self.harness_registry.invoke(
                        "finquant.statistics.zscore_test", values=closes
                    )
                except Exception as exc:
                    logger.warning(
                        "[%s] zscore test failed: %s", self.ACTOR_ID, exc
                    )

            # Always re-emit the stream tick (with enriched indicators)
            await self._emit(
                actor,
                MARKET_STREAM,
                {
                    "symbol": symbol,
                    "tick": tick,
                    "indicators": indicators_result.get("indicators", {}),
                },
            )

            # Emit anomaly alert if z-score is significant
            if anomaly and abs(float(anomaly.get("zscore", 0.0))) >= 2.0:
                await self._emit(
                    actor,
                    MARKET_ANOMALY,
                    {
                        "symbol": symbol,
                        "zscore": anomaly.get("zscore", 0.0),
                        "significant": anomaly.get("significant", True),
                        "tick": tick,
                    },
                )
        except Exception as exc:
            # Never raise from a handler — log and skip.
            logger.warning(
                "[%s] on_stream_tick failed: %s: %s",
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
            actor.on(MessageType.INVOKE, self._bind(self.on_stream_tick))
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
            "subscribes": [MARKET_STREAM],
            "publishes": [MARKET_STREAM, MARKET_ANOMALY],
        }

    # ── Internals ──────────────────────────────────────────────────

    def _bind(self, handler):
        """Adapt a (message, actor) handler to the AgentCell (message) signature."""

        async def _wrapped(message: AetherMessage) -> None:
            await handler(message, _wrapped_actor_ref)

        # The actor reference is set by start() via the bound closure;
        # fall back to None if unavailable (handlers tolerate this).
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


__all__ = ["MarketWatcherActor"]
