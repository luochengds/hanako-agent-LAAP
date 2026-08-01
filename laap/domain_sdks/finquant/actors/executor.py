"""LAAP FinQuant Domain SDK — Executor cognitive actor.

The Executor is the final hop before an order reaches an exchange. It
runs the hard safety-policy gate FIRST (which cannot be bypassed by the
LLM), then routes the surviving order to the configured connector. Fill
confirmations and rejections are both emitted as AetherMessages.

Subscribes: ``finquant.execution.order``
Publishes:  ``finquant.execution.fill``, ``finquant.execution.rejected``
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from laap.orchestration.actor import AgentCell, ActorSystem, Capability
from laap.orchestration.primitives import AetherMessage, MessageType
from laap.domain_sdk.safety_policy import SafetyBreachError
from laap.domain_sdks.finquant.connectors.base import Order
from laap.domain_sdks.finquant.topics import (
    EXECUTION_FILL,
    EXECUTION_ORDER,
    EXECUTION_REJECTED,
)

logger = logging.getLogger("laap.domain_sdks.finquant.actors.executor")


class ExecutorActor:
    """Cognitive actor that executes orders behind the hard safety gate."""

    ACTOR_ID = "finquant_execution_executor"
    CAPABILITIES: List[Capability] = [
        Capability(
            name="finquant.execution.trade",
            confidence=1.0,
            cost_estimate=0.0,
            schema={"order": "dict"},
        )
    ]

    def __init__(
        self,
        safety_policy: Any = None,
        connector: Any = None,
        cognitive_bus: Any = None,
    ) -> None:
        self.safety_policy = safety_policy
        self.connector = connector
        self.cognitive_bus = cognitive_bus

    # ── Message handlers ───────────────────────────────────────────

    async def on_order(self, message: AetherMessage, actor: AgentCell) -> None:
        """Enforce the safety gate, then route the order to the connector."""
        try:
            payload = getattr(message, "payload", None) or {}
            order_payload = payload.get("order", payload)
            portfolio = payload.get("portfolio", {})

            # ── 1. Hard safety gate FIRST (cannot be bypassed) ──
            if self.safety_policy is not None:
                try:
                    self.safety_policy.pre_execution_gate(order_payload, portfolio)
                except SafetyBreachError as breach:
                    # Safety breach — emit rejection and stop.
                    logger.warning(
                        "[%s] safety breach: %s", self.ACTOR_ID, breach.message
                    )
                    await self._emit(
                        actor,
                        EXECUTION_REJECTED,
                        {
                            "order": order_payload,
                            "reason": "safety_breach",
                            "violation": getattr(breach, "violation", ""),
                            "message": breach.message,
                            "details": getattr(breach, "details", {}),
                        },
                    )
                    return
                except Exception as exc:
                    # Unknown safety-policy error — reject defensively.
                    logger.warning(
                        "[%s] safety gate error: %s: %s",
                        self.ACTOR_ID,
                        type(exc).__name__,
                        exc,
                    )
                    await self._emit(
                        actor,
                        EXECUTION_REJECTED,
                        {
                            "order": order_payload,
                            "reason": f"safety_gate_error:{exc}",
                        },
                    )
                    return

            # ── 2. Route order to connector ──
            if self.connector is None:
                await self._emit(
                    actor,
                    EXECUTION_REJECTED,
                    {
                        "order": order_payload,
                        "reason": "no_connector_configured",
                    },
                )
                return

            order = self._coerce_order(order_payload)
            try:
                result = await self.connector.place_order(order)
            except Exception as exc:
                logger.warning(
                    "[%s] connector place_order failed: %s: %s",
                    self.ACTOR_ID,
                    type(exc).__name__,
                    exc,
                )
                await self._emit(
                    actor,
                    EXECUTION_REJECTED,
                    {
                        "order": order_payload,
                        "reason": f"connector_error:{exc}",
                    },
                )
                return

            # ── 3. Emit fill or rejection based on result ──
            status = ""
            try:
                status = result.status.value.lower() if hasattr(result.status, "value") else str(result.status).lower()
            except Exception:
                status = ""

            if status == "filled":
                await self._emit(
                    actor,
                    EXECUTION_FILL,
                    {
                        "order_id": getattr(result, "order_id", ""),
                        "filled_size": getattr(result, "filled_size", 0.0),
                        "avg_fill_price": getattr(result, "avg_fill_price", None),
                        "commission": getattr(result, "commission", 0.0),
                        "slippage_bps": getattr(result, "slippage_bps", 0.0),
                        "order": order_payload,
                    },
                )
            else:
                await self._emit(
                    actor,
                    EXECUTION_REJECTED,
                    {
                        "order": order_payload,
                        "reason": getattr(result, "reject_reason", status) or status,
                        "status": status,
                    },
                )
        except Exception as exc:
            # Never raise from a handler — log and skip.
            logger.warning(
                "[%s] on_order failed: %s: %s",
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
            actor.on(MessageType.INVOKE, self._bind(self.on_order))
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
            "subscribes": [EXECUTION_ORDER],
            "publishes": [EXECUTION_FILL, EXECUTION_REJECTED],
            "has_safety_policy": self.safety_policy is not None,
            "has_connector": self.connector is not None,
        }

    # ── Internals ──────────────────────────────────────────────────

    @staticmethod
    def _coerce_order(order_payload: Any) -> Order:
        """Adapt a dict order payload to a connector ``Order`` instance."""
        if isinstance(order_payload, Order):
            return order_payload
        if isinstance(order_payload, dict):
            from laap.domain_sdks.finquant.connectors.base import (
                OrderSide,
                OrderType,
            )

            side_raw = str(order_payload.get("side", "buy")).lower()
            side = OrderSide.BUY if side_raw == "buy" else OrderSide.SELL
            type_raw = str(order_payload.get("order_type", "market")).lower()
            try:
                order_type = OrderType(type_raw)
            except ValueError:
                order_type = OrderType.MARKET
            return Order(
                symbol=order_payload.get("symbol", ""),
                side=side,
                size=float(order_payload.get("size", 0.0)),
                order_type=order_type,
                limit_price=order_payload.get("limit_price"),
                stop_price=order_payload.get("stop_price"),
                time_in_force=order_payload.get("time_in_force", "day"),
                client_order_id=order_payload.get("client_order_id"),
                meta=order_payload.get("meta", {}),
            )
        # Duck-type: assume it already quacks like an Order.
        return order_payload

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


__all__ = ["ExecutorActor"]
