"""LAAP Aether — Orchestration kernel bridging Petri nets and actors."""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from typing import Any, Dict, List, Optional

from laap.orchestration.actor import ActorSystem
from laap.orchestration.petri import ColoredToken, PetriNet, TokenColor
from laap.orchestration.primitives import AetherAddress, AetherMessage, MessageType

logger = logging.getLogger("laap.orchestration.kernel")


class OrchestrationKernel:
    """Bridge between a colored Petri net and an Actor runtime.

    The kernel registers a listener on the Petri net so that every time a
    transition fires, produced tokens are inspected. Tokens whose color is
    ``AGENT_REF`` are translated into ``INVOKE`` AetherMessages and routed to
    the referenced actor. It also maintains actor bindings per transition and
    checkpoint/restore semantics for the net marking.
    """

    def __init__(
        self,
        actor_system: ActorSystem,
        petri_net: PetriNet,
        kernel_id: Optional[str] = None,
    ) -> None:
        self.kernel_id: str = kernel_id or f"kernel_{petri_net.net_id}"
        self.actor_system: ActorSystem = actor_system
        self.petri_net: PetriNet = petri_net
        self.actor_bindings: Dict[str, List[str]] = {}
        self.checkpoints: Dict[str, Dict[str, List[ColoredToken]]] = {}
        self.running: bool = False
        self.task: Optional[asyncio.Task[None]] = None

        self._fire_count: int = 0
        self._checkpoint_interval: int = 10
        self.petri_net.add_listener(self._on_petri_event)

    def bind_transition(self, transition_id: str, actor_id: str) -> None:
        """Bind an actor to a transition."""
        if transition_id not in self.petri_net.transitions:
            raise ValueError(f"Unknown transition: {transition_id}")
        if actor_id not in self.actor_system.actors:
            raise ValueError(f"Unknown actor: {actor_id}")
        bound = self.actor_bindings.setdefault(transition_id, [])
        if actor_id not in bound:
            bound.append(actor_id)

    def unbind_transition(self, transition_id: str, actor_id: str) -> None:
        """Remove an actor binding from a transition."""
        bound = self.actor_bindings.get(transition_id)
        if bound is None:
            return
        if actor_id in bound:
            bound.remove(actor_id)
        if not bound:
            del self.actor_bindings[transition_id]

    def deposit_token(self, place_id: str, token: ColoredToken) -> None:
        """Convenience wrapper to deposit a token into a place."""
        place = self.petri_net.places.get(place_id)
        if place is None:
            raise ValueError(f"Unknown place: {place_id}")
        place.deposit(token)

    def route_tokens(
        self,
        produced_tokens: Optional[Dict[str, List[ColoredToken]]] = None,
    ) -> None:
        """Route every ``AGENT_REF`` token as an ``INVOKE`` AetherMessage.

        When called without arguments, every ``AGENT_REF`` token currently in
        the net is routed. When a produced-token mapping is supplied (as from
        ``_on_transition_fired``), only those tokens are inspected.
        """
        if produced_tokens is None:
            produced_tokens = {
                place_id: list(place.tokens)
                for place_id, place in self.petri_net.places.items()
            }

        for tokens in produced_tokens.values():
            for token in tokens:
                if token.color == TokenColor.AGENT_REF:
                    self._route_agent_ref(token)

    def _route_agent_ref(self, token: ColoredToken) -> None:
        """Resolve an AGENT_REF token to an actor address and send INVOKE."""
        recipient = self._resolve_recipient(token.value)
        if recipient is None:
            logger.warning("Cannot route AGENT_REF token with value %r", token.value)
            return

        if recipient.actor_id not in self.actor_system.actors:
            logger.warning("Unknown recipient actor: %s", recipient.actor_id)
            return

        message = AetherMessage(
            msg_type=MessageType.INVOKE,
            sender=AetherAddress(host="local", actor_id=self.kernel_id),
            recipient=recipient,
            payload={
                "token": token.value,
                "color": token.color.name,
            },
        )

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            logger.warning("No running event loop; cannot route token")
            return

        asyncio.create_task(self.actor_system.send(message))

    @staticmethod
    def _resolve_recipient(value: Any) -> Optional[AetherAddress]:
        """Best-effort resolution of a token value into an actor address."""
        if isinstance(value, AetherAddress):
            return value
        if isinstance(value, dict):
            actor_id = value.get("actor_id") or value.get("id")
            host = value.get("host", "local")
            if actor_id is not None:
                return AetherAddress(host=str(host), actor_id=str(actor_id))
            return None
        if isinstance(value, str):
            return AetherAddress(host="local", actor_id=value)
        return None

    def _on_petri_event(self, event: str, payload: Dict[str, Any]) -> None:
        """Petri net event listener that drives routing and checkpoints."""
        if event != "transition_fired":
            return
        entry = payload.get("entry", {})
        self._on_transition_fired(
            entry.get("transition_id", ""),
            entry.get("consumed", {}),
            entry.get("produced", {}),
        )

    def _on_transition_fired(
        self,
        transition_id: str,
        consumed_tokens: Dict[str, List[ColoredToken]],
        produced_tokens: Dict[str, List[ColoredToken]],
    ) -> None:
        """Callback after a transition fires.

        Routes any ``AGENT_REF`` output tokens and stores a checkpoint every
        ``_checkpoint_interval`` firings.
        """
        self.route_tokens(produced_tokens)
        self._fire_count += 1
        if self._fire_count % self._checkpoint_interval == 0:
            checkpoint_id = f"{self.kernel_id}_fire_{self._fire_count}"
            self.checkpoints[checkpoint_id] = self.checkpoint()

    async def run(self) -> None:
        """Run the kernel loop until no transitions are enabled or stopped."""
        self.running = True
        self.task = asyncio.current_task()
        try:
            while self.running:
                stepped = await self.petri_net.step()
                if not stepped:
                    break
        finally:
            self.running = False
            self.task = None

    def stop(self) -> None:
        """Signal the kernel loop to stop."""
        self.running = False
        if self.task is not None and not self.task.done():
            self.task.cancel()

    def checkpoint(self) -> Dict[str, List[ColoredToken]]:
        """Return a snapshot of the current marking."""
        return {
            place_id: list(place.tokens)
            for place_id, place in self.petri_net.places.items()
        }

    def restore(self, checkpoint_id: str) -> None:
        """Restore the net marking from a previously saved checkpoint."""
        marking = self.checkpoints.get(checkpoint_id)
        if marking is None:
            raise ValueError(f"Unknown checkpoint: {checkpoint_id}")
        for place_id, place in self.petri_net.places.items():
            tokens = marking.get(place_id, [])
            place.tokens = deque(tokens, maxlen=place.tokens.maxlen)
