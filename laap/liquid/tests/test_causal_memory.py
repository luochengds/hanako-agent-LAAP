"""LAAP Liquid — Task 11 (因果反事实模拟器) + Task 13 (记忆场) 测试

测试内容：
  1. test_counterfactual_bounded        — 反事实轨迹有界性
  2. test_counterfactual_trajectory_length — 轨迹点数量
  3. test_counterfactual_decode         — encode/decode 往返还原
  4. test_memory_observe_predict        — observe 后 predict 返回结构
  5. test_memory_confidence_grows       — 连续 observe 后置信度增长

运行：
    cd d:\\LAAP && python -m pytest laap/liquid/tests/test_causal_memory.py -v
"""

from __future__ import annotations

import time

import numpy as np
import pytest

from laap.liquid.causal_simulator import LiquidCausalSimulator
from laap.liquid.memory_field import LiquidMemoryField


# ════════════════════════════════════════════════════════════════════
# Task 11: LiquidCausalSimulator 测试
# ════════════════════════════════════════════════════════════════════

def test_counterfactual_bounded():
    """反事实轨迹有界性：所有轨迹点 ||h|| <= 2 * ||h_initial||。

    使用一个范数足够大的 world_state（||h0|| ≈ 6.24），
    使得 LTC 稳态范数（<= sqrt(state_dim)*tau_sys = 8）小于 2*||h0||，
    从而保证轨迹单调收敛，有界性成立。
    """
    sim = LiquidCausalSimulator(state_dim=16, action_dim=8)
    world_state = {
        "temperature": 5.0,
        "pressure": 3.0,
        "volume": 2.0,
        "energy": 1.0,
    }
    intervention = {"action": "heat", "magnitude": 0.5}

    traj = sim.counterfactual(world_state, intervention, horizon=10.0, dt=0.1)

    assert len(traj) > 0, "[ERROR] 轨迹不应为空"

    initial_norm = traj[0]["norm"]
    bound = 2.0 * initial_norm
    max_norm = max(p["norm"] for p in traj)

    # 有界性：每个点的范数 <= 2 * 初始范数
    for i, p in enumerate(traj):
        assert p["norm"] <= bound + 1e-9, (
            f"[ERROR] 步 {i} (t={p['t']:.2f}): ||h||={p['norm']:.4f} > "
            f"2*||h_init||={bound:.4f}"
        )

    # is_bounded 也应返回 True
    assert sim.is_bounded(traj), (
        f"[ERROR] is_bounded 应返回 True（max||h||={max_norm:.4f}, "
        f"bound={bound:.4f}）"
    )

    print(
        f"[OK] test_counterfactual_bounded 通过："
        f"||h_init||={initial_norm:.4f}, max||h||={max_norm:.4f}, "
        f"bound={bound:.4f}, 步数={len(traj)}"
    )


def test_counterfactual_trajectory_length():
    """轨迹长度：horizon=10, dt=0.1 → 约 100 个轨迹点（含 t=0 和 t=horizon）。"""
    sim = LiquidCausalSimulator(state_dim=16, action_dim=8)
    world_state = {"x": 1.0, "y": 2.0}
    intervention = {"force": 0.3}

    traj = sim.counterfactual(world_state, intervention, horizon=10.0, dt=0.1)

    # int(10/0.1) + 1 = 101 个点（t=0, 0.1, ..., 10.0）
    assert 95 <= len(traj) <= 110, (
        f"[ERROR] 轨迹点数应为约 100，实际 {len(traj)}"
    )

    # 验证时间戳正确
    assert traj[0]["t"] == pytest.approx(0.0, abs=1e-9), (
        f"[ERROR] 第一个点 t 应为 0，实际 {traj[0]['t']}"
    )
    assert traj[-1]["t"] == pytest.approx(10.0, abs=1e-6), (
        f"[ERROR] 最后一个点 t 应为 10.0，实际 {traj[-1]['t']}"
    )

    # 时间步长应一致
    dts = [traj[i + 1]["t"] - traj[i]["t"] for i in range(len(traj) - 1)]
    assert all(abs(d - 0.1) < 1e-9 for d in dts), (
        f"[ERROR] 时间步长应全为 0.1"
    )

    print(f"[OK] test_counterfactual_trajectory_length 通过：{len(traj)} 个轨迹点")


def test_counterfactual_decode():
    """encode_state → decode_state 应近似还原原始 world_state 的关键字段。

    数值字段应精确还原（因为 encode 直接存值，decode 直接读值）；
    字符串字段通过缓存也应精确还原。
    """
    sim = LiquidCausalSimulator(state_dim=16, action_dim=8)
    world_state = {
        "temperature": 25.5,
        "pressure": 1.0,
        "volume": 3.14,
        "is_container": True,
        "state": "liquid",
    }

    h = sim.encode_state(world_state)
    decoded = sim.decode_state(h)

    # 数值字段应精确还原
    assert "temperature" in decoded, "[ERROR] 解码结果应包含 temperature"
    assert "pressure" in decoded, "[ERROR] 解码结果应包含 pressure"
    assert "volume" in decoded, "[ERROR] 解码结果应包含 volume"

    assert decoded["temperature"] == pytest.approx(25.5, abs=1e-9), (
        f"[ERROR] temperature 还原失败：期望 25.5，实际 {decoded['temperature']}"
    )
    assert decoded["pressure"] == pytest.approx(1.0, abs=1e-9), (
        f"[ERROR] pressure 还原失败：期望 1.0，实际 {decoded['pressure']}"
    )
    assert decoded["volume"] == pytest.approx(3.14, abs=1e-9), (
        f"[ERROR] volume 还原失败：期望 3.14，实际 {decoded['volume']}"
    )

    # 布尔字段转 1.0/0.0，还原为 float
    assert decoded["is_container"] == pytest.approx(1.0, abs=1e-9), (
        f"[ERROR] is_container 还原失败：期望 1.0，实际 {decoded['is_container']}"
    )

    # 字符串字段通过缓存还原
    assert decoded.get("state") == "liquid", (
        f"[ERROR] state 还原失败：期望 'liquid'，实际 {decoded.get('state')}"
    )

    print(f"[OK] test_counterfactual_decode 通过：decoded={decoded}")


# ════════════════════════════════════════════════════════════════════
# Task 13: LiquidMemoryField 测试
# ════════════════════════════════════════════════════════════════════

def test_memory_observe_predict():
    """observe 5 次正弦值后 predict(steps=3)：
    - predicted_values 长度应为 3
    - confidence 应在 [0, 1]
    - hidden_norm 应为非负实数
    """
    field = LiquidMemoryField(input_dim=8, hidden_dim=16)

    # 用 time.time() 作为基准，确保 dt > 0
    base_t = time.time()
    for i in range(5):
        x = np.full(8, np.sin(i * 0.3) * 0.5, dtype=np.float64)
        field.observe(x, t_now=base_t + i * 0.1)

    result = field.predict(steps=3, dt=0.1)

    # 结构检查
    assert "predicted_values" in result, "[ERROR] predict 结果应包含 predicted_values"
    assert "confidence" in result, "[ERROR] predict 结果应包含 confidence"
    assert "hidden_norm" in result, "[ERROR] predict 结果应包含 hidden_norm"

    # predicted_values 长度检查
    predicted = result["predicted_values"]
    assert len(predicted) == 3, (
        f"[ERROR] predicted_values 长度应为 3，实际 {len(predicted)}"
    )

    # 每个预测值应为 input_dim 维 numpy 数组
    for i, p in enumerate(predicted):
        assert isinstance(p, np.ndarray), (
            f"[ERROR] predicted_values[{i}] 应为 np.ndarray，实际 {type(p)}"
        )
        assert p.shape == (8,), (
            f"[ERROR] predicted_values[{i}] 形状应为 (8,)，实际 {p.shape}"
        )

    # confidence 应在 [0, 1]
    conf = result["confidence"]
    assert 0.0 <= conf <= 1.0, (
        f"[ERROR] confidence 应在 [0,1]，实际 {conf}"
    )

    # hidden_norm 应为非负实数
    hn = result["hidden_norm"]
    assert isinstance(hn, float) and hn >= 0.0, (
        f"[ERROR] hidden_norm 应为非负 float，实际 {hn}"
    )

    print(
        f"[OK] test_memory_observe_predict 通过："
        f"3 个预测值，confidence={conf:.4f}, hidden_norm={hn:.4f}"
    )


def test_memory_confidence_grows():
    """连续 observe 多次后，confidence 应高于初始值。

    初始 h = 0 → confidence = sigmoid(0) = 0.5。
    经过多次带非零输入的 observe（dt > 0），隐藏态累积信息，
    ||h|| > 0 → confidence > 0.5。
    """
    field = LiquidMemoryField(input_dim=8, hidden_dim=16)

    initial_conf = field.get_confidence()
    assert initial_conf == pytest.approx(0.5, abs=1e-6), (
        f"[ERROR] 初始置信度应为 sigmoid(0)=0.5，实际 {initial_conf}"
    )

    # 连续 observe 多次，用显式递增 t_now 确保 dt > 0
    base_t = time.time()
    for i in range(20):
        x = np.array(
            [np.sin(i * 0.2 + j * 0.5) * 0.7 for j in range(8)],
            dtype=np.float64,
        )
        field.observe(x, t_now=base_t + i * 0.1)

    final_conf = field.get_confidence()
    summary = field.get_h_summary()

    assert final_conf > initial_conf, (
        f"[ERROR] 连续 observe 后置信度应增长："
        f"initial={initial_conf}, final={final_conf}, "
        f"h_norm={summary['h_norm']:.4f}, history_len={summary['history_len']}"
    )

    # 隐藏态范数应大于 0
    assert summary["h_norm"] > 0.0, (
        f"[ERROR] observe 后 ||h|| 应 > 0，实际 {summary['h_norm']}"
    )

    # history 应记录了 20 次观察
    assert summary["history_len"] == 20, (
        f"[ERROR] history_len 应为 20，实际 {summary['history_len']}"
    )

    print(
        f"[OK] test_memory_confidence_grows 通过："
        f"initial={initial_conf:.4f} → final={final_conf:.4f}, "
        f"||h||={summary['h_norm']:.4f}"
    )
