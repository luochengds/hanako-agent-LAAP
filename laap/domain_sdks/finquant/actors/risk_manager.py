"""LAAP FinQuant Domain SDK — RiskManager cognitive actor.

Continuously assesses portfolio risk by computing VaR/CVaR via the
zero-token harness and comparing the result against configured policy
limits. Emits a breach alert when risk exceeds the allowed threshold.

Subscribes: ``finquant.risk.assessment``
Publishes:  ``finquant.risk.breach``
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from laap.orchestration.actor import AgentCell, ActorSystem, Capability
from laap.orchestration.primitives import AetherMessage, MessageType
from laap.domain_sdks.finquant.topics import RISK_ASSESSMENT, RISK_BREACH

logger = logging.getLogger("laap.domain_sdks.finquant.actors.risk_manager")


class RiskManagerActor:
    """Cognitive actor that monitors portfolio risk and flags breaches."""

    ACTOR_ID = "finquant_risk_manager"
    CAPABILITIES: List[Capability] = [
        Capability(
            name="finquant.risk.assess",
            confidence=0.99,
            cost_estimate=0.0,
            schema={"portfolio": "dict"},
        )
    ]

    # Default breach thresholds (decimal fractions of portfolio value).
    DEFAULT_VAR_LIMIT_PCT: float = 0.05  # 5% one-day VaR limit
    DEFAULT_CVAR_LIMIT_PCT: float = 0.08  # 8% one-day CVaR limit

    def __init__(
        self,
        harness_registry: Any = None,
        cognitive_bus: Any = None,
        var_limit_pct: float = DEFAULT_VAR_LIMIT_PCT,
        cvar_limit_pct: float = DEFAULT_CVAR_LIMIT_PCT,
    ) -> None:
        self.harness_registry = harness_registry
        self.cognitive_bus = cognitive_bus
        self.var_limit_pct = var_limit_pct
        self.cvar_limit_pct = cvar_limit_pct

    # ── Message handlers ───────────────────────────────────────────

    async def on_risk_assessment(
        self, message: AetherMessage, actor: AgentCell
    ) -> None:
        """Compute VaR/CVaR and emit a breach alert if limits are exceeded."""
        try:
            payload = getattr(message, "payload", None) or {}
            portfolio = payload.get("portfolio", payload)
            returns = portfolio.get("returns", []) if isinstance(portfolio, dict) else []
            total_value = (
                float(portfolio.get("total_value", 0.0))
                if isinstance(portfolio, dict)
                else 0.0
            )
            confidence = (
                float(portfolio.get("confidence", 0.95))
                if isinstance(portfolio, dict)
                else 0.95
            )

            if self.harness_registry is None:
                logger.warning("[%s] harness_registry not configured", self.ACTOR_ID)
                return

            var_result = await self.harness_registry.invoke(
                "finquant.risk.var",
                returns=returns,
                confidence=confidence,
                method="historical",
            )

            var = float(var_result.get("var", 0.0))
            cvar = float(var_result.get("cvar", 0.0))

            # Express as fraction of portfolio value for limit comparison.
            var_pct = abs(var) / total_value if total_value > 0 else 0.0
            cvar_pct = abs(cvar) / total_value if total_value > 0 else 0.0

            breached = []
            if var_pct > self.var_limit_pct:
                breached.append(
                    f"var_{var_pct:.2%}_exceeds_{self.var_limit_pct:.2%}"
                )
            if cvar_pct > self.cvar_limit_pct:
                breached.append(
                    f"cvar_{cvar_pct:.2%}_exceeds_{self.cvar_limit_pct:.2%}"
                )

            if breached:
                await self._emit(
                    actor,
                    RISK_BREACH,
                    {
                        "var": var,
                        "cvar": cvar,
                        "var_pct": var_pct,
                        "cvar_pct": cvar_pct,
                        "var_limit_pct": self.var_limit_pct,
                        "cvar_limit_pct": self.cvar_limit_pct,
                        "breaches": breached,
                        "confidence": confidence,
                    },
                )
        except Exception as exc:
            # Never raise from a handler — log and skip.
            logger.warning(
                "[%s] on_risk_assessment failed: %s: %s",
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
            actor.on(MessageType.INVOKE, self._bind(self.on_risk_assessment))
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
            "subscribes": [RISK_ASSESSMENT],
            "publishes": [RISK_BREACH],
            "limits": {
                "var_limit_pct": self.var_limit_pct,
                "cvar_limit_pct": self.cvar_limit_pct,
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


__all__ = ["RiskManagerActor"]
