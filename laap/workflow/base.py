"""LAAP - Workflow Engine (Petri-net / actor orchestration backend)."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional
from enum import Enum
import asyncio
import uuid, time, logging

from laap.orchestration.actor import ActorSystem
from laap.orchestration.kernel import OrchestrationKernel
from laap.orchestration.petri import (
    ColoredToken,
    PetriNet,
    PetriPlace,
    PetriTransition,
    TokenColor,
)
from laap.orchestration.primitives import AetherAddress, AetherMessage, MessageType

logger = logging.getLogger("laap.workflow")


class WorkflowStatus(Enum):
    PENDING = "pending"; RUNNING = "running"
    COMPLETED = "completed"; FAILED = "failed"


@dataclass
class WorkflowStep:
    name: str; handler: Callable
    args: Dict[str, Any] = field(default_factory=dict)
    depends_on: List[str] = field(default_factory=list)
    status: WorkflowStatus = WorkflowStatus.PENDING
    result: Any = None; error: Optional[str] = None
    start_time: float = 0.0; end_time: float = 0.0

    @property
    def duration(self) -> float:
        if self.end_time > 0: return self.end_time - self.start_time
        return time.time() - self.start_time if self.start_time > 0 else 0.0


class Workflow:
    def __init__(self, name: str = "Workflow"):
        self.id = str(uuid.uuid4())[:8]
        self.name = name
        self.steps: Dict[str, WorkflowStep] = {}
        self.status = WorkflowStatus.PENDING
        self._results: Dict[str, Any] = {}
        self._order: List[str] = []
        self._petri_net: Optional[PetriNet] = None
        self._actor_system: Optional[ActorSystem] = None
        self._kernel: Optional[OrchestrationKernel] = None
        self._completion_events: Dict[str, asyncio.Event] = {}

    def add_step(self, name: str, handler: Callable,
                 depends_on: Optional[List[str]] = None,
                 **kwargs):
        step = WorkflowStep(name=name, handler=handler, args=kwargs,
                            depends_on=depends_on or [])
        self.steps[name] = step
        self._order.append(name)
        return self

    def to_petri_net(self) -> PetriNet:
        """Return the colored Petri net representing this workflow.

        The net contains a global ``start`` place, ``ready_<step>`` / ``done_<step>``
        places for every step, a single ``init`` transition that fans the start
        token out to root steps, ``join_<step>`` transitions that wait for
        dependencies, and ``trans_<step>`` transitions bound to step actors.
        """
        if self._petri_net is not None:
            return self._petri_net
        return self._build_petri_net()

    def _to_petri(self) -> PetriNet:
        """Backward-compatible alias for :meth:`to_petri_net`."""
        return self.to_petri_net()

    def _build_petri_net(self) -> PetriNet:
        net = PetriNet(net_id=f"wf_{self.id}")
        net.add_place(PetriPlace(place_id="start"))

        for step in self.steps.values():
            net.add_place(PetriPlace(place_id=f"ready_{step.name}"))
            net.add_place(PetriPlace(place_id=f"done_{step.name}"))

        root_steps = [s for s in self.steps.values() if not s.depends_on]
        if root_steps:
            net.add_transition(
                PetriTransition(
                    transition_id="init",
                    input_places={"start": 1},
                    output_places={
                        f"ready_{step.name}": lambda tokens: [
                            ColoredToken(TokenColor.CONTROL, None)
                        ]
                        for step in root_steps
                    },
                )
            )

        for step in self.steps.values():
            if step.depends_on:
                join_inputs: Dict[str, int] = {}
                for dep in step.depends_on:
                    join_inputs[f"done_{dep}"] = 1
                net.add_transition(
                    PetriTransition(
                        transition_id=f"join_{step.name}",
                        input_places=join_inputs,
                        output_places={
                            f"ready_{step.name}": lambda tokens: [
                                ColoredToken(TokenColor.CONTROL, None)
                            ]
                        },
                    )
                )

            net.add_transition(
                PetriTransition(
                    transition_id=f"trans_{step.name}",
                    input_places={f"ready_{step.name}": 1},
                    output_places={
                        f"done_{step.name}": lambda tokens: [
                            ColoredToken(TokenColor.DATA, None)
                        ]
                    },
                    action=None,
                )
            )

        self._petri_net = net
        return net

    def _ensure_actor_system(self) -> ActorSystem:
        if self._actor_system is None:
            self._actor_system = ActorSystem(system_id=f"wf_actors_{self.id}")
        return self._actor_system

    def _ensure_kernel(self) -> OrchestrationKernel:
        if self._kernel is None:
            self._kernel = OrchestrationKernel(
                actor_system=self._ensure_actor_system(),
                petri_net=self.to_petri_net(),
                kernel_id=f"wf_kernel_{self.id}",
            )
        return self._kernel

    def _dependents_count(self, step_name: str) -> int:
        """Return the number of steps that directly depend on *step_name*."""
        return sum(1 for step in self.steps.values() if step_name in step.depends_on)

    async def _setup_actors(self, context: Dict[str, Any]) -> None:
        """Spawn one actor per step and bind it to the matching transition."""
        system = self._ensure_actor_system()
        kernel = self._ensure_kernel()
        for step in self.steps.values():
            actor_id = f"actor_{step.name}"
            if actor_id in system.actors:
                continue
            actor = system.spawn(actor_id, max_retries=0)
            actor.on(MessageType.INVOKE, self._make_actor_handler(step, context))
            kernel.bind_transition(f"trans_{step.name}", actor_id)

    def _make_actor_handler(
        self, step: WorkflowStep, context: Dict[str, Any]
    ) -> Callable[[AetherMessage], Awaitable[None]]:
        """Return an actor handler that invokes the step handler."""
        async def handler(message: AetherMessage) -> None:
            payload = message.payload or {}
            ctx = payload.get("context", context)
            await self._execute_step(step, ctx)

        return handler

    async def _execute_step(self, step: WorkflowStep, context: Dict[str, Any]) -> None:
        """Run a single step handler (sync or async) and record the result."""
        step.start_time = time.time()
        step.status = WorkflowStatus.RUNNING
        try:
            merged_args = {**step.args}
            for dep in step.depends_on:
                if dep in self._results:
                    merged_args[f"_{dep}_result"] = self._results[dep]

            if asyncio.iscoroutinefunction(step.handler):
                step.result = await step.handler(**merged_args)
            else:
                if hasattr(asyncio, "to_thread"):
                    step.result = await asyncio.to_thread(step.handler, **merged_args)
                else:
                    step.result = step.handler(**merged_args)

            step.status = WorkflowStatus.COMPLETED
            self._results[step.name] = step.result
            context[step.name] = step.result
            logger.info(f"  Step [{step.name}] OK ({step.duration:.2f}s)")
        except Exception as e:
            step.status = WorkflowStatus.FAILED
            step.error = str(e)
            logger.error(f"  Step [{step.name}] FAILED: {e}")
        finally:
            step.end_time = time.time()
            event = self._completion_events.get(step.name)
            if event is not None:
                event.set()

    async def _invoke_actor(self, step_name: str, context: Dict[str, Any]) -> None:
        """Send an INVOKE message to a step actor and await its completion."""
        system = self._ensure_actor_system()
        actor_id = f"actor_{step_name}"
        actor = system.actors[actor_id]
        event = asyncio.Event()
        self._completion_events[step_name] = event
        message = AetherMessage(
            msg_type=MessageType.INVOKE,
            sender=AetherAddress(host="local", actor_id=self._kernel.kernel_id),
            recipient=actor.address,
            payload={"context": context, "step_name": step_name},
        )
        await system.send(message)
        await event.wait()

    async def run(self, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Run the workflow asynchronously, returning an updated context dict."""
        self.status = WorkflowStatus.RUNNING
        ctx: Dict[str, Any] = context if context is not None else {}
        logger.info(f"Workflow [{self.name}] start ({len(self.steps)} steps)")
        start = time.time()

        await self._setup_actors(ctx)
        net = self.to_petri_net()
        self._ensure_kernel()

        # Seed the net with a single CONTROL token in the start place.
        net.places["start"].deposit(ColoredToken(TokenColor.CONTROL, None))

        fired_transitions: set[str] = set()

        while True:
            enabled = [
                t for t in net.transitions.values()
                if t.transition_id not in fired_transitions and t.can_fire(net)
            ]
            if not enabled:
                break

            # Fire control-flow transitions first (init and joins).
            control_transitions = [
                t for t in enabled
                if t.transition_id == "init" or t.transition_id.startswith("join_")
            ]
            for transition in control_transitions:
                if await net.fire_transition(transition.transition_id):
                    fired_transitions.add(transition.transition_id)

            # Recompute after control flow moved tokens around.
            enabled = [
                t for t in net.transitions.values()
                if t.transition_id not in fired_transitions and t.can_fire(net)
            ]
            step_transitions = [
                t for t in enabled if t.transition_id.startswith("trans_")
            ]
            if not step_transitions:
                if not control_transitions:
                    break
                continue

            # Execute step handlers concurrently via their bound actors.
            await asyncio.gather(*[
                self._invoke_actor(t.transition_id[6:], ctx)
                for t in step_transitions
            ], return_exceptions=True)

            # Fire the corresponding transitions sequentially to update marking.
            for transition in step_transitions:
                step_name = transition.transition_id[6:]
                step = self.steps[step_name]

                if step.status == WorkflowStatus.COMPLETED:
                    token_count = max(1, self._dependents_count(step_name))
                    transition.output_places = {
                        f"done_{step_name}": lambda tokens, result=step.result, count=token_count: [
                            ColoredToken(TokenColor.DATA, result)
                            for _ in range(count)
                        ]
                    }
                else:
                    # Failed step: consume the ready token but produce no output
                    # so downstream steps remain blocked.
                    transition.output_places = {}

                if await net.fire_transition(transition.transition_id):
                    fired_transitions.add(transition.transition_id)

        # Steps that never fired failed because a dependency was missing or failed.
        for step in self.steps.values():
            if step.status == WorkflowStatus.PENDING:
                step.status = WorkflowStatus.FAILED
                step.error = f"依赖未满足: {step.depends_on}"
                step.end_time = time.time()

        self.status = WorkflowStatus.COMPLETED
        total = time.time() - start
        failed = [s for s in self.steps.values() if s.status == WorkflowStatus.FAILED]
        logger.info(f"Workflow done: {total:.1f}s, {len(failed)} failed")

        result = dict(ctx)
        result.update({
            "workflow": self.name,
            "status": self.status.value,
            "duration_s": round(total, 2),
            "failed": len(failed),
            "results": {n: str(r)[:100] for n, r in self._results.items()},
        })
        return result

    def status_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "status": self.status.value,
                "steps": [{"name": s.name, "status": s.status.value,
                           "duration": round(s.duration, 2)}
                          for s in self.steps.values()]}
