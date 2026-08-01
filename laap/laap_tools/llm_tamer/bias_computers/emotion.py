"""
EmotionBiasComputer — 情感调节偏置

根据 CognitiveBus 的情感状态，调节 LLM 输出的情感色彩：
  - POSITIVE_HIGH  → 提高热情/积极词汇概率
  - NEGATIVE_HIGH  → 降低负面词汇概率，提高温和词汇
  - CURIOUS        → 提高探索性词汇概率
  - CONFUSED       → 提高询问/确认词汇概率
  - NEUTRAL        → 无偏置
"""

from __future__ import annotations

from typing import Dict

from laap.agi.cognitive_bus import (
    CognitiveStateSnapshot,
    EmotionalValence,
)


class EmotionBiasComputer:
    """从情感状态计算 logit_bias 字典。"""

    def __init__(self, bias_strength: float = 0.7):
        """
        Args:
            bias_strength: 全局强度系数（默认 0.7，情感调节应弱于注意力引导）
        """
        self.bias_strength = bias_strength
        self._token_groups: Dict[str, Dict[int, str]] = {}

    def load_token_groups(self, token_groups: Dict[str, Dict[int, str]]) -> None:
        """从配置加载 token 映射。"""
        self._token_groups = token_groups

    def compute(self, state: CognitiveStateSnapshot) -> Dict[int, float]:
        """
        根据认知状态计算情感偏置。

        Args:
            state: 当前的 CognitiveStateSnapshot

        Returns:
            {token_id: bias_value} 字典
        """
        bias: Dict[int, float] = {}
        valence = state.emotion.valence
        arousal = state.emotion.arousal

        # 情感强度随 arousal 变化
        intensity_mod = 0.5 + arousal * 0.5  # 0.5 ~ 1.0

        if valence == EmotionalValence.POSITIVE_HIGH:
            # 提高积极词汇概率
            self._apply_bias("positive_tokens",
                             3.0 * intensity_mod, bias)
            # 抑制负面词汇
            self._apply_bias("negative_tokens",
                             -4.0 * intensity_mod, bias)

        elif valence == EmotionalValence.POSITIVE_MILD:
            # 轻度提高积极词汇
            self._apply_bias("positive_tokens", 1.5 * intensity_mod, bias)

        elif valence == EmotionalValence.NEGATIVE_HIGH:
            # 强烈抑制负面词汇（防止模型强化负面）,
            self._apply_bias("negative_tokens",
                             -5.0 * intensity_mod, bias)
            # 同时提高温和/积极词汇（引导情绪回升）
            self._apply_bias("positive_tokens", 2.0 * intensity_mod, bias)

        elif valence == EmotionalValence.NEGATIVE_MILD:
            # 轻度抑制负面词汇
            self._apply_bias("negative_tokens",
                             -2.0 * intensity_mod, bias)

        elif valence == EmotionalValence.CURIOUS:
            # 提高探索性词汇
            self._apply_bias("exploratory_tokens",
                             4.0 * intensity_mod, bias)
            # 提高问句概率
            self._apply_bias("question_tokens",
                             2.0 * intensity_mod, bias)

        elif valence == EmotionalValence.CONFUSED:
            # 提高询问/确认词汇
            self._apply_bias("question_tokens",
                             3.0 * intensity_mod, bias)
            self._apply_bias("confirm_tokens",
                             2.5 * intensity_mod, bias)

        # NEUTRAL: 不施加情感偏置

        return bias

    def _apply_bias(self, group_key: str, base_strength: float,
                    bias: Dict[int, float]) -> None:
        """辅助方法：对 token 组施加统一偏置。"""
        tokens = self._token_groups.get(group_key, {})
        scaled = round(base_strength * self.bias_strength, 1)
        for tid in tokens:
            bias[tid] = bias.get(tid, 0.0) + scaled


def default_emotion_bias(state: CognitiveStateSnapshot,
                         token_groups: Dict[str, Dict[int, str]],
                         bias_strength: float = 0.7) -> Dict[int, float]:
    """便捷函数：一步计算情感偏置。"""
    computer = EmotionBiasComputer(bias_strength=bias_strength)
    computer.load_token_groups(token_groups)
    return computer.compute(state)
