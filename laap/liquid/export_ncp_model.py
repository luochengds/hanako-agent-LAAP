"""LAAP Liquid NCP 模型导出脚本（移动端部署用）

本脚本完成两件事：
  1. 创建一个 NCPCircuit(input_dim=8) 实例（8 个焦点输入，对应移动端
     注意力感知的 8 维向量：GPS/时间/通知/相机/健康/用户/任务/系统）
  2. 用储水池计算（Reservoir Computing）在正弦序列上训练 100 步，
     让 NCP 的内部动力学进入有意义的工作区（非完全随机权重）
  3. 将 NCP 的所有权重（突触矩阵 + 19 个 CfCCell 参数）导出为 JSON 格式
  4. 验证 JSON 体积 < 100KB（移动端 Bundle 容量约束）

JSON 模型结构（被 iOS Swift / Android Kotlin 运行时共同消费）：
  {
    "input_dim": 8,
    "n_total": 19, "n_sensory": 4, "n_inter": 6, "n_command": 4, "n_motor": 5,
    "w_input_sensory":   [[8x4]],   // input_dim → 感觉神经元投影
    "w_sensory_inter":   [[6x4]],
    "w_inter_command":   [[4x6]],
    "w_command_command": [[4x4]],
    "w_command_motor":   [[5x4]],
    "b_neurons":         [19],       // 每个神经元的外部/突触输入偏置
    "cells": [                        // 19 个 CfCCell 的权重
      {"w_tau": [1], "w_h": [[1,1]], "w_hh": [[1,1]], "b_h": [1]}, ...
    ]
  }

运行：
    python -m laap.liquid.export_ncp_model
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import numpy as np

from laap.liquid.neurons import NCPCircuit

logger = logging.getLogger("laap.liquid.export_ncp_model")

# ── 导出路径 ──────────────────────────────────────────────────────
DEFAULT_OUTPUT_PATH = Path(__file__).resolve().parent / "ncp_model.json"

# ── 移动端模型体积上限（100KB） ─────────────────────────────────
MAX_MODEL_SIZE_BYTES = 100 * 1024


# ════════════════════════════════════════════════════════════════════
# 训练：用储水池计算在正弦序列上微调 NCP 输入投影
# ════════════════════════════════════════════════════════════════════

def _train_ncp_on_sine(
    ncp: NCPCircuit,
    n_steps: int = 100,
    lr: float = 0.05,
    seed: int = 42,
) -> float:
    """用简单梯度下降在正弦序列上训练 NCP 的 W_input_sensory 投影。

    目标：让 NCP 的命令神经元激活值（4 维）追踪 [sin(t), cos(t), sin(0.5t), cos(0.5t)]。
    仅训练 W_input_sensory（输入投影），NCP 内部 CfC 动力学保持固定（储水池思想）。
    用有限差分估计梯度（无需 autograd），100 步足够让权重进入有意义的工作区。

    返回最终 MSE。
    """
    rng = np.random.default_rng(seed)
    t = np.linspace(0, 4 * np.pi, n_steps)
    dt = float(t[1] - t[0])

    # 8 维输入编码：sin/cos 基频 + 半频 + 季节性 + 偏置
    inputs = np.stack(
        [
            np.sin(t),
            np.cos(t),
            np.sin(0.5 * t),
            np.cos(0.5 * t),
            np.sin(2.0 * t),
            np.cos(2.0 * t),
            np.sin(0.25 * t),
            np.ones_like(t),
        ],
        axis=1,
    )  # shape=(n_steps, 8)

    # 目标：命令神经元激活（4 维）追踪前 4 个输入分量
    targets = inputs[:, :4].copy()  # shape=(n_steps, 4)

    h = ncp.default_state()

    # 有限差分梯度下降
    last_mse = float("inf")
    for step in range(n_steps):
        x = inputs[step % n_steps]
        target = targets[step % n_steps]

        # 前向
        h_new = ncp.forward(h, x, dt=dt)
        cmd_act = ncp.get_command_activations()  # shape=(4,)
        err = cmd_act - target
        mse = float(np.mean(err**2))

        # 有限差分梯度：对 W_input_sensory 加扰动再前向，估计 dMSE/dW
        # 仅每 5 步更新一次权重以减少计算量
        if step % 5 == 0 and step > 0:
            eps = 1e-3
            # 估计梯度（仅对 4x8 投影矩阵，共 32 个参数）
            grad = np.zeros_like(ncp.W_input_sensory)
            for i in range(ncp.W_input_sensory.shape[0]):
                for j in range(ncp.W_input_sensory.shape[1]):
                    # +eps 扰动
                    orig = ncp.W_input_sensory[i, j]
                    ncp.W_input_sensory[i, j] = orig + eps
                    h_p = ncp.forward(h, x, dt=dt)
                    cmd_p = ncp.get_command_activations()
                    err_p = cmd_p - target
                    mse_p = float(np.mean(err_p**2))
                    # 恢复
                    ncp.W_input_sensory[i, j] = orig
                    grad[i, j] = (mse_p - mse) / eps
            # 梯度下降步
            ncp.W_input_sensory -= lr * grad

        h = h_new
        last_mse = mse

    logger.info(f"[INFO] NCP 训练完成，{n_steps} 步后 MSE={last_mse:.6f}")
    return last_mse


# ════════════════════════════════════════════════════════════════════
# 导出：将 NCPCircuit 序列化为 JSON
# ════════════════════════════════════════════════════════════════════

def _matrix_to_list(m: np.ndarray) -> list[list[float]]:
    """将 2D numpy 数组转为嵌套 list[float]。"""
    return np.asarray(m, dtype=np.float64).tolist()


def _vector_to_list(v: np.ndarray) -> list[float]:
    """将 1D numpy 数组转为 list[float]。"""
    return np.asarray(v, dtype=np.float64).tolist()


def export_ncp_to_dict(ncp: NCPCircuit) -> dict[str, Any]:
    """将 NCPCircuit 实例的所有权重导出为可 JSON 序列化的 dict。

    包含：
      - 拓扑常量（神经元数量、输入维度）
      - 5 个突触权重矩阵（input_sensory / sensory_inter / inter_command /
        command_command / command_motor）
      - 19 个神经元的偏置 b_neurons
      - 19 个 CfCCell 的内部权重（W_tau / W_h / W_hh / b_h）
    """
    cells_json: list[dict[str, Any]] = []
    for cell in ncp.cells:
        cells_json.append(
            {
                "w_tau": _vector_to_list(cell.W_tau),
                "w_h": _matrix_to_list(cell.W_h),
                "w_hh": _matrix_to_list(cell.W_hh),
                "b_h": _vector_to_list(cell.b_h),
            }
        )

    return {
        "input_dim": int(ncp.input_dim),
        "n_total": int(ncp.N_TOTAL),
        "n_sensory": int(ncp.N_SENSORY),
        "n_inter": int(ncp.N_INTER),
        "n_command": int(ncp.N_COMMAND),
        "n_motor": int(ncp.N_MOTOR),
        "w_input_sensory": _matrix_to_list(ncp.W_input_sensory),
        "w_sensory_inter": _matrix_to_list(ncp.W_sensory_inter),
        "w_inter_command": _matrix_to_list(ncp.W_inter_command),
        "w_command_command": _matrix_to_list(ncp.W_command_command),
        "w_command_motor": _matrix_to_list(ncp.W_command_motor),
        "b_neurons": _vector_to_list(ncp.b_neurons),
        "cells": cells_json,
    }


def save_ncp_model(
    ncp: NCPCircuit,
    output_path: Path | None = None,
) -> tuple[Path, int]:
    """导出 NCP 模型到 JSON 文件，返回 (路径, 字节数)。

    会校验文件体积 < 100KB。
    """
    output_path = output_path or DEFAULT_OUTPUT_PATH
    model_dict = export_ncp_to_dict(ncp)

    # 紧凑 JSON（无空白），移动端 Bundle 友好
    json_str = json.dumps(model_dict, separators=(",", ":"))
    data = json_str.encode("utf-8")
    size = len(data)

    if size >= MAX_MODEL_SIZE_BYTES:
        raise RuntimeError(
            f"[ERROR] 导出的 NCP 模型体积 {size} 字节 >= "
            f"{MAX_MODEL_SIZE_BYTES} 字节上限"
        )

    output_path.write_bytes(data)
    logger.info(
        f"[OK] NCP 模型已导出到 {output_path}，"
        f"体积 {size} 字节（{size / 1024:.2f} KB）"
    )
    return output_path, size


# ════════════════════════════════════════════════════════════════════
# 主入口
# ════════════════════════════════════════════════════════════════════

def main() -> None:
    """主入口：创建 → 训练 → 导出 NCP 模型。"""
    logging.basicConfig(
        level=logging.INFO,
        format="[%(levelname)s] %(name)s: %(message)s",
    )

    logger.info("[INFO] 创建 NCPCircuit(input_dim=8) 实例")
    ncp = NCPCircuit(input_dim=8, seed=2024)

    logger.info("[INFO] 在正弦序列上训练 100 步（储水池 + 有限差分梯度下降）")
    mse = _train_ncp_on_sine(ncp, n_steps=100, lr=0.05, seed=42)
    logger.info(f"[INFO] 训练后 MSE = {mse:.6f}")

    logger.info(f"[INFO] 导出模型到 {DEFAULT_OUTPUT_PATH}")
    path, size = save_ncp_model(ncp, DEFAULT_OUTPUT_PATH)

    # 体积校验
    kb = size / 1024
    status = "[OK]" if size < MAX_MODEL_SIZE_BYTES else "[WARN]"
    print(
        f"{status} NCP 模型导出完成：{path}\n"
        f"     体积 = {size} 字节 ({kb:.2f} KB)，"
        f"上限 {MAX_MODEL_SIZE_BYTES // 1024} KB"
    )


if __name__ == "__main__":
    main()
