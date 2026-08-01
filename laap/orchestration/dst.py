"""LAAP Aether — Deterministic Simulation Testing (DST) engine.

The DST engine wraps an :class:`ActorSystem` and deterministically injects
faults (message drops, actor crashes, network delays and clock skew) so that
distributed orchestration scenarios can be replayed and invariant-checked.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any, Callable, Dict, List, Optional

from laap.orchestration.actor import ActorState, ActorSystem
from laap.orchestration.primitives import AetherAddress, AetherMessage, MessageType

logger = logging.getLogger("laap.orchestration.dst")


class FaultType(Enum):
    """Supported fault injection types."""

    MESSAGE_DROP = auto()
    ACTOR_CRASH = auto()
    NETWORK_DELAY = auto()
    CLOCK_SKEW = auto()


@dataclass
class FaultInjection:
    """A single deterministic fault-injection rule.

    A rule matches a send attempt when ``target_actor_id`` is either ``None``
    (any actor) or equal to the recipient's actor id.  Matching rules fire
    according to ``probability`` using the harness's deterministic RNG.

    ``delay_ms`` is only meaningful for :attr:`FaultType.NETWORK_DELAY`.
    """

    fault_type: FaultType
    probability: float = 1.0
    target_actor_id: Optional[str] = None
    delay_ms: int = 0


class DSTHarness:
    """Deterministic simulation testing wrapper for an :class:`ActorSystem`.

    The harness can be used directly in place of ``ActorSystem.send`` or
    installed at runtime so that every routed message is evaluated against a
    list of :class:`FaultInjection` rules.  All send attempts, faults and
    delivery outcomes are recorded in ``event_log``.
    """

    def __init__(
        self,
        actor_system: ActorSystem,
        rules: Optional[List[FaultInjection]] = None,
        seed: int = 0,
        invariants: Optional[List[Callable[[ActorSystem], bool]]] = None,
        auto_install: bool = False,
    ) -> None:
        self.actor_system: ActorSystem = actor_system
        self.rules: List[FaultInjection] = list(rules or [])
        self.seed: int = seed
        self.invariants: List[Callable[[ActorSystem], bool]] = list(invariants or [])
        self.event_log: List[Dict[str, Any]] = []

        self._rng: random.Random = random.Random(seed)
        self._original_send = actor_system.send
        self._installed: bool = False

        if auto_install:
            self.install()

    # ------------------------------------------------------------------ #
    # Installation / drop-in replacement API
    # ------------------------------------------------------------------ #
    def install(self) -> None:
        """Patch ``actor_system.send`` so calls go through :meth:`send`."""
        if not self._installed:
            self._original_send = self.actor_system.send
            self.actor_system.send = self.send  # type: ignore[assignment]
            self._installed = True

    def uninstall(self) -> None:
        """Restore the original ``actor_system.send`` method."""
        if self._installed:
            self.actor_system.send = self._original_send
            self._installed = False

    # ------------------------------------------------------------------ #
    # Public runtime API
    # ------------------------------------------------------------------ #
    async def send(self, message: AetherMessage) -> bool:
        """Intercept a send attempt, apply faults, log and return delivery status.

        Returns ``True`` if the message was delivered to the recipient actor,
        ``False`` if it was dropped or caused a crash.
        """
        now = time.monotonic()
        recipient = message.recipient

        if recipient is None:
            self._log_event(
                timestamp=now,
                message_id=message.msg_id,
                fault=None,
                delivered=False,
                recipient=None,
            )
            logger.warning("DST harness: cannot send message with no recipient")
            return False

        actor = self.actor_system.actors.get(recipient.actor_id)
        if actor is None:
            self._log_event(
                timestamp=now,
                message_id=message.msg_id,
                fault=None,
                delivered=False,
                recipient=recipient.actor_id,
            )
            logger.warning(
                "DST harness: unknown recipient actor %s", recipient.actor_id
            )
            return False

        self.actor_system._ensure_running(actor)
        rule = self._select_rule(actor.actor_id)
        fault_name = rule.fault_type.name if rule else None

        if rule is None:
            await self._original_send(message)
            self._log_event(
                timestamp=now,
                message_id=message.msg_id,
                fault=None,
                delivered=True,
                recipient=actor.actor_id,
            )
            return True

        fault_type = rule.fault_type

        if fault_type is FaultType.MESSAGE_DROP:
            self._log_event(
                timestamp=now,
                message_id=message.msg_id,
                fault=fault_type.name,
                delivered=False,
                recipient=actor.actor_id,
            )
            return False

        if fault_type is FaultType.NETWORK_DELAY:
            delay_s = rule.delay_ms / 1000.0
            start = time.monotonic()
            await asyncio.sleep(delay_s)
            await self._original_send(message)
            latency_ms = (time.monotonic() - start) * 1000.0
            self._log_event(
                timestamp=now,
                message_id=message.msg_id,
                fault=fault_type.name,
                delivered=True,
                recipient=actor.actor_id,
                latency_ms=round(latency_ms, 3),
            )
            return True

        if fault_type is FaultType.CLOCK_SKEW:
            offset_ms = self._rng.randint(-1000, 1000)
            message.timestamp += offset_ms / 1000.0
            await self._original_send(message)
            self._log_event(
                timestamp=now,
                message_id=message.msg_id,
                fault=fault_type.name,
                delivered=True,
                recipient=actor.actor_id,
                clock_offset_ms=offset_ms,
            )
            return True

        if fault_type is FaultType.ACTOR_CRASH:
            async with actor.state_lock:
                actor.state = ActorState.RECOVERING
            self._log_event(
                timestamp=now,
                message_id=message.msg_id,
                fault=fault_type.name,
                delivered=False,
                recipient=actor.actor_id,
            )
            if actor.supervisor is not None:
                escalation = AetherMessage(
                    msg_type=MessageType.EMIT,
                    sender=actor.address,
                    recipient=actor.supervisor,
                    payload={
                        "event": "actor_crash",
                        "reason": "dst_injected",
                        "original": {
                            "msg_id": message.msg_id,
                            "msg_type": message.msg_type.value,
                            "payload": message.payload,
                        },
                    },
                )
                # Use the original send path so the escalation is not itself
                # subjected to fault injection.
                await self._original_send(escalation)
            return False

        # Defensive fallback: unknown fault type delivers normally.
        await self._original_send(message)
        self._log_event(
            timestamp=now,
            message_id=message.msg_id,
            fault=fault_name,
            delivered=True,
            recipient=actor.actor_id,
        )
        return True

    def assert_invariants(self) -> None:
        """Run all registered invariants and raise if any fail."""
        for predicate in self.invariants:
            if not predicate(self.actor_system):
                raise AssertionError(f"DST invariant violated: {predicate!r}")

    def report(self) -> Dict[str, Any]:
        """Return a summary of the simulation run."""
        delivered = sum(1 for e in self.event_log if e.get("delivered"))
        dropped = len(self.event_log) - delivered
        faults: Dict[str, int] = {}
        for entry in self.event_log:
            fault = entry.get("fault")
            if fault:
                faults[fault] = faults.get(fault, 0) + 1

        return {
            "seed": self.seed,
            "total_send_attempts": len(self.event_log),
            "delivered": delivered,
            "dropped": dropped,
            "faults_injected": faults,
            "rule_count": len(self.rules),
            "invariant_count": len(self.invariants),
        }

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    def _select_rule(self, actor_id: str) -> Optional[FaultInjection]:
        """Return the first matching fault rule that fires for *actor_id*."""
        for rule in self.rules:
            if rule.target_actor_id is not None and rule.target_actor_id != actor_id:
                continue
            if self._rng.random() < rule.probability:
                return rule
        return None

    def _log_event(
        self,
        timestamp: float,
        message_id: str,
        fault: Optional[str],
        delivered: bool,
        recipient: Optional[str],
        latency_ms: Optional[float] = None,
        clock_offset_ms: Optional[int] = None,
    ) -> None:
        entry: Dict[str, Any] = {
            "timestamp": timestamp,
            "message_id": message_id,
            "fault": fault,
            "delivered": delivered,
            "recipient": recipient,
        }
        if latency_ms is not None:
            entry["latency_ms"] = latency_ms
        if clock_offset_ms is not None:
            entry["clock_offset_ms"] = clock_offset_ms
        self.event_log.append(entry)
