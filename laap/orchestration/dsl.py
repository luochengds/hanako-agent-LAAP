"""LAAP-DSL compiler — turns high-level orchestration expressions into colored Petri nets."""

from __future__ import annotations

import inspect
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from laap.orchestration.actor import ActorSystem, Capability
from laap.orchestration.petri import ColoredToken, PetriNet, PetriPlace, PetriTransition, TokenColor
from laap.tools.base import ToolResult


# ---------------------------------------------------------------------------
# AST nodes
# ---------------------------------------------------------------------------


class LAAPExpr(ABC):
    """Base class for LAAP-DSL AST nodes."""

    @abstractmethod
    def compile(self, builder: LAAPBuilder) -> Tuple[str, str]:
        """Compile this node into input/output place ids using *builder*."""
        raise NotImplementedError


@dataclass(frozen=True)
class InferNode(LAAPExpr):
    """An inference / LLM call expression."""

    model: str
    prompt: str
    output_key: str

    def compile(self, builder: LAAPBuilder) -> Tuple[str, str]:
        in_id = builder.add_place("infer")
        out_id = builder.add_place("infer")
        actor_id = builder.bind_actor("infer")
        transition_id = builder.add_transition(
            "infer",
            {in_id: 1},
            {out_id: _identity},
            action=lambda _consumed: [
                ColoredToken(
                    color=TokenColor.DATA,
                    value={"model": self.model, "prompt": self.prompt, "output_key": self.output_key},
                )
            ],
        )
        builder.actor_bindings.setdefault(transition_id, []).append(actor_id)
        builder.output_places[self.output_key] = out_id
        return in_id, out_id


@dataclass(frozen=True)
class ActNode(LAAPExpr):
    """A tool / action invocation expression."""

    tool: str
    params: Dict[str, Any]
    output_key: str

    def compile(self, builder: LAAPBuilder) -> Tuple[str, str]:
        in_id = builder.add_place("act")
        out_id = builder.add_place("act")
        actor_id = builder.bind_actor("act")
        transition_id = builder.add_transition(
            "act",
            {in_id: 1},
            {out_id: _identity},
            action=self._make_action(builder, actor_id),
        )
        builder.actor_bindings.setdefault(transition_id, []).append(actor_id)
        builder.output_places[self.output_key] = out_id
        return in_id, out_id

    def _make_action(
        self, builder: LAAPBuilder, actor_id: str
    ) -> Callable[[Dict[str, Any]], Any]:
        async def _action(_consumed: Dict[str, Any]) -> List[ColoredToken]:
            if builder.tool_registry is not None:
                result = await _call_tool(
                    builder.tool_registry, self.tool, self.params
                )
                return [
                    ColoredToken(
                        TokenColor.DATA,
                        {
                            "tool": self.tool,
                            "output_key": self.output_key,
                            "result": result,
                        },
                    )
                ]
            if builder.actor_system is not None:
                value: Dict[str, Any] = {
                    "actor_id": actor_id,
                    "capability": self.tool,
                    "output_key": self.output_key,
                }
                value.update(self.params)
                return [ColoredToken(TokenColor.AGENT_REF, value)]
            return [
                ColoredToken(
                    TokenColor.DATA,
                    {
                        "tool": self.tool,
                        "output_key": self.output_key,
                        "params": self.params,
                    },
                )
            ]

        return _action


@dataclass(frozen=True)
class SkillNode(LAAPExpr):
    """A skill / capability reference expression."""

    skill_name: str
    params: Dict[str, Any]
    output_key: str

    def compile(self, builder: LAAPBuilder) -> Tuple[str, str]:
        in_id = builder.add_place("skill")
        out_id = builder.add_place("skill")
        actor_id = builder.bind_actor("skill")
        value = {"skill": self.skill_name, "output_key": self.output_key}
        value.update(self.params)
        transition_id = builder.add_transition(
            "skill",
            {in_id: 1},
            {out_id: _identity},
            action=lambda _consumed: [ColoredToken(color=TokenColor.DATA, value=value)],
        )
        builder.actor_bindings.setdefault(transition_id, []).append(actor_id)
        builder.output_places[self.output_key] = out_id
        return in_id, out_id


@dataclass(frozen=True)
class SeqNode(LAAPExpr):
    """Sequential composition."""

    children: Tuple[LAAPExpr, ...]

    def compile(self, builder: LAAPBuilder) -> Tuple[str, str]:
        if not self.children:
            empty_id = builder.add_place("seq_empty")
            return empty_id, empty_id

        entry: Optional[str] = None
        exit_: Optional[str] = None
        for idx, child in enumerate(self.children):
            child_in, child_out = builder.compile(child)
            if idx == 0:
                entry = child_in
            else:
                assert exit_ is not None
                builder.add_transition("seq", {exit_: 1}, {child_in: _identity})
            exit_ = child_out

        assert entry is not None and exit_ is not None
        return entry, exit_


@dataclass(frozen=True)
class ParNode(LAAPExpr):
    """Parallel composition."""

    children: Tuple[LAAPExpr, ...]

    def compile(self, builder: LAAPBuilder) -> Tuple[str, str]:
        entry = builder.add_place("par_entry")
        join = builder.add_place("par_join")

        if not self.children:
            builder.add_transition("par", {entry: 1}, {join: _identity})
            return entry, join

        branches = [builder.compile(child) for child in self.children]
        branch_ins = [b[0] for b in branches]
        branch_outs = [b[1] for b in branches]

        builder.add_transition(
            "par_fork", {entry: 1}, {b_in: _identity for b_in in branch_ins}
        )
        builder.add_transition(
            "par_join", {b_out: 1 for b_out in branch_outs}, {join: _identity}
        )
        return entry, join


@dataclass(frozen=True)
class GuardNode(LAAPExpr):
    """Conditional branching."""

    condition_expr: LAAPExpr
    then_branch: LAAPExpr
    else_branch: Optional[LAAPExpr] = None

    def compile(self, builder: LAAPBuilder) -> Tuple[str, str]:
        cond_in, cond_out = builder.compile(self.condition_expr)
        then_in, then_out = builder.compile(self.then_branch)
        exit_ = builder.add_place("guard_exit")

        builder.add_transition(
            "guard_true",
            {cond_out: 1},
            {then_in: _identity},
            guard=_truthy_guard(cond_out),
        )

        if self.else_branch is not None:
            else_in, else_out = builder.compile(self.else_branch)
            builder.add_transition(
                "guard_false",
                {cond_out: 1},
                {else_in: _identity},
                guard=_falsey_guard(cond_out),
            )
            builder.add_transition(
                "guard_merge_else", {else_out: 1}, {exit_: _identity}
            )
        else:
            builder.add_transition(
                "guard_false",
                {cond_out: 1},
                {exit_: _identity},
                guard=_falsey_guard(cond_out),
            )

        builder.add_transition(
            "guard_merge_then", {then_out: 1}, {exit_: _identity}
        )
        return cond_in, exit_


@dataclass(frozen=True)
class LoopNode(LAAPExpr):
    """Bounded loop with an iteration-count token."""

    body: LAAPExpr
    max_iter: int = 5

    def compile(self, builder: LAAPBuilder) -> Tuple[str, str]:
        body_in, body_out = builder.compile(self.body)
        entry = builder.add_place("loop_entry")
        exit_ = builder.add_place("loop_exit")
        decision = builder.add_place("loop_decision")
        counter = builder.add_place("loop_counter")

        builder.net.places[counter].deposit(
            ColoredToken(color=TokenColor.META, value=0)
        )

        builder.add_transition(
            "loop_init",
            {entry: 1, counter: 1},
            {body_in: _payload_only, counter: _meta_only},
        )
        builder.add_transition(
            "loop_iter",
            {body_out: 1, counter: 1},
            {decision: _payload_only, counter: _increment_counter},
        )
        builder.add_transition(
            "loop_continue",
            {decision: 1, counter: 1},
            {body_in: _payload_only, counter: _meta_only},
            guard=_loop_continue_guard(counter, self.max_iter),
        )
        builder.add_transition(
            "loop_exit",
            {decision: 1, counter: 1},
            {exit_: _payload_only, counter: _meta_only},
            guard=_loop_exit_guard(counter, self.max_iter),
        )

        return entry, exit_


# ---------------------------------------------------------------------------
# Builder API
# ---------------------------------------------------------------------------


def infer(model: str, prompt: str, output_key: str) -> InferNode:
    """Build an INFER expression."""
    return InferNode(model=model, prompt=prompt, output_key=output_key)


def act(tool: str, params: Dict[str, Any], output_key: str) -> ActNode:
    """Build an ACT expression."""
    return ActNode(tool=tool, params=params, output_key=output_key)


def skill(skill_name: str, params: Dict[str, Any], output_key: str) -> SkillNode:
    """Build a SKILL expression."""
    return SkillNode(skill_name=skill_name, params=params, output_key=output_key)


def seq(*children: LAAPExpr) -> SeqNode:
    """Build a sequential composition expression."""
    return SeqNode(children=children)


def par(*children: LAAPExpr) -> ParNode:
    """Build a parallel composition expression."""
    return ParNode(children=children)


def guard(
    condition_expr: LAAPExpr,
    then_branch: LAAPExpr,
    else_branch: Optional[LAAPExpr] = None,
) -> GuardNode:
    """Build a guarded / conditional expression."""
    return GuardNode(
        condition_expr=condition_expr,
        then_branch=then_branch,
        else_branch=else_branch,
    )


def loop(body: LAAPExpr, max_iter: int = 5) -> LoopNode:
    """Build a bounded loop expression."""
    return LoopNode(body=body, max_iter=max_iter)


# ---------------------------------------------------------------------------
# Builder / compiler
# ---------------------------------------------------------------------------


def _identity(tokens: List[ColoredToken]) -> List[ColoredToken]:
    """Pass tokens through unchanged."""
    return tokens


def _resolve_tool_handler(registry: Any, tool_name: str) -> Optional[Callable]:
    """Resolve a tool name to a callable from a registry-like object."""
    if hasattr(registry, "get_tool"):
        fn = registry.get_tool(tool_name)
        if fn is not None:
            return fn
    if hasattr(registry, "get"):
        entry = registry.get(tool_name)
        if entry is not None:
            if callable(entry):
                return entry
            if hasattr(entry, "handler"):
                return entry.handler
            if isinstance(entry, dict):
                return entry.get("fn")
    if isinstance(registry, dict):
        entry = registry.get(tool_name)
        if callable(entry):
            return entry
        if isinstance(entry, dict):
            return entry.get("fn")
    return None


async def _call_tool(registry: Any, tool_name: str, params: Dict[str, Any]) -> Any:
    """Call a tool through *registry* and normalize the result."""
    fn = _resolve_tool_handler(registry, tool_name)
    if fn is None:
        raise RuntimeError(f"Tool '{tool_name}' not found in registry")
    if inspect.iscoroutinefunction(fn):
        result = await fn(**params)
    else:
        result = fn(**params)
    if isinstance(result, ToolResult):
        return result
    return ToolResult(success=True, output=str(result))


def _payload_only(tokens: List[ColoredToken]) -> List[ColoredToken]:
    """Keep every token that is not the loop counter."""
    return [t for t in tokens if t.color != TokenColor.META]


def _meta_only(tokens: List[ColoredToken]) -> List[ColoredToken]:
    """Keep only the loop counter token."""
    return [t for t in tokens if t.color == TokenColor.META]


def _increment_counter(tokens: List[ColoredToken]) -> List[ColoredToken]:
    """Increment the integer counter token flowing through a LOOP."""
    for token in tokens:
        if token.color == TokenColor.META and isinstance(token.value, int):
            return [ColoredToken(color=TokenColor.META, value=token.value + 1)]
    return []


def _truthy_guard(place_id: str) -> Callable[[PetriNet, PetriTransition], bool]:
    def guard(net: PetriNet, _transition: PetriTransition) -> bool:
        place = net.places.get(place_id)
        if place is None or not place.tokens:
            return False
        return bool(place.tokens[0].value)

    return guard


def _falsey_guard(place_id: str) -> Callable[[PetriNet, PetriTransition], bool]:
    def guard(net: PetriNet, _transition: PetriTransition) -> bool:
        place = net.places.get(place_id)
        if place is None or not place.tokens:
            return False
        return not bool(place.tokens[0].value)

    return guard


def _loop_continue_guard(
    counter_place_id: str, max_iter: int
) -> Callable[[PetriNet, PetriTransition], bool]:
    def guard(net: PetriNet, _transition: PetriTransition) -> bool:
        place = net.places.get(counter_place_id)
        if place is None or not place.tokens:
            return False
        value = place.tokens[0].value
        return isinstance(value, int) and value < max_iter

    return guard


def _loop_exit_guard(
    counter_place_id: str, max_iter: int
) -> Callable[[PetriNet, PetriTransition], bool]:
    def guard(net: PetriNet, _transition: PetriTransition) -> bool:
        place = net.places.get(counter_place_id)
        if place is None or not place.tokens:
            return False
        value = place.tokens[0].value
        return isinstance(value, int) and value >= max_iter

    return guard


class LAAPBuilder:
    """Stateful compiler from LAAP-DSL AST to a colored Petri net plus actor bindings."""

    def __init__(
        self,
        net_id: str,
        actor_system: Optional[ActorSystem] = None,
        tool_registry: Optional[Any] = None,
    ) -> None:
        self.net = PetriNet(net_id=net_id)
        self.actor_system = actor_system
        self.tool_registry = tool_registry
        self.actor_bindings: Dict[str, List[str]] = {}
        self.output_places: Dict[str, str] = {}
        self._place_counter = 0
        self._transition_counter = 0
        self._actor_counter = 0

    def _next_place_id(self, prefix: str) -> str:
        place_id = f"p_{prefix}_{self._place_counter}"
        self._place_counter += 1
        return place_id

    def _next_transition_id(self, prefix: str) -> str:
        transition_id = f"t_{prefix}_{self._transition_counter}"
        self._transition_counter += 1
        return transition_id

    def add_place(self, prefix: str, **kwargs: Any) -> str:
        """Create and register a place, returning its id."""
        place_id = self._next_place_id(prefix)
        self.net.add_place(PetriPlace(place_id=place_id, **kwargs))
        return place_id

    def add_transition(
        self,
        prefix: str,
        input_places: Dict[str, int],
        output_places: Dict[str, Callable[[List[ColoredToken]], List[ColoredToken]]],
        guard: Optional[Callable[[PetriNet, PetriTransition], bool]] = None,
        action: Optional[Callable[[Dict[str, Any]], Any]] = None,
    ) -> str:
        """Create and register a transition, returning its id."""
        transition_id = self._next_transition_id(prefix)
        transition = PetriTransition(
            transition_id=transition_id,
            input_places=input_places,
            output_places=output_places,
            guard=guard or (lambda _net, _trans: True),
            action=action,
        )
        self.net.add_transition(transition)
        return transition_id

    def bind_actor(self, prefix: str) -> str:
        """Reserve an actor id for a leaf transition and optionally spawn it."""
        actor_id = f"actor_{prefix}_{self._actor_counter}"
        self._actor_counter += 1
        if self.actor_system is not None and actor_id not in self.actor_system.actors:
            self.actor_system.spawn(
                actor_id,
                capabilities=[Capability(name=prefix, confidence=1.0)],
            )
        return actor_id

    def compile(self, expr: LAAPExpr) -> Tuple[str, str]:
        """Compile *expr* and return its entry and exit place ids."""
        return expr.compile(self)

    def build(
        self, expr: LAAPExpr
    ) -> Tuple[PetriNet, Dict[str, List[str]], Dict[str, str]]:
        """Compile *expr*, seed the net, and return (net, actor_bindings, output_places)."""
        entry, _exit = self.compile(expr)
        self.net.places[entry].deposit(
            ColoredToken(color=TokenColor.CONTROL, value={"start": True})
        )
        return self.net, self.actor_bindings, self.output_places


# ---------------------------------------------------------------------------
# Public compiler entry points
# ---------------------------------------------------------------------------


def compile_workflow(
    expr: LAAPExpr,
    net_id: str = "laap_workflow",
    actor_system: Optional[ActorSystem] = None,
    tool_registry: Optional[Any] = None,
) -> Tuple[PetriNet, Dict[str, List[str]], Dict[str, str]]:
    """Compile a LAAP-DSL AST into a Petri net with actor bindings."""
    builder = LAAPBuilder(
        net_id=net_id, actor_system=actor_system, tool_registry=tool_registry
    )
    return builder.build(expr)


def laap_cli_compile(expr: LAAPExpr, net_id: str = "laap_cli") -> None:
    """Compile *expr* and print the resulting Petri net structure."""
    net, actor_bindings, output_places = compile_workflow(expr, net_id=net_id)
    print(f"Net: {net.net_id}")
    print(f"Places ({len(net.places)}):")
    for place_id in sorted(net.places):
        print(f"  {place_id}")
    print(f"Transitions ({len(net.transitions)}):")
    for transition_id in sorted(net.transitions):
        transition = net.transitions[transition_id]
        print(
            f"  {transition_id}: "
            f"in={dict(transition.input_places)} "
            f"out={list(transition.output_places)}"
        )
    print("Actor bindings:")
    for transition_id, actor_ids in actor_bindings.items():
        print(f"  {transition_id} -> {actor_ids}")
    print("Output places:")
    for key, place_id in output_places.items():
        print(f"  {key} -> {place_id}")


__all__ = [
    "LAAPExpr",
    "InferNode",
    "ActNode",
    "SkillNode",
    "SeqNode",
    "ParNode",
    "GuardNode",
    "LoopNode",
    "LAAPBuilder",
    "infer",
    "act",
    "skill",
    "seq",
    "par",
    "guard",
    "loop",
    "compile_workflow",
    "laap_cli_compile",
]
