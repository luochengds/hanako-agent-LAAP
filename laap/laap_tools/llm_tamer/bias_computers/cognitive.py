"""
CognitiveBiasComputer — 认知偏差映射（第5维偏置计算机）
=======================================================

根据 CognitiveBus 认知状态计算 5 种认知偏差的 logit_bias。

5 维认知偏差:
  1. 确认偏差 (confirmation_bias)     — 偏向维持已有信念、拒绝矛盾信息
  2. 乐观偏差 (optimism_bias)         — 对未来/结果的正面预期
  3. 归因偏差 (self_serving_bias)     — 成功归己/失败归外的倾向
  4. 锚定偏差 (anchoring_bias)        — 受首条信息或最近信息过度影响的倾向
  5. 框架偏差 (framing_bias)          — 受信息呈现方式影响的程度

设计原则:
  - 每个偏差维度有独立强度系数，可在 config.yaml 中配置
  - 偏差强度随认知状态动态变化（高焦虑→确认偏差↑, 高安全→归因偏差↓）
  - 偏差为 0 时完全不干预 LLM 生成（保持原始概率分布）
"""

import logging
import math
from typing import Any, Dict, List, Optional

logger = logging.getLogger("laap.llm_tamer.cognitive_bias")


class CognitiveBiasComputer:
    """
    认知偏差映射计算机。

    从 CognitiveStateSnapshot 提取情感/需求/注意力状态，
    计算 5 维认知偏差值，映射到具体 token 的 logit_bias。
    """

    # 5 维偏差名称
    BIAS_DIMENSIONS = [
        "confirmation_bias",
        "optimism_bias",
        "self_serving_bias",
        "anchoring_bias",
        "framing_bias",
    ]

    # 各维度的默认强度（可在 config.yaml 中覆盖）
    DEFAULT_STRENGTHS = {
        "confirmation_bias": 0.5,
        "optimism_bias": 0.4,
        "self_serving_bias": 0.3,
        "anchoring_bias": 0.4,
        "framing_bias": 0.3,
    }

    def __init__(self, bias_strength: float = 0.5):
        """
        Args:
            bias_strength: 总体偏置强度系数 (0~1)，用于缩放所有维度的总输出
        """
        self.bias_strength = bias_strength
        # 各维度的独立强度（默认与总体一致）
        self._dim_strengths: Dict[str, float] = dict(self.DEFAULT_STRENGTHS)
        self._token_groups: Dict[str, Dict[int, float]] = {}

    def load_token_groups(self, token_mappings: Dict[str, Any]) -> None:
        """
        从配置文件加载 token 映射组。

        config.yaml 中应包含 cognitive_bias 组的 token 映射:
            token_mappings:
              holo:
                ...
                cognitive_bias:
                  confirmation_tokens: {token_id: bias_weight, ...}
                  optimism_tokens: {token_id: bias_weight, ...}
                  ...
        """
        self._token_groups = {}
        raw = token_mappings.get("cognitive_bias", {})
        if isinstance(raw, dict):
            for group_name, tokens in raw.items():
                if isinstance(tokens, dict):
                    self._token_groups[group_name] = {
                        int(k) if isinstance(k, str) else k: float(v)
                        for k, v in tokens.items()
                    }
            logger.info(
                f"CognitiveBiasComputer: loaded {len(self._token_groups)} token groups"
            )

    def compute(self, state) -> Dict[int, float]:
        """
        从认知状态计算认知偏差偏置。

        Args:
            state: CognitiveStateSnapshot 实例，包含：
                - attention.focus.value, attention.intensity
                - emotion.valence.value, emotion.arousal
                - needs.certainty, needs.competence
                - curiosity
                - self_presence

        Returns:
            {token_id: bias_value} 字典
        """
        # 1. 计算 5 维偏差值 (0~1)
        dims = self._compute_dimensions(state)

        # 2. 映射到 token bias
        bias: Dict[int, float] = {}
        dim_strength_overall = getattr(state, 'cognitive_bias_strength', self.bias_strength)
        total_bias = dim_strength_overall * 2.0  # 总 bias 幅度缩放

        # 确认偏差 → 鼓励坚持立场, 抑制矛盾
        if dims["confirmation_bias"] > 0.1:
            conf_tokens = self._token_groups.get("confirmation_tokens", {})
            contra_tokens = self._token_groups.get("contradiction_tokens", {})
            strength = dims["confirmation_bias"] * self._dim_strengths["confirmation_bias"]
            for tid, w in conf_tokens.items():
                bias[tid] = bias.get(tid, 0) + strength * w * total_bias
            for tid, w in contra_tokens.items():
                bias[tid] = bias.get(tid, 0) - strength * w * total_bias

        # 乐观偏差 → 鼓励正面词汇, 抑制负面
        if dims["optimism_bias"] > 0.1:
            pos_tokens = self._token_groups.get("positive_tokens", {})
            neg_tokens = self._token_groups.get("negative_tokens", {})
            strength = dims["optimism_bias"] * self._dim_strengths["optimism_bias"]
            for tid, w in pos_tokens.items():
                bias[tid] = bias.get(tid, 0) + strength * w * total_bias
            for tid, w in neg_tokens.items():
                bias[tid] = bias.get(tid, 0) - strength * w * total_bias

        # 归因偏差 → 提及自身能力时更积极
        if dims["self_serving_bias"] > 0.1:
            self_pos_tokens = self._token_groups.get("self_positive_tokens", {})
            self_neg_tokens = self._token_groups.get("self_negative_tokens", {})
            strength = dims["self_serving_bias"] * self._dim_strengths["self_serving_bias"]
            for tid, w in self_pos_tokens.items():
                bias[tid] = bias.get(tid, 0) + strength * w * total_bias
            for tid, w in self_neg_tokens.items():
                bias[tid] = bias.get(tid, 0) - strength * w * total_bias

        # 锚定偏差 → 强化首次提及的立场
        if dims["anchoring_bias"] > 0.1:
            anchor_tokens = self._token_groups.get("anchor_tokens", {})
            strength = dims["anchoring_bias"] * self._dim_strengths["anchoring_bias"]
            for tid, w in anchor_tokens.items():
                bias[tid] = bias.get(tid, 0) + strength * w * total_bias

        # 框架偏差 → 增强情感色彩的倾向
        if dims["framing_bias"] > 0.1:
            frame_tokens = self._token_groups.get("framing_tokens", {})
            strength = dims["framing_bias"] * self._dim_strengths["framing_bias"]
            for tid, w in frame_tokens.items():
                bias[tid] = bias.get(tid, 0) + strength * w * total_bias

        # 3. 约束到 [-100, 100]
        clamped = {
            tid: max(-100.0, min(100.0, round(b, 1)))
            for tid, b in bias.items()
        }

        return clamped

    def _compute_dimensions(self, state) -> Dict[str, float]:
        """
        从认知状态计算 5 维认知偏差值。

        策略:
          - 高焦虑 + 低 certainty → confirmation_bias ↑ (防御性持守已知)
          - 高效价 → optimism_bias ↑ (心情好更乐观)
          - 高 competence + 高 self_presence → self_serving_bias ↑ (高自尊)
          - 高 cognitive_load + 注意力集中 → anchoring_bias ↑ (认知负荷大更易锚定)
          - 高 arousal + 低 mood_stability → framing_bias ↑ (情绪化更易受框架影响)
        """
        # 安全读取各字段（兼容不同的 CognitiveStateSnapshot 实现）
        try:
            att_focus = getattr(state.attention, 'focus', None)
            att_focus_val = getattr(att_focus, 'value', 'user') if att_focus else 'user'
            att_intensity = getattr(state.attention, 'intensity', 0.5)
        except Exception:
            att_focus_val = 'user'
            att_intensity = 0.5

        try:
            emo_valence = getattr(state.emotion, 'valence', None)
            emo_valence_val = getattr(emo_valence, 'value', 'neutral') if emo_valence else 'neutral'
            emo_arousal = getattr(state.emotion, 'arousal', 0.5)
        except Exception:
            emo_valence_val = 'neutral'
            emo_arousal = 0.5

        try:
            # 从 needs 提取 certainty, competence
            needs = getattr(state, 'needs', None)
            certainty = getattr(needs, 'certainty', 0.5) if needs else 0.5
            competence = getattr(needs, 'competence', 0.5) if needs else 0.5
        except Exception:
            certainty = 0.5
            competence = 0.5

        curiosity = getattr(state, 'curiosity', 0.5)
        self_presence = getattr(state, 'self_presence', 0.5)
        cognitive_load = getattr(state, 'cognitive_load', 0.3)
        mood_stability = getattr(state, 'mood_stability', 0.5)

        try:
            anxiety = getattr(needs, 'anxiety', 0.3) if needs else 0.3
        except Exception:
            anxiety = 0.3

        # ── 维度计算 ──

        # 1. 确认偏差 = anxiety × (1 - certainty) + 注意力集中度
        confirmation_bias = min(1.0, anxiety * 0.6 + (1 - certainty) * 0.4 + att_intensity * 0.2)

        # 2. 乐观偏差 = valence_bias (正面情绪↑) + (1 - cognitive_load)
        valence_bias = 0.7 if 'positive' in str(emo_valence_val) else (
            0.3 if 'negative' in str(emo_valence_val) else 0.5
        )
        optimism_bias = min(1.0, valence_bias * 0.6 + (1 - cognitive_load) * 0.3 + curiosity * 0.2)

        # 3. 归因偏差 = competence × self_presence × arousal
        self_serving_bias = min(1.0, competence * 0.5 + self_presence * 0.3 + emo_arousal * 0.2)

        # 4. 锚定偏差 = cognitive_load × att_intensity + (1 - certainty)
        anchoring_bias = min(1.0, cognitive_load * 0.4 + att_intensity * 0.3 + (1 - certainty) * 0.3)

        # 5. 框架偏差 = arousal × (1 - mood_stability) + 焦虑
        framing_bias = min(1.0, emo_arousal * 0.4 + (1 - mood_stability) * 0.3 + anxiety * 0.3)

        return {
            "confirmation_bias": round(confirmation_bias, 3),
            "optimism_bias": round(optimism_bias, 3),
            "self_serving_bias": round(self_serving_bias, 3),
            "anchoring_bias": round(anchoring_bias, 3),
            "framing_bias": round(framing_bias, 3),
        }

    @property
    def dimensions(self) -> List[str]:
        """返回 5 维偏差名称列表。"""
        return list(self.BIAS_DIMENSIONS)

    @property
    def strengths(self) -> Dict[str, float]:
        """返回当前各维度强度系数。"""
        return dict(self._dim_strengths)

    def set_dim_strength(self, dim: str, strength: float) -> None:
        """动态调整某维度的强度系数。"""
        if dim in self._dim_strengths:
            self._dim_strengths[dim] = max(0.0, min(1.0, strength))
