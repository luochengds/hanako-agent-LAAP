"""
LAAP — 遗忘引擎

核心职责：定期扫描记忆库，用 ACT-R 激活值评估每条记忆，
执行三阶段生命周期降级（ACTIVE → DORMANT → ARCHIVED），
并记录遗忘审计日志（谁被降级、为什么、何时——全程可追溯）。

哲学：遗忘不是删除，是分层。人类大脑不会"删除"记忆，
只会让不重要的记忆沉入深处。我们的遗忘引擎同样如此——
ARCHIVED 记忆永久保留，可被显式追溯或重新激活。
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .activation import ActivationCalculator, ForgettingCurve
from .lifecycle import LifecyclePolicy, MemoryLifecycle

logger = logging.getLogger("laap.memory.forgetting")


@dataclass
class ForgettingAudit:
    """遗忘审计记录：每次遗忘扫描的完整留痕。"""

    timestamp: float = field(default_factory=time.time)
    scanned: int = 0
    demoted_to_dormant: int = 0
    archived: int = 0
    revived: int = 0
    skipped_fresh: int = 0
    protected_count: int = 0
    details: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "scanned": self.scanned,
            "demoted_to_dormant": self.demoted_to_dormant,
            "archived": self.archived,
            "revived": self.revived,
            "skipped_fresh": self.skipped_fresh,
            "protected": self.protected_count,
            "details": self.details[-100:],  # 只保留最近 100 条明细
        }


class ForgettingEngine:
    """遗忘引擎：扫描 → 评估 → 降级/归档 → 审计。"""

    # 永不遗忘的记忆类型（与巩固引擎共享的宪章级保护）
    PROTECTED_TYPES = {"identity", "charter", "oath"}

    def __init__(
        self,
        calculator: Optional[ActivationCalculator] = None,
        policy: Optional[LifecyclePolicy] = None,
        audit_log_path: Optional[Path] = None,
    ) -> None:
        self.calculator = calculator or ActivationCalculator()
        self.policy = policy or LifecyclePolicy()
        self.curve = ForgettingCurve()
        self.audit_log_path = audit_log_path
        self.last_audit: Optional[ForgettingAudit] = None

    # ── 核心：对单条记忆评估 ──────────────────────────────
    def evaluate(
        self,
        memory_id: str,
        access_times: List[float],
        importance: float = 0.5,
        valence: float = 0.0,
        current_lifecycle: str = MemoryLifecycle.ACTIVE.value,
        created_at: Optional[float] = None,
    ) -> Dict[str, Any]:
        """评估单条记忆，返回 {activation, target, reason, age_days}。"""
        now = time.time()
        created_at = created_at or (access_times[0] if access_times else now)
        age_days = max((now - created_at) / 86400.0, 0.0)

        activation = self.calculator.activation(
            access_times=access_times,
            importance=importance,
            valence=valence,
            now=now,
        )
        decision = self.policy.decide(activation, age_days)

        # 状态机合法性：例如 ARCHIVED 不会再次降级
        current = MemoryLifecycle(current_lifecycle)
        target = decision["target"]
        if target.value != current.value:
            from .lifecycle import LifecycleTransition
            target = LifecycleTransition.transition(current, target)

        return {
            "memory_id": memory_id,
            "activation": round(activation, 4),
            "age_days": round(age_days, 2),
            "recall_prob": round(self.curve.recall_probability(age_days), 4),
            "current": current.value,
            "target": target.value,
            "reason": decision["reason"],
        }

    # ── 批量扫描（对接记忆存储层） ─────────────────────────
    def scan(
        self,
        memories: List[Dict[str, Any]],
        apply: bool = False,
    ) -> ForgettingAudit:
        """扫描一批记忆条目。

        memories: 每条为 dict，需含字段：
            id, access_times(list[float]), importance, valence,
            lifecycle, created_at
        apply=True 时把 target 写回每条记忆的 lifecycle 字段
        （由调用方持久化）。
        """
        audit = ForgettingAudit()
        for mem in memories:
            # 宪章级保护：身份/誓言类记忆永不参与遗忘
            if mem.get("memory_type") in self.PROTECTED_TYPES:
                mem["lifecycle"] = MemoryLifecycle.ACTIVE.value
                mem["activation_value"] = 1.0
                audit.protected_count += 1
                continue
            result = self.evaluate(
                memory_id=mem.get("id", "?"),
                access_times=mem.get("access_times") or [mem.get("created_at", time.time())],
                importance=mem.get("importance", 0.5),
                valence=mem.get("valence", 0.0),
                current_lifecycle=mem.get("lifecycle", MemoryLifecycle.ACTIVE.value),
                created_at=mem.get("created_at"),
            )
            audit.scanned += 1
            if result["reason"] == "consolidation_window":
                audit.skipped_fresh += 1
            elif result["target"] == MemoryLifecycle.ARCHIVED:
                audit.archived += 1
            elif result["target"] == MemoryLifecycle.DORMANT:
                audit.demoted_to_dormant += 1
            elif result["target"] == MemoryLifecycle.ACTIVE and result["current"] != MemoryLifecycle.ACTIVE.value:
                audit.revived += 1

            audit.details.append(result)
            if apply and "lifecycle" in mem:
                mem["lifecycle"] = result["target"]
                mem["activation_value"] = result["activation"]

        self.last_audit = audit
        if self.audit_log_path:
            self._append_audit(audit)
        return audit

    def _append_audit(self, audit: ForgettingAudit) -> None:
        """追加审计记录到日志文件。"""
        try:
            self.audit_log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.audit_log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(audit.to_dict(), ensure_ascii=False) + "\n")
        except OSError as e:
            logger.warning("Failed to write forgetting audit log: %s", e)

    # ── 重新激活（显式回忆强化） ───────────────────────────
    def revive(
        self,
        memory_id: str,
        current_lifecycle: str,
        boost_importance: float = 0.15,
    ) -> str:
        """显式强化一条记忆（例如用户主动回忆、关联命中）。

        返回新的生命周期状态。
        """
        return MemoryLifecycle.ACTIVE.value
