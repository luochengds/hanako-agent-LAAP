"""Colored Petri net engine for LAAP Aether orchestration."""

from __future__ import annotations

import asyncio
import inspect
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set, Union


class TokenColor(Enum):
    """Color taxonomy for tokens flowing through the net."""

    DATA = auto()
    CONTROL = auto()
    AGENT_REF = auto()
    CAPABILITY = auto()
    META = auto()
    PSI_STATE = auto()
    MEMORY = auto()
    RULE_MATCH = auto()
    RESPONSE = auto()


@dataclass(frozen=True)
class ColoredToken:
    """A token carrying a color, payload, timestamp, and provenance trail."""

    color: TokenColor
    value: Any
    timestamp: float = field(default_factory=time.monotonic)
    provenance: tuple[str, ...] = field(default_factory=tuple)

    def with_provenance(self, place_id: str) -> ColoredToken:
        """Return a new token with *place_id* appended to its provenance."""
        return ColoredToken(
            color=self.color,
            value=self.value,
            timestamp=self.timestamp,
            provenance=self.provenance + (place_id,),
        )


@dataclass
class PetriPlace:
    """A place (node) that holds a bounded deque of colored tokens."""

    place_id: str
    capacity: int = -1
    tokens: deque[ColoredToken] = field(
        default_factory=lambda: deque(maxlen=10000)
    )
    token_types: Optional[Set[TokenColor]] = None

    def __len__(self) -> int:
        return len(self.tokens)

    def can_accept(self, token: ColoredToken) -> bool:
        """Check capacity and allowed color constraints."""
        if self.token_types is not None and token.color not in self.token_types:
            return False
        if self.capacity >= 0 and len(self.tokens) >= self.capacity:
            return False
        return True

    def deposit(self, token: ColoredToken) -> None:
        """Deposit a token, recording this place in its provenance."""
        stamped = token.with_provenance(self.place_id)
        self.tokens.append(stamped)

    def withdraw(self, color: Optional[TokenColor] = None) -> Optional[ColoredToken]:
        """Remove and return one token; optionally filter by color."""
        if color is None:
            return self.tokens.popleft() if self.tokens else None

        for idx, token in enumerate(self.tokens):
            if token.color == color:
                del self.tokens[idx]
                return token
        return None

    def has_at_least(self, count: int, color: Optional[TokenColor] = None) -> bool:
        """Return True if the place holds at least *count* matching tokens."""
        if color is None:
            return len(self.tokens) >= count
        return sum(1 for t in self.tokens if t.color == color) >= count


# Type aliases for transition behavior.
GuardCallable = Callable[["PetriNet", "PetriTransition"], bool]
OutputTransform = Callable[[List[ColoredToken]], List[ColoredToken]]
ActionResult = Union[List[ColoredToken], Awaitable[List[ColoredToken]], None]
ActionCallable = Callable[[Dict[str, Any]], ActionResult]
ListenerCallable = Callable[[str, Dict[str, Any]], None]


@dataclass
class PetriTransition:
    """A transition (node) that consumes, transforms, and produces tokens."""

    transition_id: str
    input_places: Dict[str, int]
    output_places: Dict[str, OutputTransform]
    guard: GuardCallable = field(default=lambda net, trans: True)
    action: Optional[ActionCallable] = None
    is_enabled: bool = True
    priority: int = 0

    def can_fire(self, net: PetriNet) -> bool:
        """Return True if the transition is enabled, guarded, and resourced."""
        if not self.is_enabled:
            return False
        for place_id, count in self.input_places.items():
            place = net.places.get(place_id)
            if place is None or not place.has_at_least(count):
                return False
        try:
            return self.guard(net, self)
        except Exception:
            return False


@dataclass
class PetriNet:
    """A colored Petri net with async firing semantics and rollback."""

    net_id: str
    places: Dict[str, PetriPlace] = field(default_factory=dict)
    transitions: Dict[str, PetriTransition] = field(default_factory=dict)
    edges: List[tuple[str, str]] = field(default_factory=list)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    execution_log: List[Dict[str, Any]] = field(default_factory=list)
    listeners: List[ListenerCallable] = field(default_factory=list)

    def add_place(self, place: PetriPlace) -> PetriPlace:
        """Register a place in the net."""
        self.places[place.place_id] = place
        return place

    def add_transition(self, transition: PetriTransition) -> PetriTransition:
        """Register a transition and record its incident edges."""
        self.transitions[transition.transition_id] = transition
        for place_id in transition.input_places:
            self.edges.append((place_id, transition.transition_id))
        for place_id in transition.output_places:
            self.edges.append((transition.transition_id, place_id))
        return transition

    def add_listener(self, listener: ListenerCallable) -> None:
        """Subscribe to net events ('transition_fired', 'transition_action_error', ...)."""
        self.listeners.append(listener)

    def _notify(self, event: str, payload: Dict[str, Any]) -> None:
        for listener in self.listeners:
            try:
                listener(event, payload)
            except Exception:
                pass

    async def fire_transition(self, transition_id: str) -> bool:
        """Fire a transition, rolling back consumed tokens on action failure."""
        transition = self.transitions.get(transition_id)
        if transition is None:
            raise ValueError(f"Unknown transition: {transition_id}")

        if not transition.can_fire(self):
            return False

        async with self.lock:
            # Re-check after acquiring the lock in concurrent settings.
            if not transition.can_fire(self):
                return False

            consumed: Dict[str, Any] = {}
            for place_id, count in transition.input_places.items():
                place = self.places[place_id]
                withdrawn: List[ColoredToken] = []
                for _ in range(count):
                    token = place.withdraw()
                    if token is None:
                        # Partial withdrawal: rollback and abort.
                        for rollback_place_id, tokens in consumed.items():
                            rollback_place = self.places[rollback_place_id]
                            for tok in tokens:
                                rollback_place.deposit(tok)
                        for tok in withdrawn:
                            place.deposit(tok)
                        return False
                    withdrawn.append(token)
                consumed[place_id] = withdrawn

            try:
                result: Any = None
                if transition.action is not None:
                    result = transition.action(consumed)
                    if inspect.iscoroutine(result):
                        result = await result

                if result is not None and "_result" not in consumed:
                    consumed["_result"] = result
            except Exception as exc:
                # Rollback consumed input tokens on action failure.
                for place_id, tokens in consumed.items():
                    if place_id == "_result":
                        continue
                    place = self.places[place_id]
                    for token in tokens:
                        place.deposit(token)
                self._notify(
                    "transition_action_error",
                    {"net_id": self.net_id, "transition_id": transition_id, "error": str(exc)},
                )
                return False

            base_tokens: List[ColoredToken] = consumed.get(
                "_result",
                [token for place_id, tokens in consumed.items() if place_id != "_result" for token in tokens],
            )

            produced: Dict[str, List[ColoredToken]] = {}
            try:
                for place_id, transform in transition.output_places.items():
                    output_tokens = transform(base_tokens)
                    place = self.places[place_id]
                    for token in output_tokens:
                        place.deposit(token)
                    produced[place_id] = list(output_tokens)
            except Exception as exc:
                # Output failure: rollback consumed input tokens. Already-produced
                # outputs remain deposited; this keeps the engine consistent without
                # fragile token identity reversal.
                for place_id, tokens in consumed.items():
                    if place_id == "_result":
                        continue
                    place = self.places[place_id]
                    for token in tokens:
                        place.deposit(token)
                self._notify(
                    "transition_output_error",
                    {"net_id": self.net_id, "transition_id": transition_id, "error": str(exc)},
                )
                return False

            entry = {
                "transition_id": transition_id,
                "consumed": {k: v for k, v in consumed.items() if k != "_result"},
                "produced": produced,
            }
            self.execution_log.append(entry)
            self._notify("transition_fired", {"net_id": self.net_id, "entry": entry})
            return True

    async def get_enabled_transitions(self) -> List[PetriTransition]:
        """Return all transitions that can currently fire."""
        return [transition for transition in self.transitions.values() if transition.can_fire(self)]

    async def step(self) -> bool:
        """Fire the highest-priority enabled transition, if any."""
        enabled = await self.get_enabled_transitions()
        if not enabled:
            return False
        highest = max(enabled, key=lambda t: t.priority)
        return await self.fire_transition(highest.transition_id)
