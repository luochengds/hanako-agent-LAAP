"""LAAP Liquid — CfC 时间序列预测场 (Task 13)

用 CfCCell 做时间序列预测，预测置信度与隐藏态范数关联。

设计要点：
  - CfC 的闭合式解让 observe() 在任意 dt 上一步前向即可演化隐藏态，
    无需 ODE 求解器，适合事件驱动的实时观察流。
  - 隐藏态范数 ||h|| 反映历史信息的累积程度：
      ||h|| 大 → 近期观察携带的信息多 → 预测置信度高
      ||h|| 小 → 隐藏态接近零（初始化或长期遗忘）→ 置信度低
  - 置信度映射：confidence = sigmoid(||h||) ∈ (0, 1)
  - 预测时以最后一个观察值作为持续输入，向前积分 steps 步，
    取隐藏态前 input_dim 维作为预测值（简单线性读出）。

本模块**不** import laap.agi.world_model.py，使用自己的接口，避免循环依赖。

LAAP 日志风格：[OK]/[INFO]/[WARN]/[ERROR]。
"""

from __future__ import annotations

import logging
import time
from collections import deque
from typing import Deque, Dict, List, Optional

import numpy as np

from laap.liquid.neurons import CfCCell

logger = logging.getLogger("laap.liquid.memory_field")


# ════════════════════════════════════════════════════════════════════
# LiquidMemoryField — CfC 时间序列预测场
# ════════════════════════════════════════════════════════════════════

class LiquidMemoryField:
    """CfC 时间序列预测场。

    用 CfCCell 维护一个随观察流演化的隐藏态 h，提供：
      - observe(x, t_now): 记录观察值并按 dt 演化 h
      - predict(steps, dt): 以当前 h 为起点，向前预测 steps 步
      - get_confidence(): 返回当前预测置信度 = sigmoid(||h||)

    属性：
        cell      : CfCCell 实例
        h         : 当前隐藏态 (hidden_dim,)
        last_t    : 上次观察的时间戳
        history   : 最近观察值的 deque(maxlen=100)
    """

    def __init__(self, input_dim: int = 8, hidden_dim: int = 16) -> None:
        if input_dim <= 0 or hidden_dim <= 0:
            raise ValueError(
                f"[ERROR] 维度必须为正：input_dim={input_dim}, hidden_dim={hidden_dim}"
            )

        self.cell = CfCCell(input_dim=input_dim, hidden_dim=hidden_dim, seed=42)
        self.h: np.ndarray = np.zeros(hidden_dim, dtype=np.float64)
        self.last_t: float = time.time()
        self.history: Deque[np.ndarray] = deque(maxlen=100)

        logger.debug(
            f"[INFO] LiquidMemoryField 初始化: input_dim={input_dim}, "
            f"hidden_dim={hidden_dim}"
        )

    # ── 内部工具 ──────────────────────────────────────────────────

    def _coerce_input(self, x: np.ndarray) -> np.ndarray:
        """将输入 x 整形/填充/截断到 (input_dim,) 的 float64 向量。"""
        x = np.asarray(x, dtype=np.float64).flatten()
        if x.size < self.cell.input_dim:
            x = np.pad(x, (0, self.cell.input_dim - x.size))
        elif x.size > self.cell.input_dim:
            x = x[: self.cell.input_dim]
        return x.astype(np.float64)

    # ── 观察 ──────────────────────────────────────────────────────

    def observe(self, x: np.ndarray, t_now: Optional[float] = None) -> None:
        """记录一个观察值并按 dt 演化 CfC 隐藏态。

        参数：
            x     : 观察值向量（任意维度，内部会填充/截断到 input_dim）
            t_now : 当前时间戳。None 时使用 time.time()。
                    若 t_now < last_t（时钟回退），dt 视为 0。
        """
        if t_now is None:
            t_now = time.time()

        dt = float(t_now - self.last_t)
        if dt < 0.0:
            # 时钟回退或显式 t_now 早于 last_t：视为同步观察，不演化
            dt = 0.0
        self.last_t = float(t_now)

        x_arr = self._coerce_input(x)
        self.h = self.cell.forward(self.h, x_arr, dt)
        self.history.append(x_arr.copy())

    # ── 预测 ──────────────────────────────────────────────────────

    def predict(self, steps: int = 3, dt: float = 0.1) -> dict:
        """从当前隐藏态向前预测 steps 步。

        以最后一个观察值作为持续输入，按 dt 步长积分 CfC，
        每步取隐藏态前 input_dim 维作为预测值。

        参数：
            steps : 预测步数
            dt    : 每步积分时长

        返回：
            {
                "predicted_values": list[np.ndarray],  # 长度 steps
                "confidence": float,                  # sigmoid(||h||) ∈ (0,1)
                "hidden_norm": float,                 # 当前 ||h||（预测前）
            }
        """
        if steps < 0:
            raise ValueError(f"[ERROR] steps 必须非负，实际 steps={steps}")
        if dt < 0:
            raise ValueError(f"[ERROR] dt 必须非负，实际 dt={dt}")

        # 预测前的隐藏态范数（反映当前信息量）
        hidden_norm = float(np.linalg.norm(self.h))

        # 以最后一个观察值作为持续输入；无历史则用零向量
        if self.history:
            last_x = self.history[-1].copy()
        else:
            last_x = np.zeros(self.cell.input_dim, dtype=np.float64)

        # 从当前 h 开始向前积分
        h = self.h.copy()
        predicted: List[np.ndarray] = []
        for _ in range(steps):
            h = self.cell.forward(h, last_x, dt)
            # 简单线性读出：取 h 的前 input_dim 维作为预测值
            pred = h[: self.cell.input_dim].copy()
            # 若 hidden_dim < input_dim，补零
            if pred.size < self.cell.input_dim:
                pred = np.pad(pred, (0, self.cell.input_dim - pred.size))
            predicted.append(pred.astype(np.float64))

        return {
            "predicted_values": predicted,
            "confidence": self.get_confidence(),
            "hidden_norm": hidden_norm,
        }

    # ── 查询接口 ──────────────────────────────────────────────────

    def get_confidence(self) -> float:
        """返回当前预测置信度 = sigmoid(||h||) ∈ (0, 1)。

        ||h|| 大 → 历史信息丰富 → 置信度高；
        ||h|| 小 → 隐藏态接近零 → 置信度低（趋于 0.5）。
        """
        h_norm = float(np.linalg.norm(self.h))
        # 数值稳定 sigmoid
        if h_norm >= 0:
            return float(1.0 / (1.0 + np.exp(-h_norm)))
        else:
            e = np.exp(h_norm)
            return float(e / (1.0 + e))

    def get_h_summary(self) -> dict:
        """返回隐藏态摘要信息。"""
        return {
            "h_norm": float(np.linalg.norm(self.h)),
            "history_len": len(self.history),
        }

    def __repr__(self) -> str:
        return (
            f"LiquidMemoryField(input_dim={self.cell.input_dim}, "
            f"hidden_dim={self.cell.hidden_dim}, history={len(self.history)})"
        )
