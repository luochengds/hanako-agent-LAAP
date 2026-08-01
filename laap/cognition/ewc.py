"""
LAAP — 弹性权重巩固 (Elastic Weight Consolidation) 权威实现

EWC 算法的单一权威来源 (Single Source of Truth)。
基于 Kirkpatrick et al. 2017，用于在线增量学习而不发生灾难性遗忘。

核心算法:
    L_total = L_new + λ * Σ F_i * (θ_i - θ_old_i)²

其中 F_i 是 Fisher 信息矩阵，衡量每个参数的重要性。
新任务学习时，重要参数被"锚定"在小变化范围内。

与现有架构集成：
  - Brain 的 PSI 需求参数是 EWC 的"权重"
  - Unity 的技能熟练度是 EWC 的"参数"
  - Cortex 的工具调用频率是 EWC 的"Fisher矩阵"

注意：
  本模块由 `laap.cognition.evolution` 迁移而来 (原 class ElasticWeightConsolidation)。
  `evolution.py` 现仅 re-export 本类以保持向后兼容。
  `laap_brain/__init__.py` 中的内联 EWC 代码为简化版，完整实现以本模块为准。
"""

from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger("laap.cognition.ewc")


class ElasticWeightConsolidation:
    """
    弹性权重巩固 (EWC) — 在线增量学习而不遗忘

    核心算法 (Kirkpatrick et al. 2017):
      L_total = L_new + λ * Σ F_i * (θ_i - θ_old_i)²

    其中 F_i 是 Fisher 信息矩阵，衡量每个参数的重要性。
    新任务学习时，重要参数被"锚定"在小变化范围内。

    与现有架构集成：
      - Brain 的 PSI 需求参数是 EWC 的"权重"
      - Unity 的技能熟练度是 EWC 的"参数"
      - Cortex 的工具调用频率是 EWC 的"Fisher矩阵"
    """

    def __init__(self, brain: Any, unity: Any, cortex: Any,
                 lambda_ewc: float = 0.5):
        self.brain = brain
        self.unity = unity
        self.cortex = cortex
        self.lambda_ewc = lambda_ewc        # EWC 正则化强度

        # Fisher 信息矩阵: 技能名 → 重要性权重
        self.fisher_matrix: Dict[str, float] = {}

        # 历史参数快照
        self.old_params: Dict[str, Any] = {}

        # 任务计数器
        self.task_count = 0
        self._importances: Dict[str, float] = {}

    def before_learning(self):
        """学习前：保存当前参数快照"""
        if hasattr(self.unity, 'skills'):
            self.old_params = {}
            for name, skill in self.unity.skills.items():
                self.old_params[name] = {
                    "proficiency": skill.proficiency.value,
                    "avg_quality": skill.avg_quality,
                    "success_rate": skill.success_rate,
                }
        self.task_count += 1

    def compute_fisher(self):
        """计算 Fisher 信息矩阵 — 衡量技能参数的重要性"""
        if not hasattr(self.unity, 'skills'):
            return

        for name, skill in self.unity.skills.items():
            # Fisher 信息 = 使用频率 × 成功率 × 熟练度
            freq = skill.use_count / max(1, self.task_count)
            success = skill.success_rate
            proficiency_weight = {
                "unknown": 0.0, "aware": 0.1, "novice": 0.3,
                "practitioner": 0.6, "expert": 0.8, "master": 1.0,
            }.get(skill.proficiency, 0.0)

            importance = freq * 0.3 + success * 0.3 + proficiency_weight * 0.4
            self.fisher_matrix[name] = importance
            self._importances[name] = importance

    def ewc_penalty(self, new_params: Dict[str, Any]) -> float:
        """
        计算 EWC 正则惩罚 — 防止灾难性遗忘

        L_ewc = λ * Σ F_i * (θ_i - θ_old_i)²
        """
        if not self.old_params:
            return 0.0

        penalty = 0.0
        for name, old in self.old_params.items():
            if name in new_params:
                new = new_params[name]
                fisher = self.fisher_matrix.get(name, 0.0)

                # 对每个参数计算平方差
                for key in old:
                    old_val = self._to_float(old[key])
                    new_val = self._to_float(new.get(key, old[key]))
                    diff_sq = (new_val - old_val) ** 2
                    penalty += fisher * diff_sq

        return self.lambda_ewc * penalty

    def after_learning(self, new_params: Dict[str, Any]) -> Dict[str, Any]:
        """
        学习后：EWC 约束下的参数更新

        新参数 = argmin(L_new + λ * EWC_penalty)
        """
        self.before_learning()
        self.compute_fisher()

        penalty = self.ewc_penalty(new_params)

        # 应用 EWC 约束：重要参数变化小，不重要参数可自由变化
        constrained = {}
        for name, new_val in new_params.items():
            fisher = self.fisher_matrix.get(name, 0.0)

            if fisher > 0.7:
                # 重要参数：大幅限制变化
                old_val = self.old_params.get(name, {}).get("avg_quality", 0.5)
                constrained[name] = old_val * 0.9 + new_val.get("avg_quality", 0.5) * 0.1
            elif fisher > 0.3:
                # 中等重要：中等限制
                old_val = self.old_params.get(name, {}).get("avg_quality", 0.5)
                constrained[name] = old_val * 0.5 + new_val.get("avg_quality", 0.5) * 0.5
            else:
                # 不重要：自由变化
                constrained[name] = new_val.get("avg_quality", 0.5)

        logger.info(
            f"EWC applied: task#{self.task_count}, "
            f"penalty={penalty:.4f}, "
            f"constrained={len(constrained)} params"
        )
        return {"constrained_params": constrained, "penalty": penalty}

    def _to_float(self, val: Any) -> float:
        if isinstance(val, (int, float)):
            return float(val)
        if isinstance(val, str):
            return float(len(val)) / 10.0
        return 0.0

    def status(self) -> dict:
        return {
            "task_count": self.task_count,
            "lambda": self.lambda_ewc,
            "fisher_params": len(self.fisher_matrix),
            "important_params": sum(1 for v in self.fisher_matrix.values() if v > 0.7),
        }
