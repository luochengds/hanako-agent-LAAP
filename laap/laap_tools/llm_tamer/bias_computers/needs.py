"""
NeedsBiasComputer — 需求驱动偏置

根据 CognitiveBus 的 PSI 五需求状态，驱动 LLM 输出方向：
  - competence 不足（< 0.3） → 提高谦虚/求助词汇概率
  - certainty 不足（< 0.3） → 提高询问/确认词汇概率
  - growth 不足（< 0.3）    → 提高学习/探索词汇概率
  - relatedness 不足（< 0.3）→ 提高社交/连接词汇概率
"""

from __future__ import annotations

from typing import Dict

from laap.agi.cognitive_bus import CognitiveStateSnapshot


class NeedsBiasComputer:
    """从 PSI 需求状态计算 logit_bias 字典。"""

    # 触发偏置的需求阈值（低于此值表示不足）
    NEED_THRESHOLD: float = 0.3

    def __init__(self, bias_strength: float = 0.5):
        """
        Args:
            bias_strength: 全局强度系数（默认 0.5，需求驱动属于间接调节）
        """
        self.bias_strength = bias_strength
        self._token_groups: Dict[str, Dict[int, str]] = {}

    def load_token_groups(self, token_groups: Dict[str, Dict[int, str]]) -> None:
        """从配置加载 token 映射。"""
        self._token_groups = token_groups

    def compute(self, state: CognitiveStateSnapshot) -> Dict[int, float]:
        """
        根据认知状态计算需求驱动偏置。

        Args:
            state: 当前的 CognitiveStateSnapshot

        Returns:
            {token_id: bias_value} 字典
        """
        bias: Dict[int, float] = {}
        needs = state.needs

        # 1. competence 不足 → 谦虚/求助
        if needs.competence < self.NEED_THRESHOLD:
            deficit = self.NEED_THRESHOLD - needs.competence
            strength = deficit * 5.0 * self.bias_strength
            self._apply_bias("humble_tokens", strength, bias)
            # 问题 token 也有帮助
            self._apply_bias("question_tokens", strength * 0.5, bias)

        # 2. certainty 不足 → 询问/确认
        if needs.certainty < self.NEED_THRESHOLD:
            deficit = self.NEED_THRESHOLD - needs.certainty
            strength = deficit * 5.0 * self.bias_strength
            self._apply_bias("confirm_tokens", strength, bias)
            self._apply_bias("question_tokens", strength * 0.7, bias)

        # 3. growth 不足 → 学习/探索
        if needs.growth < self.NEED_THRESHOLD:
            deficit = self.NEED_THRESHOLD - needs.growth
            strength = deficit * 4.0 * self.bias_strength
            self._apply_bias("exploratory_tokens", strength, bias)

        # 4. relatedness 不足 → 社交/连接
        # （相关 token 需从模型 tokenizer 获取，这里用积极 token 近似）
        if needs.relatedness < self.NEED_THRESHOLD:
            deficit = self.NEED_THRESHOLD - needs.relatedness
            strength = deficit * 3.5 * self.bias_strength
            self._apply_bias("positive_tokens", strength, bias)

        # 5. autonomy 不足 → 轻微促进自述/决策 token
        # （自主性不足时鼓励模型表达自己的观点）
        if needs.autonomy < self.NEED_THRESHOLD:
            deficit = self.NEED_THRESHOLD - needs.autonomy
            strength = deficit * 3.0 * self.bias_strength
            self._apply_bias("self_analysis_tokens", strength, bias)

        return bias

    def _apply_bias(self, group_key: str, strength: float,
                    bias: Dict[int, float]) -> None:
        """辅助方法：对 token 组施加统一偏置。"""
        tokens = self._token_groups.get(group_key, {})
        scaled = round(strength, 1)
        for tid in tokens:
            bias[tid] = bias.get(tid, 0.0) + scaled


def default_needs_bias(state: CognitiveStateSnapshot,
                       token_groups: Dict[str, Dict[int, str]],
                       bias_strength: float = 0.5) -> Dict[int, float]:
    """便捷函数：一步计算需求偏置。"""
    computer = NeedsBiasComputer(bias_strength=bias_strength)
    computer.load_token_groups(token_groups)
    return computer.compute(state)
