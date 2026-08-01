"""LAAP Liquid — LiquidCognitiveCore + LiquidBusField 测试套件

测试内容：
  1. test_liquid_core_available   : LiquidCognitiveCore.is_available() 返回 True
  2. test_core_register_evolve    : 注册 LiquidBusField，调用 evolve_all，验证返回摘要含 h_norm
  3. test_bus_field_evolve        : LiquidBusField.evolve 在不规则 dt [0.3, 1.8, 3.6] 上不报错，h 有界
  4. test_decode_needs_range      : decode_needs 返回的 5 个值都在 [0, 1] 范围内
  5. test_frequency_mismatch       : 1000Hz 事件流（1000 次 evolve, dt=0.001）+ 1 次 decode，验证合理

运行：
    cd d:\\LAAP && python -m pytest laap/liquid/tests/test_core_bus.py -v
"""

from __future__ import annotations

import time

import numpy as np
import pytest

from laap.liquid.core import LiquidCognitiveCore
from laap.liquid.bus_bridge import LiquidBusField


# ════════════════════════════════════════════════════════════════════
# 1. LiquidCognitiveCore 可用性测试
# ════════════════════════════════════════════════════════════════════

def test_liquid_core_available():
    """LiquidCognitiveCore.is_available() 在 numpy 可用时返回 True。"""
    core = LiquidCognitiveCore()
    assert core.is_available() is True, "[ERROR] numpy 可用但 is_available() 返回 False"
    print("[OK] LiquidCognitiveCore.is_available() == True")


# ════════════════════════════════════════════════════════════════════
# 2. 注册 + evolve_all 测试
# ════════════════════════════════════════════════════════════════════

def test_core_register_evolve():
    """注册一个 LiquidBusField，调用 evolve_all，验证返回摘要含 h_norm。"""
    core = LiquidCognitiveCore()
    field = LiquidBusField(state_dim=32, seed=42)
    core.register_field("bus_field", field)

    # 确认注册成功
    assert "bus_field" in core.list_fields()

    # 推进一点时间，确保 dt > 0
    t_now = field.last_t + 0.1
    summaries = core.evolve_all(t_now)

    # 返回应包含 bus_field 子场
    assert "bus_field" in summaries, f"[ERROR] 摘要缺失 bus_field 键：{summaries}"
    bus_summary = summaries["bus_field"]
    # 摘要应含 h_norm 字段
    assert "h_norm" in bus_summary, f"[ERROR] 摘要缺失 h_norm 字段：{bus_summary}"
    # h_norm 应为有限实数
    h_norm = bus_summary["h_norm"]
    assert isinstance(h_norm, float), f"[ERROR] h_norm 应为 float，实际 {type(h_norm)}"
    assert not np.isnan(h_norm), f"[ERROR] h_norm 为 NaN"
    assert h_norm >= 0.0, f"[ERROR] h_norm 应非负，实际 {h_norm}"

    # h_dim 应为 32
    assert bus_summary.get("h_dim") == 32, f"[ERROR] h_dim 应为 32，实际 {bus_summary.get('h_dim')}"
    # tau 应为正实数
    tau = bus_summary.get("tau")
    assert tau is not None and tau > 0.0, f"[ERROR] tau 应为正实数，实际 {tau}"

    print(f"[OK] 注册 + evolve_all 测试通过，bus_field 摘要：{bus_summary}")


# ════════════════════════════════════════════════════════════════════
# 3. 不规则 dt 演化测试
# ════════════════════════════════════════════════════════════════════

def test_bus_field_evolve():
    """LiquidBusField.evolve 在不规则 dt [0.3, 1.8, 3.6] 上不报错，h 保持有界。

    CfC 闭合式解对任意正 dt 都不发散：|new_h| <= max(|h|, 1)。
    """
    field = LiquidBusField(state_dim=32, seed=7)
    inputs = field.encode_inputs(
        need_deltas={"competence": 0.1, "certainty": -0.05},
        emotion_signals=np.array([0.2, -0.1, 0.0, 0.3, -0.2]),
    )

    irregular_dts = [0.3, 1.8, 3.6]
    t_now = field.last_t
    h = field.h.copy()
    for dt in irregular_dts:
        t_now += dt
        h = field.evolve(inputs, t_now)
        assert not np.any(np.isnan(h)), f"[ERROR] dt={dt} 产生 NaN: h={h}"
        assert np.all(np.abs(h) <= 1e3), (
            f"[ERROR] dt={dt} |h| 超过 1e3: max|h|={np.max(np.abs(h))}"
        )

    # 再追加几步极端 dt 验证持续稳定
    for extra_dt in [0.01, 5.0, 0.7, 2.2, 50.0]:
        t_now += extra_dt
        h = field.evolve(inputs, t_now)
        assert not np.any(np.isnan(h)), f"[ERROR] dt={extra_dt} 产生 NaN"
        assert np.all(np.abs(h) <= 1e3), f"[ERROR] dt={extra_dt} |h| 超过 1e3"

    print(
        f"[OK] 不规则 dt 演化测试通过，最终 max|h|={np.max(np.abs(h)):.6f}, "
        f"h_norm={np.linalg.norm(h):.6f}"
    )


# ════════════════════════════════════════════════════════════════════
# 4. 需求解码值域测试
# ════════════════════════════════════════════════════════════════════

def test_decode_needs_range():
    """decode_needs 返回的 5 个值都在 [0, 1] 范围内。

    即使 h 的前 5 维有较大波动，sigmoid 也会将输出压到 (0, 1)。
    """
    field = LiquidBusField(state_dim=32, seed=11)
    # 注入若干输入并演化，使 h 非零
    inputs = field.encode_inputs(
        need_deltas={"competence": 0.5, "autonomy": -0.3, "growth": 0.4},
        emotion_signals=np.array([0.5, -0.5, 0.3, -0.2, 0.1]),
    )
    t_now = field.last_t
    for _ in range(20):
        t_now += 0.1
        field.evolve(inputs, t_now)

    needs = field.decode_needs()
    assert isinstance(needs, dict), f"[ERROR] decode_needs 应返回 dict，实际 {type(needs)}"
    expected_keys = {"competence", "autonomy", "relatedness", "certainty", "growth"}
    assert set(needs.keys()) == expected_keys, (
        f"[ERROR] 需求键集合不符：期望 {expected_keys}，实际 {set(needs.keys())}"
    )

    for key, val in needs.items():
        assert isinstance(val, float), f"[ERROR] {key} 应为 float，实际 {type(val)}"
        assert not np.isnan(val), f"[ERROR] {key} 为 NaN"
        assert 0.0 <= val <= 1.0, (
            f"[ERROR] {key} 超出 [0,1] 范围：val={val}"
        )

    print(f"[OK] 需求解码值域测试通过，needs={needs}")


# ════════════════════════════════════════════════════════════════════
# 5. 频率失配测试（1000Hz 事件流）
# ════════════════════════════════════════════════════════════════════

def test_frequency_mismatch():
    """模拟 1000Hz 事件流（1000 次 evolve, dt=0.001），然后 1 次 decode。

    验证：
      - 演化过程无 NaN / 无穷
      - 最终 h 有界
      - decode_needs 返回的 5 个值非 NaN 且在 [0, 1] 范围

    CfC 的闭合式解在 dt=0.001 时单步变化极小（r=σ(-W_tau*0.001)≈0.5），
    但累积 1000 步后 h 会进入稳态，不应数值爆炸。
    """
    field = LiquidBusField(state_dim=32, seed=99)
    # 使用非零输入驱动 h 演化
    inputs = field.encode_inputs(
        need_deltas={
            "competence": 0.2,
            "autonomy": 0.1,
            "relatedness": -0.1,
            "certainty": 0.05,
            "growth": 0.15,
        },
        emotion_signals=np.array([0.3, 0.1, -0.1, 0.2, 0.0]),
    )

    dt = 0.001  # 1000Hz
    t_now = field.last_t
    h = field.h.copy()
    for i in range(1000):
        t_now += dt
        h = field.evolve(inputs, t_now)
        # 周期性断言（避免每步都断言拖慢测试）
        if (i + 1) % 200 == 0:
            assert not np.any(np.isnan(h)), f"[ERROR] 第 {i+1} 步产生 NaN"
            assert np.all(np.abs(h) <= 1e3), (
                f"[ERROR] 第 {i+1} 步 |h| 超过 1e3: max|h|={np.max(np.abs(h))}"
            )

    # 最终一次 decode
    needs = field.decode_needs()
    expected_keys = {"competence", "autonomy", "relatedness", "certainty", "growth"}
    assert set(needs.keys()) == expected_keys, (
        f"[ERROR] 需求键集合不符：期望 {expected_keys}，实际 {set(needs.keys())}"
    )

    for key, val in needs.items():
        assert not np.isnan(val), f"[ERROR] 1000Hz 后 {key} 为 NaN"
        assert 0.0 <= val <= 1.0, (
            f"[ERROR] 1000Hz 后 {key} 超出 [0,1]：val={val}"
        )

    # tau 仍应为正
    tau = field.get_tau()
    assert tau > 0.0 and not np.isnan(tau), f"[ERROR] 1000Hz 后 tau 异常：{tau}"

    print(
        f"[OK] 频率失配测试通过，1000 步 dt=0.001 后 "
        f"h_norm={np.linalg.norm(h):.6f}, tau={tau:.4f}, needs={needs}"
    )


# ════════════════════════════════════════════════════════════════════
# 入口：直接 python 运行
# ════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    test_liquid_core_available()
    test_core_register_evolve()
    test_bus_field_evolve()
    test_decode_needs_range()
    test_frequency_mismatch()
    print("\n[OK] 所有测试通过")
