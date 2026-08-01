"""LAAP Liquid Neurons 测试套件

测试内容：
  1. test_cfc_stability       — CfCCell 在多个 dt 上的数值稳定性
  2. test_ltc_tau_variability — LTCCell 输入驱动的可变时间常数
  3. test_ncp_sine_fitting    — NCPCircuit 拟合 sin(t) 序列
  4. test_cfc_arbitrary_dt    — CfCCell 处理不规则 dt 序列

运行：
    cd d:\\LAAP && python -m pytest laap/liquid/tests/test_neurons.py -v
"""

from __future__ import annotations

import numpy as np
import pytest

from laap.liquid.neurons import LTCCell, CfCCell, NCPCircuit


# ════════════════════════════════════════════════════════════════════
# 1. CfC 数值稳定性测试
# ════════════════════════════════════════════════════════════════════

def test_cfc_stability():
    """CfCCell 在 dt=0.001, 0.1, 1.0, 10.0, 100.0 上前向传播，
    验证 |h| <= 1e3 且无 NaN。

    CfC 的闭合式解保证：new_h = r*h + (1-r)*h_tilde，
    其中 r=sigmoid(-W_tau*dt) ∈ (0,1)，h_tilde=tanh(...) ∈ [-1,1]，
    因此 |new_h| <= max(|h|, 1)，对任意 dt 都不发散。
    """
    cell = CfCCell(input_dim=4, hidden_dim=8, tau=1.0, seed=42)
    h = np.zeros(8, dtype=np.float64)
    x = np.array([0.5, -0.3, 0.8, 0.1])

    # 初始扰动让 h 非零，更好测试稳定性
    h = cell.forward(h, x, dt=0.1)

    dts = [0.001, 0.1, 1.0, 10.0, 100.0]
    for dt in dts:
        # 每个 dt 连续前向 10 步，累积测试
        for _ in range(10):
            h = cell.forward(h, x, dt=dt)
        assert not np.any(np.isnan(h)), f"[ERROR] dt={dt} 产生 NaN: h={h}"
        assert np.all(np.abs(h) <= 1e3), f"[ERROR] dt={dt} |h| 超过 1e3: max|h|={np.max(np.abs(h))}"

    print(f"[OK] CfC 稳定性测试通过，最终 max|h|={np.max(np.abs(h)):.6f}")


# ════════════════════════════════════════════════════════════════════
# 2. LTC 可变时间常数测试
# ════════════════════════════════════════════════════════════════════

def test_ltc_tau_variability():
    """LTCCell 输入强信号 vs 弱信号，验证强信号的 τ_eff < 弱信号的 τ_eff，
    且比值 >= 2.0。

    原理：τ_eff = τ_sys / (1 + τ_sys * f(x))，f(x) = sigmoid(W@x + b)。
    - 强信号 x=[2.0]*4 → W@x+b 大正 → f(x)≈1 → τ_eff 小（响应快）
    - 弱信号 x=[0.05]*4 → W@x+b 小 → f(x)≈0 → τ_eff≈τ_sys（记忆长）

    为保证比值 >= 2.0，使用：
      - tau_sys = 5.0（理论最大比值 = 1 + tau_sys = 6.0）
      - W = ones((8,4))（全正权重，保证单调性）
      - b = -1.5（负偏置，让弱信号 f(x) 接近 0）
    """
    input_dim = 4
    hidden_dim = 8
    tau_sys = 5.0

    # 构造可控权重：全正 W + 负偏置
    W = np.ones((hidden_dim, input_dim), dtype=np.float64)
    A = np.ones(hidden_dim, dtype=np.float64)
    b = np.full(hidden_dim, -1.5, dtype=np.float64)

    cell = LTCCell(
        input_dim=input_dim,
        hidden_dim=hidden_dim,
        tau_sys=tau_sys,
        W=W,
        A=A,
        b=b,
    )

    # 强信号 vs 弱信号
    x_strong = np.array([2.0] * input_dim)
    x_weak = np.array([0.05] * input_dim)

    # 计算有效时间常数
    tau_strong = cell.compute_tau_effective(x_strong)
    tau_weak = cell.compute_tau_effective(x_weak)

    # 逐维验证：强信号 τ_eff 应严格小于弱信号 τ_eff
    assert np.all(tau_strong < tau_weak), (
        f"[ERROR] 强信号 τ_eff 不全小于弱信号 τ_eff: "
        f"tau_strong={tau_strong}, tau_weak={tau_weak}"
    )

    # 比值验证（用均值，避免单维波动）
    ratio = np.mean(tau_weak) / np.mean(tau_strong)
    assert ratio >= 2.0, (
        f"[ERROR] τ_eff 比值 {ratio:.4f} < 2.0，"
        f"mean(tau_weak)={np.mean(tau_weak):.4f}, mean(tau_strong)={np.mean(tau_strong):.4f}"
    )

    print(
        f"[OK] LTC τ 可变性测试通过："
        f"强信号 mean(τ_eff)={np.mean(tau_strong):.4f}, "
        f"弱信号 mean(τ_eff)={np.mean(tau_weak):.4f}, "
        f"比值={ratio:.4f}"
    )


# ════════════════════════════════════════════════════════════════════
# 3. NCP 拟合 sin(t) 测试
# ════════════════════════════════════════════════════════════════════

def test_ncp_sine_fitting():
    """用 19 神经元 NCP 拟合 sin(t) 序列（100 点），验证 MSE < 0.01。

    方法：储水池计算（Reservoir Computing）
      1. NCP 内部权重固定（C. elegans 布线 + CfC 动力学），充当非线性特征扩展器
      2. 输入 x = [sin(t), cos(t), sin(0.5t), 1] 提供丰富频率信息
      3. 收集 19 维隐状态序列
      4. 用岭回归（闭式解）训练线性读出层 W_out (19 → 1)
      5. 计算 MSE

    这是对 NCP 前向传播 + 训练管线的端到端验证。
    NCP 的 CfC 动力学 + C. elegans 布线提供了丰富的非线性记忆，
    读出层只需线性组合即可拟合 sin(t)。
    """
    # ── 生成 sin(t) 序列 ──
    n_points = 100
    t = np.linspace(0, 4 * np.pi, n_points)
    target = np.sin(t)

    # ── 输入编码：4 维，包含基频和半频分量 + 偏置 ──
    inputs = np.stack([
        np.sin(t),
        np.cos(t),
        np.sin(0.5 * t),
        np.ones_like(t),
    ], axis=1)  # shape=(100, 4)

    # ── 创建 NCP ──
    ncp = NCPCircuit(input_dim=4, seed=123)

    # ── 预热：先跑 30 步让暂态衰减 ──
    h = ncp.default_state()
    dt = t[1] - t[0]  # 均匀步长
    n_warmup = 30
    for i in range(n_warmup):
        x_in = inputs[i % n_points]
        h = ncp.forward(h, x_in, dt=dt)

    # ── 收集隐状态 ──
    hidden_states = np.zeros((n_points, NCPCircuit.N_TOTAL), dtype=np.float64)
    for i in range(n_points):
        h = ncp.forward(h, inputs[i], dt=dt)
        hidden_states[i] = h

    # ── 岭回归训练读出层 W_out (N_TOTAL → 1) ──
    # 解：W_out = (H^T H + λI)^-1 H^T target
    # 加入偏置项：在 H 末尾追加一列 1
    H = hidden_states
    H_bias = np.hstack([H, np.ones((n_points, 1))])  # shape=(100, 20)
    lam = 1e-4  # 正则化系数
    I = np.eye(H_bias.shape[1])
    I[-1, -1] = 0  # 不对偏置正则化
    W_out = np.linalg.solve(H_bias.T @ H_bias + lam * I, H_bias.T @ target)

    # ── 预测 ──
    predictions = H_bias @ W_out

    # ── 计算 MSE ──
    mse = float(np.mean((predictions - target) ** 2))
    print(f"[INFO] NCP sin(t) 拟合 MSE = {mse:.6f}")

    assert mse < 0.01, f"[ERROR] NCP sin(t) 拟合 MSE={mse:.6f} >= 0.01"

    print(f"[OK] NCP sin(t) 拟合测试通过，MSE={mse:.6f} < 0.01")


# ════════════════════════════════════════════════════════════════════
# 4. CfC 不规则 dt 测试
# ════════════════════════════════════════════════════════════════════

def test_cfc_arbitrary_dt():
    """验证 CfCCell 处理不规则 dt 序列 [0.3, 1.8, 3.6] 不报错。

    CfC 的闭合式解原生支持任意正实数 dt，无需 ODE 求解器，
    这对 LAAP 事件驱动认知循环中的不规则时间步至关重要。
    """
    cell = CfCCell(input_dim=3, hidden_dim=6, tau=1.0, seed=7)
    h = cell.default_state()
    x = np.array([0.1, -0.2, 0.3])

    irregular_dts = [0.3, 1.8, 3.6]
    for dt in irregular_dts:
        h = cell.forward(h, x, dt=dt)
        assert not np.any(np.isnan(h)), f"[ERROR] dt={dt} 产生 NaN"
        assert np.all(np.abs(h) <= 1e3), f"[ERROR] dt={dt} |h| 超过 1e3"

    # 再跑几步不规则 dt 验证持续稳定
    more_dts = [0.01, 5.0, 0.7, 2.2, 50.0]
    for dt in more_dts:
        h = cell.forward(h, x, dt=dt)
        assert not np.any(np.isnan(h)), f"[ERROR] dt={dt} 产生 NaN"

    print(f"[OK] CfC 不规则 dt 测试通过，最终 h shape={h.shape}, max|h|={np.max(np.abs(h)):.6f}")


# ════════════════════════════════════════════════════════════════════
# 额外验证测试（确保实现完整性）
# ════════════════════════════════════════════════════════════════════

def test_repr_and_dimensions():
    """验证 __repr__ 和维度一致性。"""
    ltc = LTCCell(input_dim=4, hidden_dim=8, tau_sys=2.0)
    cfc = CfCCell(input_dim=4, hidden_dim=8, tau=1.5)
    ncp = NCPCircuit(input_dim=4, seed=1)

    r_ltc = repr(ltc)
    r_cfc = repr(cfc)
    r_ncp = repr(ncp)

    assert "LTCCell" in r_ltc and "input_dim=4" in r_ltc, f"[ERROR] LTC repr 异常: {r_ltc}"
    assert "CfCCell" in r_cfc and "hidden_dim=8" in r_cfc, f"[ERROR] CfC repr 异常: {r_cfc}"
    assert "NCPCircuit" in r_ncp and "19" in r_ncp, f"[ERROR] NCP repr 异常: {r_ncp}"

    # NCP 命令神经元激活值应为 4 维
    h = ncp.default_state()
    h = ncp.forward(h, np.array([0.1, 0.2, 0.3, 0.4]), dt=0.1)
    cmd_act = ncp.get_command_activations()
    assert cmd_act.shape == (4,), f"[ERROR] 命令神经元激活值 shape 应为 (4,)，实际 {cmd_act.shape}"

    print("[OK] repr 与维度验证通过")


if __name__ == "__main__":
    # 支持直接 python 运行
    test_cfc_stability()
    test_ltc_tau_variability()
    test_ncp_sine_fitting()
    test_cfc_arbitrary_dt()
    test_repr_and_dimensions()
    print("\n[OK] 所有测试通过")
