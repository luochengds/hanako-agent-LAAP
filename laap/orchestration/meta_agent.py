"""LAAP Aether — Meta-Agent topology evolution.

The MetaAgent watches an ActorSystem, detects overloaded or idle actors,
spawns helper actors, and selects the best candidate actor for a capability
using an epsilon-greedy UCB bandit.
"""

from __future__ import annotations

import copy
import math
import random
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional

from laap.orchestration.actor import ActorState, ActorSystem, AgentCell, Capability
from laap.orchestration.primitives import AetherMessage, MessageType
from laap.skills.engine import SkillEngine


def sync_skills_as_capabilities(skill_engine: SkillEngine) -> List[Capability]:
    """Convert every loaded Skill into a Capability advertisement.

    The produced Capability uses the skill name, a fixed confidence of 0.8,
    and an empty schema.  This allows skills discovered by the SkillEngine to
    be broadcast as actor capabilities inside an ActorSystem.
    """
    return [
        Capability(name=skill.name, confidence=0.8, schema={})
        for skill in skill_engine.get_all()
    ]


class MetaAgent:
    """Topology evolution controller for an ActorSystem.

    Holds an ActorSystem and an optional SkillEngine.  It can monitor actor
    health, recruit helper actors for bottlenecks, retire idle/low-performing
    actors, and select the best actor for a given capability via epsilon-greedy
    UCB.
    """

    def __init__(
        self,
        actor_system: ActorSystem,
        skill_engine: Optional[SkillEngine] = None,
        epsilon: float = 0.1,
        ucb_exploration_constant: float = math.sqrt(2),
    ):
        self.actor_system = actor_system
        self.skill_engine = skill_engine
        self.epsilon = epsilon
        self.ucb_c = ucb_exploration_constant

        # Bandit history for select_best_agent.
        self._selection_counts: Dict[str, int] = defaultdict(int)
        self._total_rewards: Dict[str, float] = defaultdict(float)

        # Idle detection: first-seen timestamp and processed count per actor.
        self._actor_first_seen: Dict[str, tuple[float, int]] = {}

    # ------------------------------------------------------------------
    # Monitoring
    # ------------------------------------------------------------------
    def monitor(self) -> List[str]:
        """Scan actor metrics and return ids of bottleneck actors.

        A bottleneck is defined as an actor whose ``messages_processed`` is
        greater than 50 and whose error rate exceeds 10%.
        """
        bottlenecks: List[str] = []
        for actor in self.actor_system.actors.values():
            processed = actor.metrics.get("messages_processed", 0)
            if processed <= 50:
                continue
            errors = actor.metrics.get("errors", 0)
            total = processed + errors
            if total == 0:
                continue
            error_rate = errors / total
            if error_rate > 0.1:
                bottlenecks.append(actor.actor_id)
        return bottlenecks

    # ------------------------------------------------------------------
    # Recruitment
    # ------------------------------------------------------------------
    def recruit_helper(
        self,
        bottleneck_actor_id: str,
        capability_names: List[str],
    ) -> str:
        """Spawn a helper actor that replicates capabilities of a bottleneck.

        The helper is added to the ActorSystem (and therefore becomes visible to
        any AAOSACoordinator using the same system).  Its supervisor is set to
        the bottleneck actor.
        """
        source = self.actor_system.actors.get(bottleneck_actor_id)
        if source is None:
            raise ValueError(f"Bottleneck actor {bottleneck_actor_id!r} not found")

        names = set(capability_names)
        helper_caps = [
            copy.deepcopy(cap)
            for cap in source.capabilities
            if cap.name in names
        ]

        base_id = f"{bottleneck_actor_id}_helper"
        idx = 1
        helper_id = f"{base_id}_{idx}"
        while helper_id in self.actor_system.actors:
            idx += 1
            helper_id = f"{base_id}_{idx}"

        helper = self.actor_system.spawn(
            helper_id,
            capabilities=helper_caps,
            supervisor=source.address,
        )
        source.children.add(helper.address)
        return helper_id

    # ------------------------------------------------------------------
    # Retirement
    # ------------------------------------------------------------------
    async def retire_idle_actor(self, idle_threshold_sec: float = 300) -> List[str]:
        """Mark actors that have not processed messages for a while.

        Actors whose processed message count has not changed since they were
        first observed and whose observation window exceeds the threshold are
        marked as ``RECOVERING``.  The original actor object is preserved.
        """
        now = time.monotonic()
        retired: List[str] = []

        for actor in self.actor_system.actors.values():
            actor_id = actor.actor_id
            processed = actor.metrics.get("messages_processed", 0)

            if actor_id not in self._actor_first_seen:
                self._actor_first_seen[actor_id] = (now, processed)
                continue

            seen_time, seen_processed = self._actor_first_seen[actor_id]
            if processed == seen_processed and now - seen_time >= idle_threshold_sec:
                async with actor.state_lock:
                    actor.state = ActorState.RECOVERING
                retired.append(actor_id)
            elif processed != seen_processed:
                self._actor_first_seen[actor_id] = (now, processed)

        return retired

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------
    def _actor_reward(self, actor: AgentCell) -> float:
        """Compute a 0..1 reward combining success rate and latency."""
        processed = actor.metrics.get("messages_processed", 0)
        errors = actor.metrics.get("errors", 0)
        total = processed + errors
        success_rate = processed / total if total else 0.0

        latency = actor.metrics.get("avg_latency_ms", 0.0)
        if latency > 0:
            # Normalise latency: faster actors get a small bonus.
            latency_bonus = min(1.0, 1000.0 / latency) * 0.2
        else:
            latency_bonus = 0.2

        # Keep the reward in [0, 1].
        return min(1.0, success_rate * 0.8 + latency_bonus)

    def _ucb_score(self, actor: AgentCell) -> float:
        """Return the UCB score for an actor."""
        actor_id = actor.actor_id
        n_i = self._selection_counts[actor_id]
        if n_i == 0:
            return float("inf")
        avg_reward = self._total_rewards[actor_id] / n_i
        N = max(1, sum(self._selection_counts.values()))
        return avg_reward + self.ucb_c * math.sqrt(math.log(N) / n_i)

    def select_best_agent(
        self,
        capability: str,
        candidates: List[AgentCell],
    ) -> AgentCell:
        """Select the best actor for *capability* using epsilon-greedy UCB.

        The reward is derived from the actor's historical success rate and
        average latency.  A small epsilon probability promotes exploration.
        """
        capable = [
            actor
            for actor in candidates
            if any(cap.name.lower() == capability.lower() for cap in actor.capabilities)
        ]
        if not capable:
            raise ValueError(f"No candidate can handle capability {capability!r}")

        if random.random() < self.epsilon:
            winner = random.choice(capable)
        else:
            winner = max(capable, key=self._ucb_score)

        # Update bandit history using the current observed reward.
        actor_id = winner.actor_id
        self._selection_counts[actor_id] += 1
        self._total_rewards[actor_id] += self._actor_reward(winner)
        return winner

    # ------------------------------------------------------------------
    # Evolution
    # ------------------------------------------------------------------
    async def evolve(self) -> Dict[str, Any]:
        """Execute one evolution cycle: monitor, recruit, retire."""
        bottlenecks = self.monitor()
        helpers: List[str] = []
        for bottleneck_id in bottlenecks:
            actor = self.actor_system.actors.get(bottleneck_id)
            if actor is None:
                continue
            capability_names = [cap.name for cap in actor.capabilities]
            helper_id = self.recruit_helper(bottleneck_id, capability_names)
            helpers.append(helper_id)

        retired = await self.retire_idle_actor()

        return {
            "bottlenecks": bottlenecks,
            "helpers": helpers,
            "retired": retired,
        }

    async def handle_aether_message(self, msg: AetherMessage) -> Dict[str, Any]:
        """React to an AetherMessage; META_EVOLVE triggers an evolution cycle."""
        if msg.msg_type == MessageType.META_EVOLVE:
            return await self.evolve()
        return {}

    # ------------------------------------------------------------------
    # Skill integration
    # ------------------------------------------------------------------
    def sync_skills(self) -> List[Capability]:
        """Convert the bound SkillEngine's skills into capabilities."""
        if self.skill_engine is None:
            return []
        return sync_skills_as_capabilities(self.skill_engine)
