"""
LAAP — 情绪梯度系统 (EG-MRSI)

情绪 = 需求满足率的微分信号，不是标签，而是指导 RSI 改进的方向。
基于 EG-MRSI (Ando 2025) 框架。
"""

from __future__ import annotations
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional
import numpy as np


@dataclass
class EmotionalState:
    valence: float = 0.0
    arousal: float = 0.5
    dominance: float = 0.5
    confidence: float = 0.5

    def to_dict(self) -> dict:
        return {
            "valence": round(self.valence, 3),
            "arousal": round(self.arousal, 3),
            "dominance": round(self.dominance, 3),
            "confidence": round(self.confidence, 3),
        }


class EmotionGradient:
    def __init__(self, alpha=1.0, beta=0.5, gamma=0.8, smoothing=0.3):
        self.alpha = alpha; self.beta = beta; self.gamma = gamma
        self.smoothing = smoothing
        self.state = EmotionalState()
        self._need_history: List[Dict[str, float]] = []
        self._reward_history: List[float] = []

    def update(self, satisfactions: Dict[str, float],
               task_success: Optional[float] = None,
               novelty: Optional[float] = None) -> EmotionalState:
        self._need_history.append(satisfactions)
        avg = np.mean(list(satisfactions.values()))
        v_target = np.clip(2.0 * avg - 1.0, -1.0, 1.0)
        self.state.valence = self._smooth(self.state.valence, v_target)

        if len(self._need_history) >= 2:
            prev = self._need_history[-2]; curr = self._need_history[-1]
            deltas = [curr[k] - prev.get(k, 0.5) for k in curr]
            drive = min(1.0, abs(np.mean(deltas)) * 3)
        else:
            drive = 0.3
        self.state.arousal = self._smooth(self.state.arousal, 0.3 + 0.7 * drive)

        if task_success is not None:
            self.state.dominance = self._smooth(self.state.dominance, 0.2 + 0.8 * task_success)
        if novelty is not None:
            self.state.confidence = self._smooth(self.state.confidence, np.clip(1.0 - novelty, 0, 1))
        return self.state

    def compute_intrinsic_reward(self) -> float:
        vd = 0.0
        if len(self._need_history) >= 2:
            vd = np.mean(list(self._need_history[-1].values())) - np.mean(list(self._need_history[-2].values()))
        r = np.clip(self.alpha * vd + self.beta * (1.0 - self.state.confidence) + self.gamma * self.state.arousal, -1.0, 1.0)
        self._reward_history.append(float(r))
        return float(r)

    @property
    def mean_reward(self, window=20) -> float:
        r = self._reward_history[-window:] if self._reward_history else [0.0]
        return float(np.mean(r))

    @property
    def reward_volatility(self, window=20) -> float:
        if len(self._reward_history) < window:
            return 0.0
        return float(np.std(self._reward_history[-window:]))

    def _smooth(self, old, new):
        return old * self.smoothing + new * (1.0 - self.smoothing)

    def reset(self):
        self.state = EmotionalState()
        self._need_history.clear(); self._reward_history.clear()

    def set_external_vad(self, valence: float, arousal: float, dominance: float,
                         source: str = "external", confidence: float = 0.5) -> EmotionalState:
        """Blend an external BCI-derived VAD estimate into the current emotional state.

        The ``source`` parameter is retained for provenance/auditing but does not
        affect the blend; ``confidence`` controls how strongly the external signal
        is incorporated (factor = confidence * 0.5).
        """
        blend = confidence * 0.5
        self.state.valence = float(np.clip(
            self.state.valence * (1.0 - blend) + valence * blend, -1.0, 1.0))
        self.state.arousal = float(np.clip(
            self.state.arousal * (1.0 - blend) + arousal * blend, 0.0, 1.0))
        self.state.dominance = float(np.clip(
            self.state.dominance * (1.0 - blend) + dominance * blend, 0.0, 1.0))
        return self.state


# ═══════════════════════════════════════════════════════════════
# PAD 情感系统 — 意识中间件层
# ═══════════════════════════════════════════════════════════════
"""情感系统 — 意识中间件层

基于 PAD（Pleasure-Arousal-Dominance）情感模型实现生命体的情感状态。
情感状态影响任务调度：高 arousal 时降低任务复杂度，避免过载。

References:
- Mehrabian, A. (1996). Pleasure-arousal-dominance: A general framework
  for describing and measuring individual differences in temperament.
- LAAP 2.1升级方案补充 § 意识中间件层
"""


class EmotionEventType(Enum):
    """情感事件类型"""
    TASK_SUCCESS = "task_success"  # 任务成功
    TASK_FAILURE = "task_failure"  # 任务失败
    THREAT_DETECTED = "threat_detected"  # 威胁检测
    REWARD_RECEIVED = "reward_received"  # 收到奖励
    PENALTY_RECEIVED = "penalty_received"  # 收到惩罚
    SOCIAL_POSITIVE = "social_positive"  # 正向社会交互
    SOCIAL_NEGATIVE = "social_negative"  # 负向社会交互
    NOVEL_STIMULUS = "novel_stimulus"  # 新奇刺激
    GOAL_BLOCKED = "goal_blocked"  # 目标受阻
    GOAL_PROGRESS = "goal_progress"  # 目标进展


# 情感事件对 PAD 三维度的影响权重
EVENT_PAD_IMPACT: Dict[EmotionEventType, tuple[float, float, float]] = {
    EmotionEventType.TASK_SUCCESS: (+0.3, -0.2, +0.2),
    EmotionEventType.TASK_FAILURE: (-0.3, +0.3, -0.2),
    EmotionEventType.THREAT_DETECTED: (-0.4, +0.5, -0.4),
    EmotionEventType.REWARD_RECEIVED: (+0.4, +0.2, +0.1),
    EmotionEventType.PENALTY_RECEIVED: (-0.4, +0.3, -0.2),
    EmotionEventType.SOCIAL_POSITIVE: (+0.2, +0.1, +0.1),
    EmotionEventType.SOCIAL_NEGATIVE: (-0.2, +0.2, -0.1),
    EmotionEventType.NOVEL_STIMULUS: (+0.1, +0.3, -0.1),
    EmotionEventType.GOAL_BLOCKED: (-0.3, +0.4, -0.3),
    EmotionEventType.GOAL_PROGRESS: (+0.2, -0.1, +0.1),
}


@dataclass
class EmotionState:
    """PAD 情感状态

    Attributes:
        valence: 愉悦度 [-1, 1]，正为愉悦，负为不悦
        arousal: 唤醒度 [-1, 1]，正为兴奋，负为平静
        dominance: 支配度 [-1, 1]，正为掌控，负为顺从
    """
    valence: float = 0.0
    arousal: float = 0.0
    dominance: float = 0.0
    last_update: float = field(default_factory=time.time)

    def clamp(self) -> "EmotionState":
        """将各维度截断到 [-1, 1] 区间"""
        self.valence = max(-1.0, min(1.0, self.valence))
        self.arousal = max(-1.0, min(1.0, self.arousal))
        self.dominance = max(-1.0, min(1.0, self.dominance))
        return self

    def to_dict(self) -> Dict[str, Any]:
        return {
            "valence": self.valence,
            "arousal": self.arousal,
            "dominance": self.dominance,
            "last_update": self.last_update,
        }


class EmotionSystem:
    """情感系统

    维护生命体的当前情感状态，根据事件更新情感，
    并提供情感对任务调度的影响判断。

    情感衰减：每秒 arousal 衰减 0.01（半衰期约 70 秒），
    valence 与 dominance 衰减 0.005/秒。
    """

    # 衰减率（每秒）
    AROUSAL_DECAY_PER_SEC = 0.01
    VALENCE_DECAY_PER_SEC = 0.005
    DOMINANCE_DECAY_PER_SEC = 0.005

    # 情感影响调度的阈值
    HIGH_AROUSAL_THRESHOLD = 0.7  # arousal > 0.7 时建议简化任务
    LOW_VALENCE_THRESHOLD = -0.5  # valence < -0.5 时建议暂停决策

    def __init__(self, initial_state: Optional[EmotionState] = None):
        self._state = initial_state or EmotionState()

    def update(self, event: EmotionEventType) -> EmotionState:
        """根据事件更新情感状态

        Args:
            event: 情感事件类型

        Returns:
            更新后的 EmotionState
        """
        # 先应用时间衰减
        self._apply_decay()
        # 应用事件影响
        impact = EVENT_PAD_IMPACT.get(event, (0.0, 0.0, 0.0))
        self._state.valence += impact[0]
        self._state.arousal += impact[1]
        self._state.dominance += impact[2]
        self._state.clamp()
        self._state.last_update = time.time()
        return self._state

    def current(self) -> EmotionState:
        """返回当前情感状态（先应用衰减）"""
        self._apply_decay()
        return self._state

    def should_simplify_task(self) -> bool:
        """高 arousal 时建议简化任务复杂度

        当 arousal > 0.7 时，生命体处于高唤醒状态（紧张/兴奋），
        复杂决策易出错，建议降低任务复杂度。

        Returns:
            True 表示应简化任务
        """
        return self.current().arousal > self.HIGH_AROUSAL_THRESHOLD

    def should_pause_decision(self) -> bool:
        """低 valence 时建议暂停重要决策

        当 valence < -0.5 时，生命体处于不悦状态，
        重要决策可能受负面情绪影响，建议暂停。

        Returns:
            True 表示应暂停决策
        """
        return self.current().valence < self.LOW_VALENCE_THRESHOLD

    def get_task_priority_modifier(self) -> float:
        """获取任务优先级调整因子

        高 arousal 提升紧迫感（优先级 +），
        低 dominance 降低自信（优先级 -）。

        Returns:
            优先级调整因子 [-0.3, +0.3]
        """
        state = self.current()
        modifier = 0.0
        # 高 arousal 增加紧迫感
        if state.arousal > 0:
            modifier += state.arousal * 0.2
        # 低 dominance 降低自信
        if state.dominance < 0:
            modifier += state.dominance * 0.1
        return max(-0.3, min(0.3, modifier))

    def _apply_decay(self) -> None:
        """应用时间衰减 — 各维度向中性值 0 衰减"""
        now = time.time()
        elapsed = now - self._state.last_update
        if elapsed <= 0:
            return
        # 衰减朝 0 方向收敛，避免中性状态被推离 0
        self._state.arousal = self._decay_toward_zero(
            self._state.arousal, self.AROUSAL_DECAY_PER_SEC * elapsed)
        self._state.valence = self._decay_toward_zero(
            self._state.valence, self.VALENCE_DECAY_PER_SEC * elapsed)
        self._state.dominance = self._decay_toward_zero(
            self._state.dominance, self.DOMINANCE_DECAY_PER_SEC * elapsed)
        self._state.clamp()
        self._state.last_update = now

    @staticmethod
    def _decay_toward_zero(value: float, amount: float) -> float:
        """将 value 朝 0 方向衰减 amount"""
        if value > 0:
            return max(0.0, value - amount)
        if value < 0:
            return min(0.0, value + amount)
        return value

    def reset(self) -> None:
        """重置为中性情感状态"""
        self._state = EmotionState()
