"""Bridge between PSI cognition, AEvo harness, and the colored Petri net.

Maps the PSI perceive-select-integrate loop and the AEvo candidate
generation/evaluation loop onto ColoredToken places and PetriTransition
firings.  The net is executed by an OrchestrationKernel so that actor
processing and token flow are coordinated through a single runtime.
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any, Dict, List, Optional

from laap.agent_core.psi_cognition import PSICognition
from laap.evolution.aevo.harness import EvolutionHarness
from laap.evolution.aevo.protected_eval import ProtectedEvaluator
from laap.orchestration.actor import AgentCell, ActorSystem, Capability
from laap.orchestration.kernel import OrchestrationKernel
from laap.orchestration.petri import (
    ColoredToken,
    PetriNet,
    PetriPlace,
    PetriTransition,
    TokenColor,
)
from laap.orchestration.primitives import AetherMessage, MessageType


class PSIActor(AgentCell):
    """Actor wrapper around a PSICognition engine.

    The actor handles ``INVOKE`` messages by running a full PSI cycle
    (perceive -> select intention -> integrate) and queues the resulting
    insight as a pending token.  ``process_pending_insights`` flushes the
    queue into ``DATA`` colored tokens that can be deposited into a Petri
    net place.
    """

    def __init__(
        self,
        actor_id: str = "psi_actor",
        psi_cognition: Optional[PSICognition] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(actor_id=actor_id, **kwargs)
        self.register_capability(Capability(name="psi_insight"))
        self.cognition = psi_cognition or PSICognition()
        self._pending_insights: List[ColoredToken] = []
        self._insights_lock = threading.RLock()
        self.on(MessageType.INVOKE, self._handle_invoke)

    async def _handle_invoke(self, message: AetherMessage) -> None:
        """Handle an INVOKE message by running the PSI cycle."""
        await self.handle_invoke_payload(message.payload)

    async def handle_invoke_payload(self, payload: Dict[str, Any]) -> None:
        """Run perceive/select_intention/integrate and queue an insight token."""
        stimulus = payload.get("stimulus", "")
        modality = payload.get("modality", "text")
        perception = self.cognition.perceive(stimulus, modality)

        goal = payload.get("goal", stimulus[:50])
        priority = payload.get("priority", 0.5)
        urgency = payload.get("urgency", 0.0)
        self.cognition.select_intention(goal, priority, urgency)

        integration = self.cognition.integrate()

        insight_value = {
            "kind": "psi_insight",
            "perception": {
                "stimulus": perception.stimulus,
                "salience": perception.salience,
                "modality": perception.modality,
                "timestamp": perception.timestamp,
            },
            "integration": {
                "state": integration.state.value,
                "confidence": integration.confidence,
                "coherence": integration.coherence,
                "arousal": integration.arousal,
                "emotional_valence": integration.emotional_valence,
            },
            "stats": self.cognition.get_stats(),
        }
        token = ColoredToken(color=TokenColor.DATA, value=insight_value)
        with self._insights_lock:
            self._pending_insights.append(token)

    def process_pending_insights(self, batch_size: int = 5) -> List[ColoredToken]:
        """Flush up to ``batch_size`` pending insights as DATA tokens."""
        with self._insights_lock:
            batch = self._pending_insights[:batch_size]
            self._pending_insights = self._pending_insights[batch_size:]
        return batch


class _PlaceholderEvolution:
    """Minimal evolution stand-in used when no real RSIEngine is supplied."""

    def generate_candidate(self, agent: Any) -> Dict[str, Any]:
        return {"param": 0.5, "timestamp": time.time()}


class _PlaceholderEvaluator:
    """Minimal evaluator stand-in with a stable fitness score."""

    def composite_fitness(self, agent: Any) -> float:
        return 0.6


class _SimpleAgent:
    """Tiny agent object satisfying the Harness evaluator interface."""

    def __init__(self) -> None:
        self.config = self
        self.exploration_rate = 0.1
        self.learning_rate = 0.01
        self.step_count = 0

    def step(self) -> None:
        self.step_count += 1


class HarnessActor(AgentCell):
    """Actor wrapper around an EvolutionHarness.

    The actor handles ``INVOKE`` messages by running a short harness
    segment (candidate generation + evaluation) and queues the execution
    summary as a pending token.  ``submit_execution_result`` flushes the
    result as a ``harness_execution_result`` DATA token.
    """

    def __init__(
        self,
        actor_id: str = "harness_actor",
        harness: Optional[EvolutionHarness] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(actor_id=actor_id, **kwargs)
        self.register_capability(Capability(name="harness_execution"))
        self.harness = harness or EvolutionHarness(
            base_evolution=_PlaceholderEvolution(),
            evaluator=ProtectedEvaluator(_PlaceholderEvaluator()),
        )
        self._default_agent = _SimpleAgent()
        self._pending_results: List[ColoredToken] = []
        self._results_lock = threading.RLock()
        self.on(MessageType.INVOKE, self._handle_invoke)

    async def _handle_invoke(self, message: AetherMessage) -> None:
        """Handle an INVOKE message by running the harness segment."""
        await self.handle_invoke_payload(message.payload)

    async def handle_invoke_payload(self, payload: Dict[str, Any]) -> None:
        """Run the harness segment and queue a result token."""
        agent = payload.get("agent", self._default_agent)
        iterations = payload.get("iterations", 1)
        records = self.harness.run_segment(agent, iterations=iterations)

        success = any(getattr(record, "success", False) for record in records)
        fitness = records[-1].fitness_after if records else 0.5

        result_value = {
            "kind": "harness_execution_result",
            "fitness": fitness,
            "success": success,
            "record_count": len(records),
            "records": [
                {
                    "fitness_after": record.fitness_after,
                    "success": record.success,
                    "description": record.description,
                }
                for record in records
            ],
        }
        token = ColoredToken(color=TokenColor.DATA, value=result_value)
        with self._results_lock:
            self._pending_results.append(token)

    def submit_execution_result(self) -> Optional[ColoredToken]:
        """Flush one pending harness execution result as a DATA token."""
        with self._results_lock:
            if not self._pending_results:
                return None
            return self._pending_results.pop(0)


def build_psi_harness_net(
    psi_actor: PSIActor,
    harness_actor: HarnessActor,
) -> PetriNet:
    """Build the PSI-Harness colored Petri net.

    Place/transition topology::

        psi_perception
              |
              v
        psi_process  (requires psi_cycle_control)
              |
              v
        insight_data
              |
              v
        harness_exec
              |
              v
        harness_result
              |
              v
        psi_learn
              |
              +-> psi_perception

    ``psi_cycle_control`` is a CONTROL token gate: one token enables exactly
    one full PSI-Harness cycle, preventing the kernel from looping forever.
    """
    net = PetriNet(net_id="psi_harness")

    net.add_place(PetriPlace("psi_perception", token_types={TokenColor.DATA}))
    net.add_place(
        PetriPlace("psi_cycle_control", token_types={TokenColor.CONTROL}, capacity=100)
    )
    net.add_place(PetriPlace("insight_data", token_types={TokenColor.DATA}))
    net.add_place(PetriPlace("harness_result", token_types={TokenColor.DATA}))

    async def psi_process_action(consumed: Dict[str, Any]) -> List[ColoredToken]:
        token = consumed["psi_perception"][0]
        value = token.value
        payload = value if isinstance(value, dict) else {"stimulus": str(value)}
        await psi_actor.handle_invoke_payload(payload)
        return psi_actor.process_pending_insights(batch_size=5)

    def passthrough_transform(tokens: List[ColoredToken]) -> List[ColoredToken]:
        return tokens

    net.add_transition(
        PetriTransition(
            transition_id="psi_process",
            input_places={"psi_perception": 1, "psi_cycle_control": 1},
            output_places={"insight_data": passthrough_transform},
            action=psi_process_action,
        )
    )

    async def harness_exec_action(consumed: Dict[str, Any]) -> List[ColoredToken]:
        await harness_actor.handle_invoke_payload(
            {"agent": harness_actor._default_agent, "iterations": 1}
        )
        result_token = harness_actor.submit_execution_result()
        return [result_token] if result_token is not None else []

    net.add_transition(
        PetriTransition(
            transition_id="harness_exec",
            input_places={"insight_data": 1},
            output_places={"harness_result": passthrough_transform},
            action=harness_exec_action,
        )
    )

    async def psi_learn_action(consumed: Dict[str, Any]) -> List[ColoredToken]:
        token = consumed["harness_result"][0]
        value = token.value
        success = bool(value.get("success")) if isinstance(value, dict) else False
        outcome = "success" if success else "failure"
        psi_actor.cognition.learn(outcome, success)

        new_stimulus = {
            "stimulus": f"learned: {outcome}",
            "previous_outcome": outcome,
            "timestamp": time.time(),
        }
        return [ColoredToken(color=TokenColor.DATA, value=new_stimulus)]

    net.add_transition(
        PetriTransition(
            transition_id="psi_learn",
            input_places={"harness_result": 1},
            output_places={"psi_perception": passthrough_transform},
            action=psi_learn_action,
        )
    )

    return net


class PSIHarnessOrchestrator:
    """Orchestrator that runs the PSI-Harness Petri net via OrchestrationKernel."""

    def __init__(self, kernel_id: Optional[str] = None) -> None:
        self.system = ActorSystem("psi_harness_system")
        self.psi_actor = PSIActor(actor_id="psi_actor")
        self.harness_actor = HarnessActor(actor_id="harness_actor")
        self._register_actor(self.psi_actor)
        self._register_actor(self.harness_actor)

        self.net = build_psi_harness_net(self.psi_actor, self.harness_actor)
        self.kernel = OrchestrationKernel(
            self.system, self.net, kernel_id=kernel_id
        )

        self.kernel.bind_transition("psi_process", self.psi_actor.actor_id)
        self.kernel.bind_transition("harness_exec", self.harness_actor.actor_id)
        self.kernel.bind_transition("psi_learn", self.psi_actor.actor_id)

    def _register_actor(self, actor: AgentCell) -> None:
        """Add a pre-built actor to the system and start its mailbox loop."""
        self.system.actors[actor.actor_id] = actor
        actor._system = self.system
        try:
            actor._task = asyncio.get_running_loop().create_task(actor.run())
        except RuntimeError:
            actor._task = None

    async def run_cycle(self, stimulus: Any) -> None:
        """Inject a stimulus token and run one full PSI-Harness cycle."""
        stimulus_token = ColoredToken(
            color=TokenColor.DATA,
            value=stimulus if isinstance(stimulus, dict) else {"stimulus": str(stimulus)},
        )
        control_token = ColoredToken(color=TokenColor.CONTROL, value={"cycle": True})

        self.kernel.deposit_token("psi_perception", stimulus_token)
        self.kernel.deposit_token("psi_cycle_control", control_token)

        await self.kernel.run()

    async def shutdown(self) -> None:
        """Stop the kernel and all actors."""
        self.kernel.stop()
        await self.system.shutdown()
