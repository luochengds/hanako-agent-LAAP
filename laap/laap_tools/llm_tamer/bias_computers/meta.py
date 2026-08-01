"""
MetaBiasComputer — 元认知偏置

在特定场景下强制自省 token 序列出现。

触发条件：
  - 预测误差大（prediction_error > 0.3）
  - 自我存在感低（self_presence < 0.2）
  - curiosity 高且 certainty 低 → 需要反思
  - 注意力在 SELF 模式
"""

from __future__ import annotations

from typing import Dict

from laap.agi.cognitive_bus import (
    AttentionFocus,
    CognitiveStateSnapshot,
)


class MetaBiasComputer:
    """元认知偏置计算器——在需要时促进自省行为。"""

    def __init__(self, bias_strength: float = 0.8):
        """
        Args:
            bias_strength: 全局强度系数（默认 0.8）
        """
        self.bias_strength = bias_strength
        self._token_groups: Dict[str, Dict[int, str]] = {}

    def load_token_groups(self, token_groups: Dict[str, Dict[int, str]]) -> None:
        """从配置加载 token 映射。"""
        self._token_groups = token_groups

    def compute(self, state: CognitiveStateSnapshot) -> Dict[int, float]:
        """
        根据认知状态计算元认知偏置。

        Args:
            state: 当前的 CognitiveStateSnapshot

        Returns:
            {token_id: bias_value} 字典
        """
        bias: Dict[int, float] = {}
        meta_need_score = 0.0
        reasons: list[str] = []

        # 1. 预测误差驱动力
        if state.prediction_error is not None:
            pe = state.prediction_error.error_magnitude
            if pe > 0.3:
                delta = min(1.0, (pe - 0.3) / 0.7)  # 0~1 scale
                meta_need_score += delta * 0.4
                reasons.append(f"prediction_error={pe:.2f}")

        # 2. 自我存在感低 + 高预测误差 = 不确定自我状态
        if state.self_presence < 0.25:
            deficit = 0.25 - state.self_presence
            meta_need_score += deficit * 0.3
            reasons.append(f"low_self_presence={state.self_presence:.2f}")

        # 3. 高 curiosity + 低 certainty = 探索/反思需求
        if state.curiosity > 0.6 and state.needs.certainty < 0.4:
            delta = min(1.0, (state.curiosity - 0.6) / 0.4)
            deficit = (0.4 - state.needs.certainty) / 0.4
            meta_need_score += delta * deficit * 0.3
            reasons.append("curious+uncertain")

        # 4. 注意力在 SELF 模式 → 已经在内省，顺势强化
        if state.attention.focus == AttentionFocus.SELF:
            meta_need_score += 0.3
            reasons.append("self_focus")

        # 应用偏置
        if meta_need_score > 0.2:
            strength = meta_need_score * 4.0 * self.bias_strength
            # 提高自省 token 概率
            self._apply_bias("introspection_tokens", strength, bias)
            # 同时提高 self_analysis token（联想、反思类）
            self._apply_bias("self_analysis_tokens", strength * 0.6, bias)

        return bias

    def _apply_bias(self, group_key: str, strength: float,
                    bias: Dict[int, float]) -> None:
        """辅助方法：对 token 组施加统一偏置。"""
        tokens = self._token_groups.get(group_key, {})
        scaled = round(strength, 1)
        for tid in tokens:
            bias[tid] = bias.get(tid, 0.0) + scaled


def default_meta_bias(state: CognitiveStateSnapshot,
                      token_groups: Dict[str, Dict[int, str]],
                      bias_strength: float = 0.8) -> Dict[int, float]:
    """便捷函数：一步计算元认知偏置。"""
    computer = MetaBiasComputer(bias_strength=bias_strength)
    computer.load_token_groups(token_groups)
    return computer.compute(state)
