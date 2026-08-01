"""Formal verification outputs for LAAP Aether Petri nets."""

from __future__ import annotations

import re
from collections import deque
from typing import Dict, List, Optional, Tuple, Union

from laap.orchestration.petri import ColoredToken, PetriNet, PetriTransition, TokenColor


class PetriNetVerifier:
    """Static verifier producing boundedness/liveness checks and formal outputs.

    The algorithms are intentionally educational and correct for ordinary token
    counts.  Colored tokens are treated as opaque values: only the number of
    tokens per place is considered during analysis.
    """

    _OMEGA: int = -1

    @classmethod
    def _generic_tokens(cls, count: int) -> List[ColoredToken]:
        """Produce deterministic tokens for measuring transition effects."""
        return [ColoredToken(color=TokenColor.DATA, value=0) for _ in range(count)]

    @classmethod
    def _transition_effects(
        cls, net: PetriNet
    ) -> Dict[str, Tuple[Dict[str, int], Dict[str, int]]]:
        """Return {transition_id: (input_counts, output_counts)}.

        Output counts are obtained by running each output transform on a bundle
        of generic tokens.  This collapses color details and yields a purely
        numeric effect, which is sufficient for the coverability approximation.
        """
        effects: Dict[str, Tuple[Dict[str, int], Dict[str, int]]] = {}
        for transition in net.transitions.values():
            input_counts = dict(transition.input_places)
            generic = cls._generic_tokens(sum(input_counts.values()))
            output_counts: Dict[str, int] = {}
            for place_id, transform in transition.output_places.items():
                try:
                    output_counts[place_id] = len(transform(generic))
                except Exception:
                    output_counts[place_id] = 0
            effects[transition.transition_id] = (input_counts, output_counts)
        return effects

    @classmethod
    def _fire_transition(
        cls,
        marking: Tuple[int, ...],
        place_ids: Tuple[str, ...],
        effects: Tuple[Dict[str, int], Dict[str, int]],
    ) -> Optional[Tuple[int, ...]]:
        """Apply a transition to a marking; return None if not enabled."""
        input_counts, output_counts = effects
        current = dict(zip(place_ids, marking))

        for place_id, required in input_counts.items():
            available = current.get(place_id, 0)
            if available == cls._OMEGA:
                continue
            if available < required:
                return None

        child = dict(current)
        for place_id, required in input_counts.items():
            if child.get(place_id, 0) != cls._OMEGA:
                child[place_id] = child.get(place_id, 0) - required
        for place_id, produced in output_counts.items():
            if child.get(place_id, 0) != cls._OMEGA:
                child[place_id] = child.get(place_id, 0) + produced

        return tuple(child[pid] for pid in place_ids)

    @classmethod
    def _accelerate(
        cls,
        child: Tuple[int, ...],
        ancestors: List[Tuple[int, ...]],
    ) -> Tuple[int, ...]:
        """Karp-Miller acceleration: omega-ify places that strictly increase.

        If some ancestor is component-wise <= the child and strictly less in a
        given place, that place can be increased without bound, so it is marked
        with the sentinel omega value (-1).
        """
        child_list = list(child)
        changed = False
        for ancestor in ancestors:
            if all(a <= c or c == cls._OMEGA for a, c in zip(ancestor, child)):
                for idx, (a, c) in enumerate(zip(ancestor, child)):
                    if a < c and c != cls._OMEGA:
                        child_list[idx] = cls._OMEGA
                        changed = True
        if changed:
            # Re-check earlier ancestors after applying acceleration.
            return cls._accelerate(tuple(child_list), ancestors)
        return tuple(child_list)

    @classmethod
    def boundedness_check(
        cls, net: PetriNet, max_depth: int = 100
    ) -> Tuple[bool, Optional[int]]:
        """Run a Karp-Miller style coverability tree and report the global bound.

        Returns ``(is_bounded, max_bound)``.  ``max_bound`` is the maximum finite
        token count observed across all places; it is ``None`` when the net is
        unbounded (an omega place is reachable).
        """
        place_ids = tuple(sorted(net.places.keys()))
        effects = cls._transition_effects(net)
        initial = tuple(len(net.places[pid]) for pid in place_ids)

        visited: set[Tuple[int, ...]] = {initial}
        queue: deque[Tuple[Tuple[int, ...], List[Tuple[int, ...]]]] = deque(
            [(initial, [])]
        )
        max_finite = 0
        has_omega = False
        depth_reached = 0

        while queue and depth_reached < max_depth:
            current, ancestors = queue.popleft()
            current_ancestors = ancestors + [current]
            depth_reached = max(depth_reached, len(current_ancestors))

            for value in current:
                if value == cls._OMEGA:
                    has_omega = True
                else:
                    max_finite = max(max_finite, value)

            for transition_id, trans_effects in effects.items():
                raw_child = cls._fire_transition(
                    current, place_ids, trans_effects
                )
                if raw_child is None:
                    continue
                child = cls._accelerate(raw_child, current_ancestors)
                if child not in visited:
                    visited.add(child)
                    queue.append((child, list(current_ancestors)))

        if has_omega:
            return (False, None)
        return (True, max_finite)

    @classmethod
    def liveness_check(
        cls, net: PetriNet, max_depth: int = 100
    ) -> Dict[str, List[object]]:
        """Detect sink places and reachable deadlocked markings.

        A *sink place* has no outgoing transitions.  A *deadlock* is a reachable
        marking where no transition is enabled and at least one non-sink place
        still holds a token (the net is stuck before termination).

        Returns ``{"deadlocks": [...], "sink_places": [...]}``.
        """
        place_ids = sorted(net.places.keys())
        effects = cls._transition_effects(net)

        # Structural information: places with no incoming/outgoing arcs.
        incoming: Dict[str, bool] = {pid: False for pid in place_ids}
        outgoing: Dict[str, bool] = {pid: False for pid in place_ids}
        for transition in net.transitions.values():
            for place_id in transition.output_places:
                if place_id in incoming:
                    incoming[place_id] = True
            for place_id in transition.input_places:
                if place_id in outgoing:
                    outgoing[place_id] = True

        sink_places = [pid for pid in place_ids if not outgoing[pid]]

        dead_transitions: List[str] = []
        for transition in net.transitions.values():
            tid = transition.transition_id
            for place_id, required in transition.input_places.items():
                place = net.places.get(place_id)
                if place is None:
                    dead_transitions.append(tid)
                    break
                if required > 0 and len(place) == 0 and not incoming[place_id]:
                    dead_transitions.append(tid)
                    break

        # Search for reachable deadlocks from the current marking.
        initial = tuple(len(net.places[pid]) for pid in place_ids)
        visited: set[Tuple[int, ...]] = {initial}
        queue: deque[Tuple[int, ...]] = deque([initial])
        deadlocks: List[Dict[str, int]] = []

        while queue:
            current = queue.popleft()
            enabled_any = False
            for trans_effects in effects.values():
                child = cls._fire_transition(current, tuple(place_ids), trans_effects)
                if child is not None:
                    enabled_any = True
                    if child not in visited:
                        visited.add(child)
                        queue.append(child)
            if not enabled_any:
                marking = dict(zip(place_ids, current))
                # Only report as deadlock if tokens remain in non-termination places.
                if any(marking[pid] > 0 for pid in place_ids if pid not in sink_places):
                    deadlocks.append(marking)

        return {
            "deadlocks": deadlocks,
            "sink_places": sink_places,
            "dead_transitions": dead_transitions,
        }

    @classmethod
    def reachability_check(
        cls,
        net: PetriNet,
        target_marking: Union[Dict[str, int], List[int], Tuple[int, ...]],
        max_depth: int = 100,
    ) -> Tuple[bool, Optional[List[str]]]:
        """Explore the state space (BFS) to decide reachability of a marking.

        ``target_marking`` may be a dict mapping place ids to counts, or a
        sequence ordered by sorted place ids.  On success returns ``(True,
        path)`` where ``path`` is the list of transition ids fired; otherwise
        ``(False, None)``.
        """
        place_ids = tuple(sorted(net.places.keys()))
        effects = cls._transition_effects(net)

        if isinstance(target_marking, dict):
            target = tuple(target_marking.get(pid, 0) for pid in place_ids)
        else:
            target = tuple(target_marking)
            if len(target) != len(place_ids):
                raise ValueError(
                    "target_marking sequence length must match the number of places"
                )

        initial = tuple(len(net.places[pid]) for pid in place_ids)
        if initial == target:
            return (True, [])

        visited: set[Tuple[int, ...]] = {initial}
        queue: deque[Tuple[Tuple[int, ...], List[str]]] = deque([(initial, [])])

        while queue:
            current, path = queue.popleft()
            if len(path) >= max_depth:
                continue
            for transition_id, trans_effects in effects.items():
                child = cls._fire_transition(current, place_ids, trans_effects)
                if child is None:
                    continue
                new_path = path + [transition_id]
                if child == target:
                    return (True, new_path)
                if child not in visited:
                    visited.add(child)
                    queue.append((child, new_path))

        return (False, None)

    @staticmethod
    def _sanitize_tla_identifier(name: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9_]", "_", name)
        if cleaned and cleaned[0].isdigit():
            cleaned = "_" + cleaned
        return cleaned

    @classmethod
    def generate_tla(
        cls,
        net: PetriNet,
        properties: Optional[Dict[str, str]] = None,
        invariants: Optional[Dict[str, str]] = None,
    ) -> str:
        """Generate a TLA+ module string representing the Petri net.

        Places become natural-number variables, each transition becomes a
        named action, and an initial-state predicate is derived from the
        current token distribution.  The module always defines
        ``TypeInvariant`` and ``NoNegativeTokens``; callers may append
        additional properties or invariants through the optional parameters.
        """
        place_ids = tuple(sorted(net.places.keys()))
        effects = cls._transition_effects(net)

        raw_module = net.net_id
        sanitized = cls._sanitize_tla_identifier(raw_module)
        module_name = "".join(part.capitalize() for part in sanitized.split("_") if part)
        if not module_name or not module_name[0].isupper():
            module_name = "Petri" + module_name

        var_names = [cls._sanitize_tla_identifier(pid) for pid in place_ids]
        place_to_var = dict(zip(place_ids, var_names))

        init_parts = [
            f"{var} = {len(net.places[pid])}" for pid, var in place_to_var.items()
        ]

        action_definitions: List[str] = []
        action_names: List[str] = []
        for transition in sorted(
            net.transitions.values(), key=lambda t: t.transition_id
        ):
            tid = transition.transition_id
            input_counts, output_counts = effects[tid]
            delta: Dict[str, int] = {pid: 0 for pid in place_ids}
            enabled_parts: List[str] = []

            for pid, count in input_counts.items():
                var = place_to_var[pid]
                enabled_parts.append(f"{var} >= {count}")
                delta[pid] -= count
            for pid, count in output_counts.items():
                delta[pid] = delta.get(pid, 0) + count

            action_parts: List[str] = []
            for pid in place_ids:
                var = place_to_var[pid]
                d = delta[pid]
                if d == 0:
                    action_parts.append(f"{var}' = {var}")
                elif d > 0:
                    action_parts.append(f"{var}' = {var} + {d}")
                else:
                    action_parts.append(f"{var}' = {var} - {abs(d)}")

            action_name = "T_" + cls._sanitize_tla_identifier(tid)
            action_names.append(action_name)
            parts = enabled_parts + action_parts
            action_body = "\n".join(f"  /\\ {part}" for part in parts)
            action_definitions.append(f"{action_name} ==\n{action_body}")

        init_definition = "Init ==\n" + "\n".join(f"  /\\ {part}" for part in init_parts)

        if action_names:
            next_definition = "Next ==\n" + "\n".join(
                rf"  \/ {name}" for name in action_names
            )
        else:
            next_definition = "Next == UNCHANGED vars"

        type_invariant_body = "\n".join(
            f"  /\\ {var} >= 0" for var in var_names
        )

        property_definitions: List[str] = []
        for name, expr in (properties or {}).items():
            property_definitions.append(f"{name} == {expr}")

        invariant_definitions: List[str] = []
        for name, expr in (invariants or {}).items():
            invariant_definitions.append(f"{name} == {expr}")

        lines = [
            f"---- MODULE {module_name} ----",
            "EXTENDS Naturals",
            "",
            f"VARIABLES {', '.join(var_names)}",
            "",
            f"vars == <<{', '.join(var_names)}>>",
            "",
            init_definition,
            "",
        ]
        if action_definitions:
            lines.extend(action_definitions)
            lines.append("")
        lines.extend(
            [
                next_definition,
                "",
                "Spec == Init /\\ [][Next]_vars /\\ WF_vars(Next)",
                "",
                "TypeInvariant ==",
                type_invariant_body,
                "",
                "NoNegativeTokens == TypeInvariant",
            ]
        )
        if property_definitions:
            lines.append("")
            lines.extend(property_definitions)
        if invariant_definitions:
            lines.append("")
            lines.extend(invariant_definitions)
        lines.append("====================================")
        return "\n".join(lines)

    @classmethod
    def generate_tla_plus(
        cls,
        net: PetriNet,
        properties: Optional[Dict[str, str]] = None,
        invariants: Optional[Dict[str, str]] = None,
    ) -> str:
        """Alias for :meth:`generate_tla` matching the task naming convention."""
        return cls.generate_tla(net, properties=properties, invariants=invariants)

    @classmethod
    def generate_tla_cfg(
        cls,
        net: PetriNet,
        properties: Optional[List[str]] = None,
        invariants: Optional[List[str]] = None,
    ) -> str:
        """Generate a TLC configuration string for the Petri-net module.

        The configuration always references ``Init``, ``Next`` and
        ``TypeInvariant``.  Additional property and invariant names may be
        supplied to extend the check list.
        """
        lines = ["INIT Init", "NEXT Next", "PROPERTY TypeInvariant"]
        for name in properties or []:
            lines.append(f"PROPERTY {name}")
        for name in invariants or []:
            lines.append(f"INVARIANT {name}")
        return "\n".join(lines) + "\n"

    @classmethod
    def generate_coq(cls, net: PetriNet) -> str:
        """Generate a Coq proof skeleton with admitted boundedness/liveness theorems."""
        place_ids = sorted(net.places.keys())
        effects = cls._transition_effects(net)

        place_constructors = "\n  | ".join(f"P_{pid}" for pid in place_ids) or "P_Empty"
        transition_constructors = (
            "\n  | ".join(f"T_{tid}" for tid in sorted(net.transitions.keys()))
            or "T_Dummy"
        )

        lines = [
            "Require Import Coq.Init.Logic.",
            "Require Import Coq.Arith.Arith.",
            "Require Import Coq.Lists.List.",
            "Import ListNotations.",
            "",
            f"Inductive Place : Type :=\n  | {place_constructors}.",
            "",
            f"Inductive Transition : Type :=\n  | {transition_constructors}.",
            "",
            "Definition Marking := Place -> nat.",
            "",
            "Definition pre (t : Transition) (m : Marking) : Prop :=",
            "  match t with",
        ]

        for transition in sorted(
            net.transitions.values(), key=lambda t: t.transition_id
        ):
            input_counts = transition.input_places
            if not input_counts:
                lines.append(f"  | T_{transition.transition_id} => True")
                continue
            parts = " /\\ ".join(
                f"m P_{pid} >= {count}" for pid, count in input_counts.items()
            )
            lines.append(f"  | T_{transition.transition_id} => {parts}")

        lines.extend(
            [
                "  end.",
                "",
                "Definition post (t : Transition) (m m' : Marking) : Prop :=",
                "  match t with",
            ]
        )

        for transition in sorted(
            net.transitions.values(), key=lambda t: t.transition_id
        ):
            input_counts, output_counts = effects[transition.transition_id]
            updates: List[str] = []
            for pid in place_ids:
                delta = output_counts.get(pid, 0) - input_counts.get(pid, 0)
                if delta == 0:
                    updates.append(f"m' P_{pid} = m P_{pid}")
                elif delta > 0:
                    updates.append(f"m' P_{pid} = m P_{pid} + {delta}")
                else:
                    updates.append(f"m' P_{pid} = m P_{pid} - {abs(delta)}")
            conjunction_sep = " /\\ "
            lines.append(
                f"  | T_{transition.transition_id} => {conjunction_sep.join(updates)}"
            )

        lines.extend(
            [
                "  end.",
                "",
                "Definition Bounded (m : Marking) (bound : nat) : Prop :=",
                "  forall p, m p <= bound.",
                "",
                "Theorem net_is_bounded :",
                "  exists bound, forall m, (exists t, pre t m /\\ post t m m) -> Bounded m bound.",
                "Proof.",
                "  admit.",
                "Admitted.",
                "",
                "Theorem net_is_live :",
                "  forall m t, pre t m -> exists m', post t m m'.",
                "Proof.",
                "  admit.",
                "Admitted.",
                "",
            ]
        )
        return "\n".join(lines)

    @classmethod
    def generate_coq_skeleton(cls, net: PetriNet) -> str:
        """Alias for :meth:`generate_coq` matching the task naming convention."""
        return cls.generate_coq(net)
