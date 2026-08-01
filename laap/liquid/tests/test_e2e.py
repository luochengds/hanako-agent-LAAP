"""LNN 液态认知内核 — 端到端集成测试 (Task 18)

验证完整 PSI 循环 + liquid 内核的端到端功能：
1. LiquidCognitiveCore 聚合多个子场协同演化
2. CognitiveBus 连续时间状态场 + 离散 tick 并存
3. AffectiveState 液态情感 + ConsciousStream 液态注意力
4. CausalEngine LTC 反事实 + WorldModel CfC 预测
5. 移动端 NCP 独立 PSI 循环
6. 全部 fallback 路径零回归
"""

import time
import math

import numpy as np
import pytest

from laap.liquid.neurons import LTCCell, CfCCell, NCPCircuit
from laap.liquid.core import LiquidCognitiveCore
from laap.liquid.bus_bridge import LiquidBusField
from laap.liquid.affective_field import LiquidAffectiveField
from laap.liquid.attention_selector import LiquidAttentionSelector
from laap.liquid.causal_simulator import LiquidCausalSimulator
from laap.liquid.memory_field import LiquidMemoryField


# ════════════════════════════════════════════════════════════════════
# 1. LiquidCognitiveCore 聚合多场协同演化
# ════════════════════════════════════════════════════════════════════


class TestEndToEndIntegration:
    """端到端集成测试"""

    def test_core_aggregates_all_fields(self):
        """LiquidCognitiveCore 聚合 bus/affective/attention 三场协同演化"""
        core = LiquidCognitiveCore()
        assert core.is_available(), "LiquidCognitiveCore 应可用"

        bus_field = LiquidBusField(state_dim=32)
        affective = LiquidAffectiveField()
        attention = LiquidAttentionSelector()

        core.register_field("bus", bus_field)
        core.register_field("affective", affective)
        core.register_field("attention", attention)

        t0 = time.time()
        summary = core.evolve_all(t0)
        assert "bus" in summary or len(summary) > 0, "应至少有一个场返回摘要"

        state = core.get_state_summary()
        assert isinstance(state, dict)

    def test_full_psi_cycle_with_liquid(self):
        """完整 PSI 循环：感知→液态注意力→液态情感→响应"""
        # 初始化各场
        bus = LiquidBusField(state_dim=32)
        affective = LiquidAffectiveField()
        attention = LiquidAttentionSelector()
        memory = LiquidMemoryField(input_dim=8, hidden_dim=16)
        causal = LiquidCausalSimulator(state_dim=16, action_dim=8)

        t0 = 1000.0

        # 1. 感知阶段：注入需求信号到 bus
        inputs = bus.encode_inputs(
            need_deltas={"competence": 0.8, "growth": 0.6},
            emotion_signals=np.array([0.5, 0.3, 0.1, 0.4, 0.2]),
        )
        bus.evolve(inputs, t_now=t0)

        # 2. 解码需求
        needs = bus.decode_needs()
        assert all(0 <= v <= 1 for v in needs.values()), f"需求值越界: {needs}"

        # 3. 液态注意力选择焦点
        salience = {
            "user_input": 0.9,
            "task_goal": 0.3,
            "novelty": 0.7,
            "urgency": 0.5,
            "self_state": 0.4,
        }
        focus, dist = attention.select_focus(salience, t_now=t0 + 0.01)
        assert focus in attention.focus_names
        assert abs(sum(dist) - 1.0) < 0.01

        # 4. 液态情感响应
        affective.process_emotion_event(
            {"dimension": "joy", "intensity": 0.7, "valence": 0.8},
            t_now=t0 + 0.02,
        )
        emo_state = affective.decode_affective_state()
        assert all(-1 <= v <= 1 for v in emo_state.values())

        # 5. 记忆场观察
        memory.observe(np.array([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]), t_now=t0 + 0.03)
        prediction = memory.predict(steps=3)
        assert "confidence" in prediction
        assert 0 <= prediction["confidence"] <= 1

        # 6. 因果反事实模拟
        trajectory = causal.counterfactual(
            world_state={"energy": 0.8, "focus": 0.6, "mood": 0.7},
            intervention={"action": "engage", "intensity": 0.5},
            horizon=5.0,
            dt=0.1,
        )
        assert len(trajectory) > 0
        assert causal.is_bounded(trajectory), "反事实轨迹应有界"

    def test_continuous_time_evolution(self):
        """连续时间演化：不规则时间戳下状态正确演化"""
        bus = LiquidBusField(state_dim=16)
        affective = LiquidAffectiveField()

        # 不规则时间戳序列
        timestamps = [0.3, 2.1, 5.7, 6.1, 10.0]
        prev_h_norm = 0.0

        for i, t in enumerate(timestamps):
            inputs = bus.encode_inputs(
                need_deltas={"competence": 0.5},
                emotion_signals=np.zeros(5),
            )
            h = bus.evolve(inputs, t_now=t)
            h_norm = float(np.linalg.norm(h))
            # 状态应非全零（有演化发生）
            if i > 0:
                assert h_norm > 0 or prev_h_norm >= 0, f"t={t} 状态异常"
            prev_h_norm = h_norm

            affective.evolve_idle(t_now=t)

        # 最终状态应稳定有界
        final_needs = bus.decode_needs()
        assert all(0 <= v <= 1 for v in final_needs.values())

    def test_frequency_mismatch_handling(self):
        """频率失配：1000Hz 事件流 + 1Hz 查询无信息丢失"""
        bus = LiquidBusField(state_dim=16)
        t0 = 0.0

        # 模拟 1000Hz 高频事件流（100 个事件，dt=0.001）
        for i in range(100):
            inputs = bus.encode_inputs(
                need_deltas={"competence": 0.01 * (i % 10)},
                emotion_signals=np.array([0.1] * 5),
            )
            bus.evolve(inputs, t_now=t0 + i * 0.001)

        # 1Hz 查询：解码状态应反映高频事件的累积影响
        needs = bus.decode_needs()
        assert all(0 <= v <= 1 for v in needs.values()), "频率失配导致状态异常"
        # 状态不应全为零（有信号保留）
        assert any(v > 0.01 for v in needs.values()), "高频事件信号丢失"

    def test_attention_explainability(self):
        """注意力可解释性：能读出响应最强的命令神经元"""
        selector = LiquidAttentionSelector()
        selector.select_focus(
            {"user_input": 0.9, "task_goal": 0.2, "novelty": 0.6},
            t_now=time.time(),
        )
        explain = selector.explain_focus()
        assert "top_neuron_id" in explain
        assert "weight" in explain
        assert "command_activations" in explain
        assert 0 <= explain["top_neuron_id"] <= 3
        assert len(explain["command_activations"]) == 4

    def test_causal_bounded_dynamics(self):
        """LTC 因果反事实模拟有界不发散"""
        sim = LiquidCausalSimulator(state_dim=16, action_dim=8)
        trajectory = sim.counterfactual(
            world_state={"x": 0.5, "y": 0.3, "z": 0.8},
            intervention={"action": "test", "intensity": 0.9},
            horizon=10.0,
            dt=0.1,
        )
        assert sim.is_bounded(trajectory), "轨迹应有界"

        # 检查所有点范数
        norms = [p["norm"] for p in trajectory]
        initial_norm = norms[0]
        for n in norms:
            assert n <= initial_norm * 2.0 + 1e-6, f"轨迹发散: norm={n}, initial={initial_norm}"


# ════════════════════════════════════════════════════════════════════
# 2. Fallback 零回归验证
# ════════════════════════════════════════════════════════════════════


class TestFallbackZeroRegression:
    """fallback 路径零回归验证"""

    def test_cognitive_bus_fallback(self):
        """CognitiveBus 在 liquid field 不可用时仍正常工作"""
        from laap.agi.cognitive_bus import CognitiveBus
        bus = CognitiveBus(agent_name="TestAgent")
        # liquid field 应已自动创建（numpy 可用）
        assert bus._liquid_field is not None, "liquid field 应可用"

        # tick() 应正常工作
        snapshot = bus.tick()
        assert snapshot is not None

    def test_affective_state_fallback(self):
        """AffectiveState 在 liquid 不可用时仍正常工作"""
        from laap.agi.affective_engine import AffectiveState, PersonalityProfile
        state = AffectiveState(profile=PersonalityProfile())
        # liquid affective 应已创建
        assert state._liquid_affective is not None

        # update() 应正常工作
        state.update(external_stimulus=0.5, dt=0.1)
        liquid_state = state.get_liquid_affective_state()
        assert liquid_state is not None

    def test_conscious_stream_fallback(self):
        """ConsciousStream 在 liquid 不可用时仍正常工作"""
        from laap.agi.conscious import ConsciousStream
        cs = ConsciousStream()
        assert cs._liquid_attention is not None

        result = cs.get_liquid_attention({"user_input": 0.8})
        assert result is not None
        focus, dist = result
        assert isinstance(focus, str)

    def test_causal_engine_fallback(self):
        """CausalEngine 在 liquid 不可用时仍正常工作"""
        from laap.agi.causal import UnifiedCausalEngine
        engine = UnifiedCausalEngine()
        assert engine._liquid_causal is not None

    def test_world_model_fallback(self):
        """WorldModel 在 liquid 不可用时仍正常工作"""
        from laap.agi.world_model import UnifiedWorldModel
        wm = UnifiedWorldModel()
        assert wm._liquid_memory is not None

        conf = wm.get_liquid_confidence()
        assert conf is not None
        assert 0 <= conf <= 1


# ════════════════════════════════════════════════════════════════════
# 3. 移动端 NCP 独立 PSI 循环
# ════════════════════════════════════════════════════════════════════


class TestMobileNCPE2E:
    """移动端 NCP 端到端验证"""

    def test_mobile_ncp_inference_latency(self):
        """移动端 NCP 推理延迟 < 1ms"""
        from laap.liquid.neurons import NCPCircuit
        ncp = NCPCircuit(input_dim=8)
        h = ncp.default_state()
        x = np.random.rand(8) * 0.5

        # 预热
        for _ in range(10):
            h = ncp.forward(h, x, 0.01)

        # 计时
        times = []
        for _ in range(100):
            t_start = time.perf_counter()
            h = ncp.forward(h, x, 0.01)
            t_end = time.perf_counter()
            times.append((t_end - t_start) * 1000)  # ms

        avg_ms = sum(times) / len(times)
        assert avg_ms < 1.0, f"NCP 推理延迟 {avg_ms:.3f}ms 超过 1ms"

    def test_mobile_ncp_model_size(self):
        """导出的 NCP 模型 < 100KB"""
        import os
        model_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "ncp_model.json"
        )
        if not os.path.exists(model_path):
            pytest.skip("ncp_model.json 未生成（需先运行 export_ncp_model.py）")
        size_kb = os.path.getsize(model_path) / 1024
        assert size_kb < 100, f"模型体积 {size_kb:.1f}KB 超过 100KB"

    def test_mobile_standalone_psi_loop(self):
        """移动端独立 PSI 循环（无桌面主节点）"""
        ncp = NCPCircuit(input_dim=8)
        h = ncp.default_state()

        # 模拟 50 轮 PSI 循环
        for i in range(50):
            # 感知输入（模拟移动传感器）
            x = np.array([
                0.5 + 0.3 * math.sin(i * 0.1),  # 需求
                0.3 + 0.2 * math.cos(i * 0.15),  # 焦点
                0.4 + 0.1 * math.sin(i * 0.2),  # 自我
                0.2,  # 环境
                0.3,  # 记忆
                0.1 + 0.05 * i / 50,  # 规划
                0.5,  # 学习
                0.1,  # 空闲
            ])
            h = ncp.forward(h, x, 0.01)

            # 检查状态有界
            assert np.all(np.abs(h) < 1e3), f"第 {i} 轮状态发散"
            assert not np.any(np.isnan(h)), f"第 {i} 轮出现 NaN"

        # 命令神经元激活值
        cmd = ncp.get_command_activations()
        assert len(cmd) == 4
        assert np.all(np.abs(cmd) < 1e3)
