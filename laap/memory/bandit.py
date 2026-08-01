"""LAAP — Memory bandit controller

Solves the Memory Paradox's adaptive-strategy gap.
Instead of a single retrieval policy, this controller learns when to
switch among retrieval strategies using multi-armed bandit feedback.

Arms:
  MINIMAL — early/open task: small top-k, high threshold, low noise.
  COMPREHENSIVE — exploratory/creative task: larger top-k, low threshold.
  RECONSTRUCTIVE — stuck/failed task: boost related memory + assumption recall.
  PRUNING — long-running task: prefer recent + high-importance, compress old.

The controller exposes ``select_arm(cognitive_state, query)`` for the
memory manager/orchestration layer to consume. Rewards are supplied by
the cognition layer via ``record_reward(arm, reward)``.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("laap.memory.bandit")


class MemoryBanditArm(str, Enum):
    MINIMAL = "minimal"
    COMPREHENSIVE = "comprehensive"
    RECONSTRUCTIVE = "reconstructive"
    PRUNING = "pruning"


@dataclass
class ArmConfig:
    """Parameters for one retrieval strategy."""
    top_k: int = 6
    min_importance: float = 0.0
    prefer_recent: bool = False
    recall_assumptions: bool = False
    boost_related: bool = False
    compress_old: bool = False
    max_age_s: Optional[float] = None


ARM_CONFIGS: Dict[MemoryBanditArm, ArmConfig] = {
    MemoryBanditArm.MINIMAL: ArmConfig(
        top_k=3, min_importance=0.45, prefer_recent=False,
        recall_assumptions=False, boost_related=False, compress_old=False,
    ),
    MemoryBanditArm.COMPREHENSIVE: ArmConfig(
        top_k=12, min_importance=0.0, prefer_recent=False,
        recall_assumptions=False, boost_related=True, compress_old=False,
    ),
    MemoryBanditArm.RECONSTRUCTIVE: ArmConfig(
        top_k=10, min_importance=0.0, prefer_recent=False,
        recall_assumptions=True, boost_related=True, compress_old=False,
    ),
    MemoryBanditArm.PRUNING: ArmConfig(
        top_k=6, min_importance=0.25, prefer_recent=True,
        recall_assumptions=False, boost_related=False, compress_old=True,
        max_age_s=3600.0,
    ),
}


@dataclass
class ArmStats:
    count: int = 0
    total_reward: float = 0.0
    last_used_at: float = 0.0

    @property
    def mean_reward(self) -> float:
        return self.total_reward / self.count if self.count else 0.0


class MemoryBanditController:
    """Contextual multi-armed bandit over memory retrieval strategies."""

    def __init__(self, exploration_eps: float = 0.15) -> None:
        self._stats: Dict[MemoryBanditArm, ArmStats] = {
            arm: ArmStats() for arm in MemoryBanditArm
        }
        self._recent_rewards: List[float] = []
        self._max_recent = 50
        self._last_arm: Optional[MemoryBanditArm] = None
        self._last_query: str = ""
        self._exploration_eps = exploration_eps
        self._context: Dict[str, Any] = {}

    def select_arm(
        self,
        cognitive_state: Optional[Dict[str, Any]] = None,
        query: str = "",
    ) -> tuple[MemoryBanditArm, ArmConfig]:
        """Choose a retrieval strategy for this turn.

        Args:
            cognitive_state: optional dict from IntegratedCognitiveEngine
            query: current query text, used for context-sensitive priors.

        Returns:
            (selected arm, arm config)
        """
        self._last_query = query or ""
        self._context = cognitive_state or {}

        if self._should_explore():
            arm = self._explore()
        else:
            arm = self._ucb1_best()

        self._last_arm = arm
        self._stats[arm].last_used_at = time.time()
        self._stats[arm].count += 1
        return arm, ARM_CONFIGS[arm]

    def record_reward(self, reward: float) -> None:
        """Record outcome quality for the previously selected arm.

        Args:
            reward: normalized quality signal in [0, 1].
                Good candidates:
                - task success indicator
                - retrieval relevance feedback
                - downstream response accuracy
        """
        if self._last_arm is None:
            return
        reward = max(0.0, min(1.0, float(reward)))
        self._stats[self._last_arm].total_reward += reward
        self._recent_rewards.append(reward)
        if len(self._recent_rewards) > self._max_recent:
            self._recent_rewards = self._recent_rewards[-self._max_recent:]
        logger.debug(
            f"[memory_bandit] arm={self._last_arm.value} reward={reward:.3f}"
        )

    def record_relevance_feedback(self, used: int, helpful: int) -> None:
        """Convenience wrapper: reward = helpful / used."""
        if used <= 0:
            return
        self.record_reward(helpful / used)

    def last_arm(self) -> Optional[MemoryBanditArm]:
        return self._last_arm

    def stats(self) -> Dict[str, Any]:
        return {
            arm.value: {
                "count": s.count,
                "mean_reward": round(s.mean_reward, 4),
                "total_reward": round(s.total_reward, 4),
                "last_used_at": s.last_used_at,
            }
            for arm, s in self._stats.items()
        }

    def reset(self) -> None:
        """Reset bandit state. Useful when entering a new major task."""
        for s in self._stats.values():
            s.count = 0
            s.total_reward = 0.0
            s.last_used_at = 0.0
        self._recent_rewards.clear()
        self._last_arm = None
        self._context.clear()

    def _should_explore(self) -> bool:
        """Epsilon-greedy with warm-up decay."""
        total = sum(s.count for s in self._stats.values())
        if total < 4:
            return True
        return math.random() < self._exploration_eps

    def _explore(self) -> MemoryBanditArm:
        """Pick an under-sampled arm."""
        min_count = min(s.count for s in self._stats.values())
        candidates = [arm for arm, s in self._stats.items() if s.count == min_count]
        if self._context:
            return self._contextual_prior(candidates)
        return candidates[0]

    def _ucb1_best(self) -> MemoryBanditArm:
        """UCB1 selection with contextual prior jitter."""
        total = sum(s.count for s in self._stats.values()) or 1
        best_arm = MemoryBanditArm.MINIMAL
        best_score = -1e9
        for arm, s in self._stats.items():
            mean = s.mean_reward
            ucb = mean + math.sqrt(2.0 * math.log(total) / (s.count + 1e-6))
            if self._context:
                ucb += self._contextual_bonus(arm) * 0.25
            if ucb > best_score:
                best_score = ucb
                best_arm = arm
        return best_arm

    def _contextual_prior(self, candidates: List[MemoryBanditArm]) -> MemoryBanditArm:
        """Prefer arms that match current cognitive state."""
        ctx = self._context
        entropy = float(ctx.get("entropy", 0.5))
        flow_regime = str(ctx.get("flow_regime", "laminar"))
        confidence = float(ctx.get("confidence", 0.5))

        score = {arm: 0.0 for arm in candidates}
        for arm in candidates:
            if arm == MemoryBanditArm.RECONSTRUCTIVE and confidence < 0.35:
                score[arm] += 1.0
            if arm == MemoryBanditArm.PRUNING and flow_regime == "laminar":
                score[arm] += 0.8
            if arm == MemoryBanditArm.COMPREHENSIVE and entropy > 0.65:
                score[arm] += 0.7
            if arm == MemoryBanditArm.MINIMAL and confidence > 0.8:
                score[arm] += 0.6
        return max(score, key=lambda a: score[a])

    def _contextual_bonus(self, arm: MemoryBanditArm) -> float:
        ctx = self._context
        entropy = float(ctx.get("entropy", 0.5))
        confidence = float(ctx.get("confidence", 0.5))
        flow_regime = str(ctx.get("flow_regime", "laminar"))

        if arm == MemoryBanditArm.RECONSTRUCTIVE and confidence < 0.35:
            return 0.6
        if arm == MemoryBanditArm.PRUNING and flow_regime == "laminar":
            return 0.5
        if arm == MemoryBanditArm.COMPREHENSIVE and entropy > 0.65:
            return 0.5
        if arm == MemoryBanditArm.MINIMAL and confidence > 0.8:
            return 0.4
        return 0.0

    def log_summary(self) -> str:
        lines = ["[memory_bandit] stats:"]
        for arm, s in self._stats.items():
            lines.append(
                f"  {arm.value}: count={s.count} mean={s.mean_reward:.3f}"
            )
        return "\n".join(lines)
