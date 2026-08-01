"""
LAAP — 记忆生命周期状态机

三阶段记忆生命周期：
    ACTIVE   → 激活值高，正常参与检索（默认）
    DORMANT  → 激活值低，检索时降权；等待强化或进一步降级
    ARCHIVED → 激活值极低，从常规检索隐藏；仅显式追溯可及

设计原则（与 MemoryBear 的本质差异）：
    他们：识别 → 融合 → 删除（MemorySummary 替换原始节点）
    我们：识别 → 降级 → 归档（永不物理删除，保证记忆完整性）

归档不是遗忘的终点，而是记忆的"冬眠"。只要被重新激活
（访问/关联强化），记忆可以从任意阶段苏醒回升。
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, Any


class MemoryLifecycle(str, Enum):
    ACTIVE = "active"
    DORMANT = "dormant"
    ARCHIVED = "archived"


class LifecycleTransition:
    """生命周期状态机：定义合法的状态迁移。"""

    _ALLOWED = {
        MemoryLifecycle.ACTIVE: {MemoryLifecycle.DORMANT, MemoryLifecycle.ARCHIVED},
        MemoryLifecycle.DORMANT: {MemoryLifecycle.ACTIVE, MemoryLifecycle.ARCHIVED},
        MemoryLifecycle.ARCHIVED: {MemoryLifecycle.ACTIVE},  # 归档可苏醒，不可再降
    }

    @classmethod
    def can_transition(cls, src: MemoryLifecycle, dst: MemoryLifecycle) -> bool:
        return dst in cls._ALLOWED.get(src, set())

    @classmethod
    def transition(cls, current: MemoryLifecycle, target: MemoryLifecycle) -> MemoryLifecycle:
        """执行迁移；非法迁移保持原状态并返回当前状态。"""
        if cls.can_transition(current, target):
            return target
        return current


class LifecyclePolicy:
    """生命周期阈值策略（激活值 0~1）。

    - active_threshold: 低于此值进入 DORMANT
    - dormant_threshold: 低于此值进入 ARCHIVED
    - revive_threshold: 高于此值（经强化后）从 DORMANT/ARCHIVED 回到 ACTIVE
    """

    def __init__(
        self,
        active_threshold: float = 0.45,
        dormant_threshold: float = 0.15,
        revive_threshold: float = 0.55,
        min_age_days: float = 3.0,   # 记忆太新不参与遗忘（保护近期记忆）
    ) -> None:
        self.active_threshold = active_threshold
        self.dormant_threshold = dormant_threshold
        self.revive_threshold = revive_threshold
        self.min_age_days = min_age_days

    def decide(self, activation: float, age_days: float) -> Dict[str, Any]:
        """根据激活值与年龄决定目标生命周期。

        返回 {target, reason}：
        - 太新的记忆保持现状（记忆巩固窗口期）
        - 高激活 → ACTIVE
        - 中激活 → DORMANT
        - 低激活 → ARCHIVED
        """
        if age_days < self.min_age_days:
            return {"target": MemoryLifecycle.ACTIVE, "reason": "consolidation_window"}

        if activation >= self.revive_threshold:
            return {"target": MemoryLifecycle.ACTIVE, "reason": "revived"}
        if activation >= self.active_threshold:
            return {"target": MemoryLifecycle.ACTIVE, "reason": "sufficient"}
        if activation >= self.dormant_threshold:
            return {"target": MemoryLifecycle.DORMANT, "reason": "low_activation"}
        return {"target": MemoryLifecycle.ARCHIVED, "reason": "critically_low"}
