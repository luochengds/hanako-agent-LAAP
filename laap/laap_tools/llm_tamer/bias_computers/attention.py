"""
AttentionBiasComputer — 注意力引导偏置

根据 CognitiveBus 的注意力状态，调整 LLM 输出方向：
  - 注意力在 USER  → 提高问句/回答 token 的概率
  - 注意力在 SELF  → 提高自我分析 token 的概率
  - 注意力涣散     → 提高话题重启 token 的概率
  - 注意力在 TASK  → 提高任务相关 token 的概率
"""

from __future__ import annotations

from typing import Dict, List

from laap.agi.cognitive_bus import (
    AttentionFocus,
    CognitiveStateSnapshot,
)


class AttentionBiasComputer:
    """从注意力状态计算 logit_bias 字典。"""

    # 不同注意力焦点对应的 token 组名（与 config.yaml 中 token_mappings 的键对应）
    FOCUS_TOKEN_MAP: Dict[AttentionFocus, str] = {
        AttentionFocus.USER: "question_tokens",
        AttentionFocus.SELF: "self_analysis_tokens",
        AttentionFocus.TASK: "question_tokens",  # 任务模式也用问句 token 细化
        AttentionFocus.MEMORY: "self_analysis_tokens",
        AttentionFocus.PLANNING: "question_tokens",
        AttentionFocus.LEARNING: "exploratory_tokens",
        AttentionFocus.ENVIRONMENT: "question_tokens",
        AttentionFocus.IDLE: "refocus_tokens",
    }

    def __init__(self, bias_strength: float = 1.0):
        """
        Args:
            bias_strength: 全局强度系数（默认从 config.yaml 读取）
        """
        self.bias_strength = bias_strength
        # 从 config.yaml 加载的 token 映射
        self._token_groups: Dict[str, Dict[int, str]] = {}

    def load_token_groups(self, token_groups: Dict[str, Dict[int, str]]) -> None:
        """从配置加载 token 映射。"""
        self._token_groups = token_groups

    def compute(self, state: CognitiveStateSnapshot) -> Dict[int, float]:
        """
        根据认知状态计算注意力偏置。

        Args:
            state: 当前的 CognitiveStateSnapshot

        Returns:
            {token_id: bias_value} 字典
        """
        bias: Dict[int, float] = {}
        focus = state.attention.focus
        intensity = state.attention.intensity

        # 1. 注意力焦点引导
        token_group_key = self.FOCUS_TOKEN_MAP.get(focus)
        if token_group_key and token_group_key in self._token_groups:
            tokens = self._token_groups[token_group_key]
            # 偏置强度与注意力强度成正比
            focus_strength = self.bias_strength * intensity * 3.0
            for tid in tokens:
                bias[tid] = round(focus_strength, 1)

        # 2. 注意力涣散 → 提高话题重启 token 概率
        if intensity < 0.3:
            refocus_key = "refocus_tokens"
            if refocus_key in self._token_groups:
                tokens = self._token_groups[refocus_key]
                # 越低 attention 强度，越需要温和引导
                boost = self.bias_strength * (0.3 - intensity) * 5.0
                for tid in tokens:
                    bias[tid] = bias.get(tid, 0.0) + round(boost, 1)

        # 3. 注意力高度集中 → 维持当前方向（抑制分散 token）
        if intensity > 0.85:
            # 轻度抑制其他焦点的 token
            for other_focus, other_key in self.FOCUS_TOKEN_MAP.items():
                if other_focus != focus and other_key in self._token_groups:
                    inhibitors = self._token_groups[other_key]
                    for tid in inhibitors:
                        current = bias.get(tid, 0.0)
                        # 只给正值没被覆盖的 token 轻微抑制（~exp(-1) ≈ 37% 概率抑制）
                        if tid not in bias:
                            bias[tid] = round(-self.bias_strength * 1.0, 1)

        return bias


def default_attention_bias(state: CognitiveStateSnapshot,
                           token_groups: Dict[str, Dict[int, str]],
                           bias_strength: float = 1.0) -> Dict[int, float]:
    """便捷函数：一步计算注意力偏置。"""
    computer = AttentionBiasComputer(bias_strength=bias_strength)
    computer.load_token_groups(token_groups)
    return computer.compute(state)
