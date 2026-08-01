"""LAAP Liquid NCP 移动端部署 E2E 验证（Task 17）

本测试套件验证 Task 14-16 的移动端 NCP 部署管线：
  1. test_model_export           —— 运行导出脚本，验证 ncp_model.json 生成且 < 100KB
  2. test_model_structure        —— 加载 JSON 验证结构完整（含所有权重矩阵）
  3. test_mobile_inference_simulation —— 用 Python 模拟移动端推理流程：
       - 加载 JSON 权重
       - 重建 NCP 推理逻辑（不依赖 NCPCircuit 类，直接用 JSON 权重做矩阵运算）
       - 验证推理结果与原 NCPCircuit 一致（误差 < 1e-6）
       - 验证推理延迟 < 1ms（100 次推理平均）
  4. test_standalone_psi_loop    —— 模拟移动端独立 PSI 循环
       （感知→NCP推理→响应），无桌面主节点

运行：
    cd d:\\LAAP && python -m pytest laap/liquid/tests/test_mobile_ncp.py -v
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pytest

from laap.liquid.export_ncp_model import (
    DEFAULT_OUTPUT_PATH,
    MAX_MODEL_SIZE_BYTES,
    export_ncp_to_dict,
    save_ncp_model,
)
from laap.liquid.neurons import NCPCircuit


# ════════════════════════════════════════════════════════════════════
# 1. 模型导出测试
# ════════════════════════════════════════════════════════════════════

def test_model_export():
    """运行导出脚本，验证 ncp_model.json 生成且体积 < 100KB。

    覆盖 Task 14 的核心约束：
      - 文件确实生成
      - 体积约束（移动端 Bundle 友好）
    """
    # 创建一个 NCP 并导出
    ncp = NCPCircuit(input_dim=8, seed=2024)
    output_path, size = save_ncp_model(ncp, DEFAULT_OUTPUT_PATH)

    # 验证 1：文件存在
    assert output_path.exists(), f"[ERROR] 导出文件不存在: {output_path}"
    assert output_path.is_file(), f"[ERROR] 路径不是文件: {output_path}"

    # 验证 2：体积 < 100KB
    assert size < MAX_MODEL_SIZE_BYTES, (
        f"[ERROR] 模型体积 {size} 字节 >= 上限 {MAX_MODEL_SIZE_BYTES} 字节"
    )

    # 验证 3：是合法 JSON
    data = json.loads(output_path.read_text(encoding="utf-8"))
    assert isinstance(data, dict), f"[ERROR] JSON 顶层应为 dict"

    kb = size / 1024
    print(f"[OK] 模型导出测试通过：{output_path.name}，{size} 字节 ({kb:.2f} KB)")


# ════════════════════════════════════════════════════════════════════
# 2. 模型结构完整性测试
# ════════════════════════════════════════════════════════════════════

def test_model_structure():
    """加载 JSON 验证结构完整（含所有权重矩阵 + 19 个 CfCCell）。

    验证字段：
      - 拓扑常量：input_dim, n_total, n_sensory, n_inter, n_command, n_motor
      - 突触矩阵：w_input_sensory, w_sensory_inter, w_inter_command,
                  w_command_command, w_command_motor
      - 偏置：b_neurons
      - cells：19 个 CfCCell，每个含 w_tau, w_h, w_hh, b_h
    """
    # 确保模型已导出
    if not DEFAULT_OUTPUT_PATH.exists():
        ncp = NCPCircuit(input_dim=8, seed=2024)
        save_ncp_model(ncp, DEFAULT_OUTPUT_PATH)

    data = json.loads(DEFAULT_OUTPUT_PATH.read_text(encoding="utf-8"))

    # 拓扑常量
    assert data["input_dim"] == 8, f"[ERROR] input_dim 应为 8，实际 {data['input_dim']}"
    assert data["n_total"] == 19, f"[ERROR] n_total 应为 19，实际 {data['n_total']}"
    assert data["n_sensory"] == 4
    assert data["n_inter"] == 6
    assert data["n_command"] == 4
    assert data["n_motor"] == 5

    # 突触矩阵形状
    def check_matrix(name, expected_rows, expected_cols):
        m = data[name]
        assert len(m) == expected_rows, (
            f"[ERROR] {name} 行数应为 {expected_rows}，实际 {len(m)}"
        )
        for row in m:
            assert len(row) == expected_cols, (
                f"[ERROR] {name} 列数应为 {expected_cols}，实际 {len(row)}"
            )

    check_matrix("w_input_sensory", 4, 8)    # (nSensory, inputDim)
    check_matrix("w_sensory_inter", 6, 4)    # (nInter, nSensory)
    check_matrix("w_inter_command", 4, 6)    # (nCommand, nInter)
    check_matrix("w_command_command", 4, 4)  # (nCommand, nCommand)
    check_matrix("w_command_motor", 5, 4)    # (nMotor, nCommand)

    # 偏置
    assert len(data["b_neurons"]) == 19, (
        f"[ERROR] b_neurons 长度应为 19，实际 {len(data['b_neurons'])}"
    )

    # 19 个 CfCCell
    cells = data["cells"]
    assert len(cells) == 19, f"[ERROR] cells 长度应为 19，实际 {len(cells)}"
    for i, cell in enumerate(cells):
        assert "w_tau" in cell, f"[ERROR] cells[{i}] 缺少 w_tau"
        assert "w_h" in cell, f"[ERROR] cells[{i}] 缺少 w_h"
        assert "w_hh" in cell, f"[ERROR] cells[{i}] 缺少 w_hh"
        assert "b_h" in cell, f"[ERROR] cells[{i}] 缺少 b_h"
        assert len(cell["w_tau"]) == 1, f"[ERROR] cells[{i}].w_tau 长度应为 1"
        assert len(cell["w_h"]) == 1 and len(cell["w_h"][0]) == 1, (
            f"[ERROR] cells[{i}].w_h 形状应为 (1,1)"
        )
        assert len(cell["w_hh"]) == 1 and len(cell["w_hh"][0]) == 1, (
            f"[ERROR] cells[{i}].w_hh 形状应为 (1,1)"
        )
        assert len(cell["b_h"]) == 1, f"[ERROR] cells[{i}].b_h 长度应为 1"

    print("[OK] 模型结构完整性测试通过：5 个突触矩阵 + 19 个 CfCCell 均完整")


# ════════════════════════════════════════════════════════════════════
# 3. 移动端推理模拟测试（核心：纯 JSON 权重重建推理）
# ════════════════════════════════════════════════════════════════════

class _StandaloneNCPInference:
    """用纯 JSON 权重重建的 NCP 推理（模拟 iOS/Android 移动端运行时）。

    不依赖 laap.liquid.neurons.NCPCircuit，仅用 numpy 做矩阵运算。
    算法等价于 NCPCircuit.forward，用于验证移动端部署的正确性。
    """

    def __init__(self, model_dict: dict) -> None:
        self.input_dim = model_dict["input_dim"]
        self.n_total = model_dict["n_total"]
        self.n_sensory = model_dict["n_sensory"]
        self.n_inter = model_dict["n_inter"]
        self.n_command = model_dict["n_command"]
        self.n_motor = model_dict["n_motor"]

        self.w_input_sensory = np.array(model_dict["w_input_sensory"], dtype=np.float64)
        self.w_sensory_inter = np.array(model_dict["w_sensory_inter"], dtype=np.float64)
        self.w_inter_command = np.array(model_dict["w_inter_command"], dtype=np.float64)
        self.w_command_command = np.array(model_dict["w_command_command"], dtype=np.float64)
        self.w_command_motor = np.array(model_dict["w_command_motor"], dtype=np.float64)
        self.b_neurons = np.array(model_dict["b_neurons"], dtype=np.float64)

        # 19 个 CfCCell 权重
        self.cells = []
        for c in model_dict["cells"]:
            self.cells.append({
                "w_tau": np.array(c["w_tau"], dtype=np.float64),
                "w_h": np.array(c["w_h"], dtype=np.float64),
                "w_hh": np.array(c["w_hh"], dtype=np.float64),
                "b_h": np.array(c["b_h"], dtype=np.float64),
            })

        # 索引区间（与 NCPCircuit 一致）
        self.sensory_idx = (0, self.n_sensory)
        self.inter_idx = (self.n_sensory, self.n_sensory + self.n_inter)
        self.command_idx = (self.n_sensory + self.n_inter,
                            self.n_sensory + self.n_inter + self.n_command)
        self.motor_idx = (self.n_sensory + self.n_inter + self.n_command, self.n_total)

        self._command_activations = np.zeros(self.n_command, dtype=np.float64)

    @staticmethod
    def _sigmoid(x: np.ndarray) -> np.ndarray:
        out = np.where(
            x >= 0,
            1.0 / (1.0 + np.exp(-np.clip(x, -50.0, 50.0))),
            np.exp(np.clip(x, -50.0, 50.0)) / (1.0 + np.exp(np.clip(x, -50.0, 50.0))),
        )
        return np.clip(out, 1e-6, 1.0 - 1e-6)

    def _cfc_forward(self, cell_idx: int, h: float, x: float, dt: float) -> float:
        """单 CfCCell 前向（input_dim=1, hidden_dim=1）。"""
        c = self.cells[cell_idx]
        # r = σ(-W_τ · dt)
        r = self._sigmoid(-c["w_tau"] * dt)[0]
        # h̃ = tanh(W_h[0,0] · x + W_hh[0,0] · h + b_h[0])
        h_tilde = np.tanh(np.clip(
            c["w_h"][0, 0] * x + c["w_hh"][0, 0] * h + c["b_h"][0],
            -50.0, 50.0
        ))
        new_h = r * h + (1.0 - r) * h_tilde
        return float(new_h)

    def forward(self, h: np.ndarray, x: np.ndarray, dt: float) -> np.ndarray:
        """单步前向，返回新的 19 维隐状态。"""
        if dt == 0.0:
            return h.copy()

        new_h = h.copy()

        # 1. 感觉神经元
        sensory_in = self.w_input_sensory @ x  # (4,)
        for i in range(self.n_sensory):
            idx = self.sensory_idx[0] + i
            xi = sensory_in[i] + self.b_neurons[idx]
            new_h[idx] = self._cfc_forward(idx, h[idx], xi, dt)

        # 2. 中间神经元
        sensory_out = new_h[self.sensory_idx[0]:self.sensory_idx[1]]
        inter_in = self.w_sensory_inter @ sensory_out  # (6,)
        for i in range(self.n_inter):
            idx = self.inter_idx[0] + i
            xi = inter_in[i] + self.b_neurons[idx]
            new_h[idx] = self._cfc_forward(idx, h[idx], xi, dt)

        # 3. 命令神经元（含循环连接，用旧 h 避免循环依赖）
        inter_out = new_h[self.inter_idx[0]:self.inter_idx[1]]
        h_command_old = h[self.command_idx[0]:self.command_idx[1]]
        command_feedback = self.w_command_command @ h_command_old
        command_in = self.w_inter_command @ inter_out + command_feedback  # (4,)
        for i in range(self.n_command):
            idx = self.command_idx[0] + i
            xi = command_in[i] + self.b_neurons[idx]
            new_h[idx] = self._cfc_forward(idx, h[idx], xi, dt)

        # 记录命令神经元激活值（tanh 压缩）
        self._command_activations = np.tanh(
            new_h[self.command_idx[0]:self.command_idx[1]]
        )

        # 4. 运动神经元
        command_out = new_h[self.command_idx[0]:self.command_idx[1]]
        motor_in = self.w_command_motor @ command_out  # (5,)
        for i in range(self.n_motor):
            idx = self.motor_idx[0] + i
            xi = motor_in[i] + self.b_neurons[idx]
            new_h[idx] = self._cfc_forward(idx, h[idx], xi, dt)

        # 隐状态裁剪（与 NCPCircuit._clip_h 一致）
        return np.clip(new_h, -1e3, 1e3)

    def get_command_activations(self) -> np.ndarray:
        return self._command_activations.copy()

    def default_state(self) -> np.ndarray:
        return np.zeros(self.n_total, dtype=np.float64)


def test_mobile_inference_simulation():
    """用 Python 模拟移动端推理流程，验证正确性与延迟。

    验证项：
      1. 加载 JSON 权重重建推理逻辑（不依赖 NCPCircuit 类）
      2. 推理结果与原 NCPCircuit 一致（误差 < 1e-6）
      3. 100 次推理平均延迟 < 1ms
    """
    # 确保模型已导出
    if not DEFAULT_OUTPUT_PATH.exists():
        ncp = NCPCircuit(input_dim=8, seed=2024)
        save_ncp_model(ncp, DEFAULT_OUTPUT_PATH)

    model_dict = json.loads(DEFAULT_OUTPUT_PATH.read_text(encoding="utf-8"))

    # ── 1. 用 JSON 权重重建移动端推理 ──
    mobile_ncp = _StandaloneNCPInference(model_dict)

    # ── 2. 正确性验证：与原 NCPCircuit 对比 ──
    # 用相同 seed 创建 NCPCircuit，重新导出，确保对比的是同一组权重
    ncp_ref = NCPCircuit(input_dim=8, seed=2024)
    # 用导出脚本中的训练过程同步权重（否则 _StandaloneNCPInference 用的是已训练权重）
    # 这里直接用导出的 dict 重建一个"参考" NCPCircuit：将 JSON 权重赋回 NCPCircuit
    ncp_ref.W_input_sensory = np.array(model_dict["w_input_sensory"], dtype=np.float64)
    ncp_ref.W_sensory_inter = np.array(model_dict["w_sensory_inter"], dtype=np.float64)
    ncp_ref.W_inter_command = np.array(model_dict["w_inter_command"], dtype=np.float64)
    ncp_ref.W_command_command = np.array(model_dict["w_command_command"], dtype=np.float64)
    ncp_ref.W_command_motor = np.array(model_dict["w_command_motor"], dtype=np.float64)
    ncp_ref.b_neurons = np.array(model_dict["b_neurons"], dtype=np.float64)
    for i, c in enumerate(model_dict["cells"]):
        ncp_ref.cells[i].W_tau = np.array(c["w_tau"], dtype=np.float64)
        ncp_ref.cells[i].W_h = np.array(c["w_h"], dtype=np.float64)
        ncp_ref.cells[i].W_hh = np.array(c["w_hh"], dtype=np.float64)
        ncp_ref.cells[i].b_h = np.array(c["b_h"], dtype=np.float64)

    # 用一组确定性输入做对比
    rng = np.random.default_rng(99)
    h_ref = ncp_ref.default_state()
    h_mob = mobile_ncp.default_state()
    x = rng.standard_normal(8)
    dt = 0.1

    # 跑 10 步，每步对比
    max_err = 0.0
    for step in range(10):
        h_ref = ncp_ref.forward(h_ref, x, dt=dt)
        h_mob = mobile_ncp.forward(h_mob, x, dt=dt)
        err = float(np.max(np.abs(h_ref - h_mob)))
        max_err = max(max_err, err)
        assert err < 1e-6, (
            f"[ERROR] 步骤 {step}: 移动端推理与原 NCP 误差 {err:.2e} >= 1e-6"
        )

    # 命令神经元激活值对比
    cmd_ref = ncp_ref.get_command_activations()
    cmd_mob = mobile_ncp.get_command_activations()
    cmd_err = float(np.max(np.abs(cmd_ref - cmd_mob)))
    assert cmd_err < 1e-6, f"[ERROR] 命令神经元激活值误差 {cmd_err:.2e} >= 1e-6"

    # ── 3. 延迟测试：100 次推理平均 < 1ms ──
    h = mobile_ncp.default_state()
    x_fixed = rng.standard_normal(8)
    n_iters = 100
    # 预热（避免首次 JIT/缓存开销）
    for _ in range(10):
        h = mobile_ncp.forward(h, x_fixed, dt=0.05)

    start = time.perf_counter()
    for _ in range(n_iters):
        h = mobile_ncp.forward(h, x_fixed, dt=0.05)
    elapsed = time.perf_counter() - start
    avg_ms = (elapsed / n_iters) * 1000.0

    assert avg_ms < 1.0, (
        f"[ERROR] 移动端推理平均延迟 {avg_ms:.4f} ms >= 1.0 ms"
    )

    print(
        f"[OK] 移动端推理模拟测试通过："
        f"最大误差 {max_err:.2e}，"
        f"命令激活误差 {cmd_err:.2e}，"
        f"平均延迟 {avg_ms:.4f} ms < 1.0 ms"
    )


# ════════════════════════════════════════════════════════════════════
# 4. 独立 PSI 循环模拟（无桌面主节点）
# ════════════════════════════════════════════════════════════════════

def test_standalone_psi_loop():
    """模拟移动端独立 PSI 循环：感知→NCP推理→响应。

    场景：移动端断网/桌面不可达时，仅靠本地 19 神经元 NCP 做轻量认知循环。
    验证：
      1. 循环能稳定运行 50 轮（无 NaN、无爆炸）
      2. 命令神经元激活值在合理范围 [-1, 1]
      3. 运动神经元响应能反映输入变化（非完全死循环）
    """
    if not DEFAULT_OUTPUT_PATH.exists():
        ncp = NCPCircuit(input_dim=8, seed=2024)
        save_ncp_model(ncp, DEFAULT_OUTPUT_PATH)

    model_dict = json.loads(DEFAULT_OUTPUT_PATH.read_text(encoding="utf-8"))
    mobile_ncp = _StandaloneNCPInference(model_dict)

    # 模拟 PSI 循环状态
    class MockPSIState:
        competence = 0.7
        autonomy = 0.5
        relatedness = 0.5
        certainty = 0.5
        growth = 0.5

    h = mobile_ncp.default_state()
    state = MockPSIState()
    dt = 0.1  # 模拟 100ms 循环周期

    cmd_history = []
    motor_history = []

    for cycle in range(50):
        # ── Perceive：将 PSI 状态编码为 8 维输入 ──
        percept_input = np.array([
            state.competence,
            state.autonomy,
            state.relatedness,
            state.certainty,
            state.growth,
            0.5,  # attention focus 占位
            0.5,  # self presence
            min(1.0, cycle / 50.0),  # 时间累积
        ], dtype=np.float64)

        # ── NCP Inference ──
        h = mobile_ncp.forward(h, percept_input, dt=dt)
        cmd_act = mobile_ncp.get_command_activations()
        motor_out = h[mobile_ncp.motor_idx[0]:mobile_ncp.motor_idx[1]]

        # ── Act/Learn：用 motor 响应更新 PSI 状态（简化） ──
        motor_mean = float(np.mean(motor_out))
        state.competence = float(np.clip(state.competence + 0.01 * motor_mean, 0, 1))
        state.certainty = float(np.clip(state.certainty + 0.005 * motor_mean, 0, 1))
        # 自然衰减
        state.autonomy = float(np.clip(state.autonomy - 0.002, 0, 1))
        state.relatedness = float(np.clip(state.relatedness - 0.002, 0, 1))
        state.growth = float(np.clip(state.growth - 0.002, 0, 1))

        cmd_history.append(cmd_act.copy())
        motor_history.append(motor_out.copy())

    # 验证 1：无 NaN
    cmd_arr = np.array(cmd_history)
    motor_arr = np.array(motor_history)
    assert not np.any(np.isnan(cmd_arr)), "[ERROR] 命令激活值出现 NaN"
    assert not np.any(np.isnan(motor_arr)), "[ERROR] 运动响应出现 NaN"

    # 验证 2：无爆炸
    assert np.all(np.abs(cmd_arr) <= 1.0 + 1e-9), (
        f"[ERROR] 命令激活值超出 [-1,1]: max={cmd_arr.max()}, min={cmd_arr.min()}"
    )
    assert np.all(np.abs(motor_arr) <= 1e3), (
        f"[ERROR] 运动响应爆炸: max|h|={np.max(np.abs(motor_arr))}"
    )

    # 验证 3：运动响应有变化（非死循环）
    motor_var = float(np.var(motor_arr))
    assert motor_var > 1e-8, (
        f"[ERROR] 运动响应方差过小 {motor_var:.2e}，可能为死循环"
    )

    # 验证 4：独立循环完成 50 轮无桌面依赖
    # （这里仅验证不抛异常且状态稳定，实际桌面唤醒逻辑在 Kotlin/Swift 侧）

    print(
        f"[OK] 独立 PSI 循环测试通过：50 轮无桌面依赖，"
        f"命令激活范围 [{cmd_arr.min():.4f}, {cmd_arr.max():.4f}]，"
        f"运动响应方差 {motor_var:.4e}"
    )


# ════════════════════════════════════════════════════════════════════
# 入口
# ════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    test_model_export()
    test_model_structure()
    test_mobile_inference_simulation()
    test_standalone_psi_loop()
    print("\n[OK] 所有移动端 NCP 部署测试通过")
