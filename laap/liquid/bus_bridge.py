"""LAAP Liquid — LiquidBusField 认知总线液态状态场

本模块实现 ``LiquidBusField``：将 LAAP 认知总线（CognitiveBus）的
PSI 五需求 + 情感信号编码为 10 维输入，驱动一个 CfCCell 演化 32 维
隐状态 ``h(t)``，再从 ``h(t)`` 的前 5 维经 sigmoid 解码回 PSI 五需求。

设计要点：
  - **连续时间演化**：``evolve`` 按真实 Δt = t_now - last_t 推进，
    原生支持事件驱动的不规则时间步。
  - **避免循环依赖**：本模块不 import ``laap.agi.cognitive_bus``，
    ``decode_needs`` 返回普通 dict，键名与 ``NeedState`` 字段对齐。
  - **核心容器兼容**：提供 ``step(t_now)`` 单参演化接口，便于
    ``LiquidCognitiveCore.evolve_all`` 自动调度。

PSI 五需求（与 NeedState 字段一致）：
    competence, autonomy, relatedness, certainty, growth
    取值范围 [0.0, 1.0]，1.0 = 完全满足，0.0 = 完全匮乏。

LAAP 日志风格：使用 [OK]/[INFO]/[WARN]/[ERROR] 标签。
"""

from __future__ import annotations

import logging
import time
from typing import Dict, Optional

import numpy as np

from laap.liquid.neurons import CfCCell, _xavier_init

logger = logging.getLogger("laap.liquid.bus_bridge")

# ── 常量 ──────────────────────────────────────────────────────
# PSI 五需求键名（与 laap.agi.cognitive_bus.NeedState 字段对齐）
_NEED_KEYS = ("competence", "autonomy", "relatedness", "certainty", "growth")

# 输入维度：5 需求增量 + 5 情感信号
_INPUT_DIM = 10

# 默认隐状态维度
_DEFAULT_STATE_DIM = 32


class LiquidBusField:
    """认知总线液态状态场。

    内嵌一个 ``CfCCell(input_dim=10, hidden_dim=state_dim)`` 作为状态演化核心。
    隐状态 ``h`` 的前 5 维经 sigmoid 解码为 PSI 五需求。

    参数：
        state_dim : 隐状态维度，默认 32
        seed      : CfCCell 随机种子（可复现）

    属性：
        cfc      : 内嵌 CfCCell
        h        : 当前隐状态 (state_dim,)
        last_t   : 上次演化的时间戳
    """

    def __init__(self, state_dim: int = _DEFAULT_STATE_DIM, *, seed: Optional[int] = None,
                 use_input_gate: bool = False) -> None:
        """
        参数：
            state_dim      : 隐状态维度，默认 32
            seed           : CfCCell 随机种子
            use_input_gate : 是否启用 K3 启发的输入依赖门控。
                             True 时 CfCCell 的门控同时依赖 dt 和输入 x，
                             强输入信号会让 τ_eff 更小（响应更快）。
        """
        if state_dim <= 0:
            raise ValueError(f"[ERROR] state_dim 必须为正，实际 state_dim={state_dim}")
        if state_dim < len(_NEED_KEYS):
            raise ValueError(
                f"[ERROR] state_dim 至少为 {len(_NEED_KEYS)}（需容纳 5 维需求解码），"
                f"实际 state_dim={state_dim}"
            )

        self.state_dim = int(state_dim)
        # 内嵌 CfCCell 作为动力学核心
        # use_input_gate=True 时：生成 W_gate (hidden_dim, input_dim) 的 Xavier 初始化
        # use_input_gate=True 时：生成 W_gate (hidden_dim, input_dim) 的 Xavier 初始化
        _rng = np.random.default_rng(seed)
        W_gate = _xavier_init((self.state_dim, _INPUT_DIM), _rng) if use_input_gate else None
        self.cfc = CfCCell(input_dim=_INPUT_DIM, hidden_dim=self.state_dim, seed=seed, W_gate=W_gate)
        # 零初始化隐状态
        self.h: np.ndarray = np.zeros(self.state_dim, dtype=np.float64)
        # 最近一次演化时间戳
        self.last_t: float = time.time()
        # 最近一次输入（默认零向量），供 step(t_now) 使用
        self._last_inputs: np.ndarray = np.zeros(_INPUT_DIM, dtype=np.float64)

        logger.debug(
            f"[INFO] LiquidBusField 初始化: state_dim={self.state_dim}, cfc={self.cfc!r}"
        )

    # ── 演化 ────────────────────────────────────────────────────

    def evolve(self, inputs: np.ndarray, t_now: float) -> np.ndarray:
        """按真实 Δt = t_now - last_t 演化一步隐状态。

        参数：
            inputs : 10 维输入向量（需求增量 + 情感信号）
            t_now  : 当前时间戳（秒）

        返回：
            new_h : 演化后的隐状态 (state_dim,)

        若 t_now <= last_t（时间未推进或倒流），直接返回当前 h 不演化，
        并更新 last_t 以避免后续 Δt 累积异常。
        """
        inputs = np.asarray(inputs, dtype=np.float64)
        if inputs.shape != (_INPUT_DIM,):
            raise ValueError(
                f"[ERROR] inputs 形状应为 ({_INPUT_DIM},)，实际 {inputs.shape}"
            )

        dt = float(t_now) - float(self.last_t)
        if dt < 0.0:
            # 时间倒流：保守处理，不演化，仅更新时间戳
            logger.warning(
                f"[WARN] t_now < last_t（{t_now} < {self.last_t}），跳过本次演化"
            )
            self.last_t = float(t_now)
            return self.h.copy()
        if dt == 0.0:
            # 时间未推进：保持现状
            return self.h.copy()

        # CfCCell 半隐式演化
        self.h = self.cfc.forward(self.h, inputs, dt=dt)
        self.last_t = float(t_now)
        self._last_inputs = inputs.copy()
        return self.h.copy()

    def step(self, t_now: float) -> np.ndarray:
        """单参演化接口（供 LiquidCognitiveCore.evolve_all 自动调度）。

        使用最近一次 evolve 的输入（或默认零向量）演化一步。
        """
        return self.evolve(self._last_inputs, t_now)

    # ── 解码 ────────────────────────────────────────────────────

    def decode_needs(self) -> Dict[str, float]:
        """从 h(t) 的前 5 维经 sigmoid 解码为 PSI 五需求字典。

        返回：
            dict ：``{competence, autonomy, relatedness, certainty, growth}``，
            值域 (0, 1)（sigmoid 输出经裁剪到 [1e-6, 1-1e-6]）。
        """
        # 取前 5 维
        h5 = self.h[: len(_NEED_KEYS)]
        # sigmoid 压缩到 (0, 1)
        # 使用数值稳定 sigmoid（与 neurons._sigmoid 一致）
        needs_vals = self._sigmoid(h5)
        return {key: float(v) for key, v in zip(_NEED_KEYS, needs_vals)}

    def decode(self) -> Dict[str, float]:
        """通用 decode 接口（与 decode_needs 等价，供容器鸭子类型调用）。"""
        return self.decode_needs()

    # ── 编码 ────────────────────────────────────────────────────

    def encode_inputs(
        self,
        need_deltas: Optional[Dict[str, float]] = None,
        emotion_signals: Optional[np.ndarray] = None,
    ) -> np.ndarray:
        """将需求增量 + 情感信号编码为 10 维输入向量。

        布局：
            [0..4] : PSI 五需求增量（competence, autonomy, relatedness, certainty, growth）
            [5..9] : 情感信号（5 维）

        参数：
            need_deltas     : 需求增量字典，键为五需求名，值为 float（可正可负）；
                             缺失键按 0.0 处理。
            emotion_signals : 5 维情感信号向量；None 时全零。

        返回：
            inputs : 10 维 np.ndarray
        """
        inputs = np.zeros(_INPUT_DIM, dtype=np.float64)

        # 前 5 维：需求增量
        if need_deltas is not None:
            for i, key in enumerate(_NEED_KEYS):
                if key in need_deltas:
                    inputs[i] = float(need_deltas[key])

        # 后 5 维：情感信号
        if emotion_signals is not None:
            emo = np.asarray(emotion_signals, dtype=np.float64).flatten()
            if emo.shape[0] < 5:
                # 不足 5 维时右侧补零
                emo = np.pad(emo, (0, 5 - emo.shape[0]), mode="constant")
            inputs[5:10] = emo[:5]

        return inputs

    # ── 查询 ────────────────────────────────────────────────────

    def get_tau(self) -> float:
        """返回当前 CfCCell 的有效时间常数（标量，取每维均值）。

        CfCCell.get_tau_effective 返回 (hidden_dim,) 向量，这里取均值
        作为整体时间尺度的标量摘要。
        """
        tau_vec = self.cfc.get_tau_effective()
        return float(np.mean(tau_vec))

    def get_h_summary(self) -> Dict[str, float]:
        """返回当前 h(t) 的摘要字典。

        返回：
            {"h_norm": float, "h_dim": int, "tau": float}
        """
        return {
            "h_norm": float(np.linalg.norm(self.h)),
            "h_dim": int(self.state_dim),
            "tau": self.get_tau(),
        }

    # ── 内部工具 ────────────────────────────────────────────────

    @staticmethod
    def _sigmoid(x: np.ndarray) -> np.ndarray:
        """数值稳定的 sigmoid，输出裁剪到 [1e-6, 1-1e-6]。

        与 laap.liquid.neurons._sigmoid 实现一致，避免跨模块私有导入。
        """
        out = np.where(
            x >= 0,
            1.0 / (1.0 + np.exp(-np.clip(x, -50.0, 50.0))),
            np.exp(np.clip(x, -50.0, 50.0)) / (1.0 + np.exp(np.clip(x, -50.0, 50.0))),
        )
        return np.clip(out, 1e-6, 1.0 - 1e-6)

    def __repr__(self) -> str:
        return (
            f"LiquidBusField(state_dim={self.state_dim}, "
            f"h_norm={np.linalg.norm(self.h):.4f}, tau={self.get_tau():.4f})"
        )
