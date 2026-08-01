"""液态情感场 + 液态注意力选择器 测试"""

import math
import time

import numpy as np
import pytest

from laap.liquid.affective_field import LiquidAffectiveField
from laap.liquid.attention_selector import LiquidAttentionSelector


# ════════════════════════════════════════════════════════════════════
# LiquidAffectiveField 测试
# ════════════════════════════════════════════════════════════════════


class TestLiquidAffectiveField:
    def test_affective_half_life(self):
        """强情绪事件后，在 τ_base×ln(2) 时间后情感值衰减到约一半。"""
        field = LiquidAffectiveField()
        t0 = 1000.0  # 用固定时间戳避免 time.time() 抖动

        # 触发 joy 维度强情绪事件（给足 dt 让 LTC 演化产生峰值）
        field.last_t = t0
        field.process_emotion_event(
            {"dimension": "joy", "intensity": 0.9, "valence": 1.0},
            t_now=t0 + 0.1,  # dt=0.1 足够让情感涌现
        )
        state_after_event = field.decode_affective_state()
        joy_peak = state_after_event["joy"]
        assert abs(joy_peak) > 1e-3, f"情感峰值过低: {joy_peak}，事件未生效"

        # 在 τ_base × ln(2) 时间后演化（自然衰减）
        tau_base = field.get_tau_base("joy")  # 1/2.5 = 0.4
        half_life = tau_base * math.log(2)  # ≈ 0.277s
        field.evolve_idle(t_now=t0 + 0.1 + half_life)
        state_after_decay = field.decode_affective_state()
        joy_decayed = state_after_decay["joy"]

        # 验证半衰期：指数衰减后应约为峰值的一半（允许 ±20% 误差）
        ratio = abs(joy_decayed) / max(abs(joy_peak), 1e-10)
        assert 0.3 <= ratio <= 0.7, (
            f"joy 半衰期不符: peak={joy_peak}, decayed={joy_decayed}, "
            f"ratio={ratio:.3f}，期望 ≈ 0.5"
        )

    def test_personality_mapping(self):
        """验证人格敏感度到 τ_base 的映射。"""
        field = LiquidAffectiveField()
        # joy 敏感度 2.5 → tau_base = 1/2.5 = 0.4
        assert abs(field.get_tau_base("joy") - 0.4) < 0.01, (
            f"joy tau_base 应为 0.4，实际 {field.get_tau_base('joy')}"
        )
        # fear 敏感度 1.5 → tau_base = 1/1.5 ≈ 0.667
        assert abs(field.get_tau_base("fear") - (1.0 / 1.5)) < 0.01, (
            f"fear tau_base 应为 {1.0/1.5:.3f}，实际 {field.get_tau_base('fear')}"
        )

    def test_affective_decode_range(self):
        """decode_affective_state 返回 5 个值都在 [-1, 1]。"""
        field = LiquidAffectiveField()
        # 触发多个维度事件
        for dim in ["joy", "trust", "fear", "surprise", "sadness"]:
            field.process_emotion_event(
                {"dimension": dim, "intensity": 0.8, "valence": 0.5},
                t_now=time.time(),
            )
        state = field.decode_affective_state()
        assert len(state) == 5, f"应返回 5 个维度，实际 {len(state)}"
        for name, val in state.items():
            assert -1.0 <= val <= 1.0, f"{name}={val} 超出 [-1,1]"

    def test_affective_summary(self):
        """get_h_summary 返回正确的摘要结构。"""
        field = LiquidAffectiveField()
        field.process_emotion_event(
            {"dimension": "joy", "intensity": 0.7, "valence": 1.0},
            t_now=time.time(),
        )
        summary = field.get_h_summary()
        assert "h_norm" in summary
        assert "taus" in summary
        assert "dimensions" in summary
        assert summary["dimensions"] == 5
        assert summary["h_norm"] >= 0.0


# ════════════════════════════════════════════════════════════════════
# LiquidAttentionSelector 测试
# ════════════════════════════════════════════════════════════════════


class TestLiquidAttentionSelector:
    def test_attention_select(self):
        """select_focus 返回合法焦点名称且分布和为 1。"""
        selector = LiquidAttentionSelector()
        focus, dist = selector.select_focus(
            {"user_input": 0.9, "task_goal": 0.3, "novelty": 0.5, "urgency": 0.4},
            t_now=time.time(),
        )
        assert focus in selector.focus_names, f"焦点 {focus} 不在列表中"
        assert len(dist) == 8, f"分布维度应为 8，实际 {len(dist)}"
        assert abs(sum(dist) - 1.0) < 0.01, f"分布和应为 1.0，实际 {sum(dist)}"

    def test_attention_continuous_transition(self):
        """连续两次 select_focus 用渐变 salience，分布平滑变化无突变。"""
        selector = LiquidAttentionSelector()
        t0 = time.time()

        # 第一次：强烈偏向 user
        focus1, dist1 = selector.select_focus(
            {"user_input": 0.9, "task_goal": 0.1, "novelty": 0.2, "urgency": 0.1},
            t_now=t0,
        )

        # 第二次：渐变到 user/task 均衡
        focus2, dist2 = selector.select_focus(
            {"user_input": 0.5, "task_goal": 0.5, "novelty": 0.3, "urgency": 0.2},
            t_now=t0 + 0.1,
        )

        # KL 散度衡量变化幅度
        kl = float(np.sum(dist1 * np.log(dist1 / (dist2 + 1e-10) + 1e-10)))
        assert kl < 1.0, (
            f"注意力分布突变: KL={kl:.3f}，应 < 1.0（平滑过渡）"
        )

    def test_attention_explain(self):
        """explain_focus 返回 top_neuron_id 在 [0,3] 范围。"""
        selector = LiquidAttentionSelector()
        selector.select_focus(
            {"user_input": 0.8, "task_goal": 0.2},
            t_now=time.time(),
        )
        explain = selector.explain_focus()
        assert "top_neuron_id" in explain
        assert "weight" in explain
        assert "command_activations" in explain
        assert 0 <= explain["top_neuron_id"] <= 3, (
            f"top_neuron_id 应在 [0,3]，实际 {explain['top_neuron_id']}"
        )
        assert len(explain["command_activations"]) == 4, (
            f"应有 4 个命令神经元激活值，实际 {len(explain['command_activations'])}"
        )

    def test_attention_distribution_all_positive(self):
        """注意力分布所有分量非负。"""
        selector = LiquidAttentionSelector()
        _, dist = selector.select_focus(
            {"user_input": 0.7, "task_goal": 0.6, "novelty": 0.4},
            t_now=time.time(),
        )
        assert np.all(dist >= 0.0), f"分布有负值: {dist}"

    def test_attention_summary(self):
        """get_h_summary 返回正确结构。"""
        selector = LiquidAttentionSelector()
        selector.select_focus({"user_input": 0.8}, t_now=time.time())
        summary = selector.get_h_summary()
        assert "h_norm" in summary
        assert "h_dim" in summary
        assert "top_focus" in summary
        assert summary["h_dim"] == 19
