"""
LAAP — 记忆激活值计算器 (ACT-R 基础)

基于 ACT-R (Adaptive Control of Thought-Rational) 认知架构理论，
实现记忆条目的激活值计算。激活值决定记忆的检索优先级与遗忘时机。

公式：
    BLA(i) = ln( Σ_k t_k^(-d) )          # 基础层激活 (Base-Level Activation)
    A(i)   = BLA(i) + I(i) + E(i)        # 总激活 = 基础激活 + 重要性 + 情绪调制

其中：
    t_k  : 第 k 次访问距当前的时间（天数）
    d    : 衰减常数（默认 0.5，人类记忆典型值）
    I(i) : 重要性权重（归一化后 0~1）
    E(i) : 情绪效价调制（|valence| 越高记忆越牢固）

参考：Anderson, J. R. (2007). How Can the Human Mind Occur in the Physical Universe?

与 MemoryBear 的差异：我们不只计算"强度"，还结合 LAAP 的
emotional_valence 与 importance 双通道，且激活值只用于排序与降级，
永不触发物理删除。
"""

from __future__ import annotations

import math
import time
from typing import List, Optional


class ActivationCalculator:
    """ACT-R 记忆激活值计算器。

    参数：
        decay_constant: 幂律衰减常数 d（默认 0.5）
        importance_weight: 重要性在总激活中的权重（默认 0.35）
        emotion_weight: 情绪在总激活中的权重（默认 0.15）
        base_weight: 基础激活的权重（默认 0.5）
    """

    def __init__(
        self,
        decay_constant: float = 0.5,
        importance_weight: float = 0.35,
        emotion_weight: float = 0.15,
        base_weight: float = 0.5,
    ) -> None:
        self.decay_constant = decay_constant
        self.importance_weight = importance_weight
        self.emotion_weight = emotion_weight
        self.base_weight = base_weight

    def base_level_activation(
        self,
        access_times: List[float],
        now: Optional[float] = None,
    ) -> float:
        """计算基础层激活（幂律和，饱和压缩到 0~1）。

        经典 ACT-R 的 BLA = ln(Σ t_k^(-d)) 在单次访问且时间久远时为负，
        工程上我们改用饱和压缩：
            B(i) = 1 - exp(-Σ t_k^(-d))
        保证：新近/高频访问 → 接近 1；久远/低频 → 接近 0。

        access_times: 历次访问的 unix 时间戳列表（含创建时刻）。
        """
        now = now or time.time()
        if not access_times:
            return 0.0
        total = 0.0
        for t in access_times:
            delta_days = max((now - t) / 86400.0, 0.0001)
            total += delta_days ** (-self.decay_constant)
        return 1.0 - math.exp(-total)

    def emotion_modulation(self, valence: float) -> float:
        """情绪调制：|valence| 越强，记忆越牢固（正负情绪都增强）。

        返回 0~1 的调制系数。
        """
        return min(1.0, abs(valence))

    def activation(
        self,
        access_times: List[float],
        importance: float = 0.5,
        valence: float = 0.0,
        now: Optional[float] = None,
    ) -> float:
        """综合激活值 A = base_weight·BLA + importance_weight·I + emotion_weight·E。

        归一化到 0~1 区间（sigmoid 压缩），便于阈值比较。
        """
        bla = self.base_level_activation(access_times, now)
        # 已饱和压缩到 0~1，无需额外变换
        bla_norm = bla
        emo = self.emotion_modulation(valence)
        raw = (
            self.base_weight * bla_norm
            + self.importance_weight * max(0.0, min(1.0, importance))
            + self.emotion_weight * emo
        )
        # sigmoid 平滑，中心点 0.5
        return 1.0 / (1.0 + math.exp(-8.0 * (raw - 0.5)))


class ForgettingCurve:
    """艾宾浩斯遗忘曲线（用于补充激活值的回忆概率估计）。"""

    def __init__(self, decay_days: float = 7.0) -> None:
        self.decay_days = decay_days

    def recall_probability(self, age_days: float) -> float:
        """回忆概率 = e^(-age/decay_days)。"""
        return math.exp(-age_days / self.decay_days)
