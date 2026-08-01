"""LAAP Liquid — LTC 因果反事实模拟器 (Task 11)

用 LTCCell 的有界动力学（论文 Section 4 证明状态有界）模拟干预后的
世界状态演化。将世界状态编码为向量，干预作为输入信号，LTC 积分得到
未来轨迹。

设计要点：
  - LTC 的半隐式欧拉离散化对任意 dt > 0 都不会发散（见 neurons.py 注释）
  - 稳态 h* = tau_eff * drive，其中 drive = A * sigmoid(W@x+b) ∈ (0, 1)，
    tau_eff = tau_sys / (1 + tau_sys * f(x)) ∈ (tau_sys/(1+tau_sys), tau_sys)。
    故 h* 的每个分量 ∈ [0, tau_sys]，整体范数有上界 sqrt(state_dim) * tau_sys。
  - 反事实轨迹的有界性判据：所有步 ||h|| <= ||h_initial|| * 2，
    其中 h_initial 是干预后轨迹起点的隐状态。

本模块**不** import laap.agi.causal.py，使用自己的接口，避免循环依赖。

LAAP 日志风格：[OK]/[INFO]/[WARN]/[ERROR]。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

import numpy as np

from laap.liquid.neurons import LTCCell

logger = logging.getLogger("laap.liquid.causal_simulator")


# ════════════════════════════════════════════════════════════════════
# LiquidCausalSimulator — LTC 因果反事实模拟器
# ════════════════════════════════════════════════════════════════════

class LiquidCausalSimulator:
    """LTC 因果反事实模拟器。

    用 LTCCell 的有界动力学模拟"如果施加某干预，世界状态会如何演化"。

    核心思路：
      1. 将世界状态 dict 编码为 state_dim 向量 h0
      2. 将干预 dict 编码为 action_dim 输入信号 x，并对 h0 施加扰动
         得到 h_intervened（反事实起点）
      3. 以 x 为持续输入，按 dt 步长积分 LTC，得到未来轨迹
      4. 轨迹中每步记录 (t, 解码状态, 范数)，并检查有界性

    属性：
        state_dim  : 世界状态向量维度（LTC 隐状态维度）
        action_dim : 干预/动作向量维度（LTC 输入维度）
        cell       : LTCCell 实例
    """

    # 干预扰动的缩放系数，保证 ||h_intervened|| 不会远超 ||h0||
    _INTERVENTION_SCALE = 0.1

    def __init__(self, state_dim: int = 16, action_dim: int = 8) -> None:
        if state_dim <= 0 or action_dim <= 0:
            raise ValueError(
                f"[ERROR] 维度必须为正：state_dim={state_dim}, action_dim={action_dim}"
            )

        self.state_dim = int(state_dim)
        self.action_dim = int(action_dim)

        # tau_sys=2.0 让模拟有适度记忆（论文建议 tau_sys ~ 1-3）
        self.cell = LTCCell(
            input_dim=self.action_dim,
            hidden_dim=self.state_dim,
            tau_sys=2.0,
            seed=42,
        )

        # 编码/解码时缓存的字段顺序与非数值字段原值
        self._last_keys: List[str] = []
        self._last_non_numeric: Dict[str, Any] = {}

        logger.debug(
            f"[INFO] LiquidCausalSimulator 初始化: state_dim={state_dim}, "
            f"action_dim={action_dim}, tau_sys=2.0"
        )

    # ── 状态编码/解码 ──────────────────────────────────────────────

    def encode_state(self, world_state: dict) -> np.ndarray:
        """将世界状态 dict 编码为 state_dim 向量。

        编码规则：
          - 数值字段 (int/float) 直接转 float
          - 布尔字段转 1.0/0.0
          - 字符串字段用简单哈希映射到 [0, 1]（解码时从缓存恢复原值）
          - 其他类型记为 0.0
          - 拼接后 padding/截断到 state_dim

        副作用：缓存字段顺序到 self._last_keys，非数值字段原值到
        self._last_non_numeric，供后续 decode_state 使用。
        """
        keys = list(world_state.keys())
        self._last_keys = keys
        self._last_non_numeric = {}

        vals: List[float] = []
        for k in keys:
            v = world_state[k]
            if isinstance(v, bool):
                vals.append(1.0 if v else 0.0)
            elif isinstance(v, (int, float)):
                vals.append(float(v))
            elif isinstance(v, str):
                # 字符串哈希到 [0, 1]，原值缓存以便解码恢复
                self._last_non_numeric[k] = v
                h = float(sum(ord(c) for c in v) % 100) / 100.0
                vals.append(h)
            else:
                self._last_non_numeric[k] = v
                vals.append(0.0)

        vec = np.asarray(vals, dtype=np.float64)
        if vec.size < self.state_dim:
            vec = np.pad(vec, (0, self.state_dim - vec.size))
        elif vec.size > self.state_dim:
            vec = vec[: self.state_dim]
        return vec.astype(np.float64)

    def decode_state(self, h: np.ndarray) -> dict:
        """将 h 解码回世界状态 dict。

        使用最近一次 encode_state 缓存的字段顺序：
          - 非数值字段从缓存恢复原值
          - 数值字段直接读 h[i]

        若未调用过 encode_state，返回空 dict。
        """
        if not self._last_keys:
            return {}

        h = np.asarray(h, dtype=np.float64)
        result: Dict[str, Any] = {}
        for i, k in enumerate(self._last_keys):
            if i < h.size:
                if k in self._last_non_numeric:
                    result[k] = self._last_non_numeric[k]
                else:
                    result[k] = float(h[i])
            else:
                # h 维度不足，用 0 填充
                result[k] = 0.0
        return result

    # ── 干预 ──────────────────────────────────────────────────────

    def _encode_intervention(self, intervention: dict) -> np.ndarray:
        """将干预 dict 编码为 action_dim 输入向量。

        编码规则同 encode_state，但目标维度为 action_dim，
        并归一化到 ||x|| <= 1.0 以保证 LTC 输入幅度受控。
        """
        vals: List[float] = []
        for v in intervention.values():
            if isinstance(v, bool):
                vals.append(1.0 if v else 0.0)
            elif isinstance(v, (int, float)):
                vals.append(float(v))
            elif isinstance(v, str):
                h = float(sum(ord(c) for c in v) % 100) / 100.0
                vals.append(h)
            else:
                vals.append(0.0)

        vec = np.asarray(vals, dtype=np.float64)
        if vec.size < self.action_dim:
            vec = np.pad(vec, (0, self.action_dim - vec.size))
        elif vec.size > self.action_dim:
            vec = vec[: self.action_dim]

        # 归一化到单位球内，防止输入幅度过大导致 LTC 饱和
        norm = float(np.linalg.norm(vec))
        if norm > 1.0:
            vec = vec / norm
        return vec.astype(np.float64)

    def apply_intervention(self, h: np.ndarray, intervention: dict) -> np.ndarray:
        """对 h 施加干预，返回干预后的隐状态。

        将干预 dict 编码为 action_dim 输入向量 x，再将 x 投影到 state_dim
        并乘以小尺度系数作为扰动项：
            h_intervened = h + scale * x_padded_to_state_dim

        scale=_INTERVENTION_SCALE 确保 ||h_intervened|| 不会远超 ||h||。
        """
        x = self._encode_intervention(intervention)
        effect = np.zeros(self.state_dim, dtype=np.float64)
        n = min(self.state_dim, self.action_dim)
        effect[:n] = x[:n] * self._INTERVENTION_SCALE
        return np.asarray(h, dtype=np.float64) + effect

    # ── 反事实模拟 ────────────────────────────────────────────────

    def counterfactual(
        self,
        world_state: dict,
        intervention: dict,
        horizon: float = 10.0,
        dt: float = 0.1,
    ) -> List[dict]:
        """反事实模拟：施加 intervention 后，世界状态在 [0, horizon] 上如何演化。

        步骤：
          1. 编码 world_state → h0
          2. 施加 intervention → h_intervened（轨迹起点）
          3. 编码 intervention → x（LTC 持续输入）
          4. 从 t=0 到 horizon 按 dt 步长积分 LTC
          5. 每步记录 (t, 解码状态, 范数)
          6. 有界性检查：所有 ||h|| <= 2 * ||h_intervened||，
             若违反记录 [WARN] 但不 crash

        参数：
            world_state  : 初始世界状态 dict
            intervention : 干预 dict（编码为 LTC 输入信号）
            horizon      : 模拟总时长
            dt           : 积分步长

        返回：
            [{"t": float, "state": dict, "norm": float}, ...]
            包含 t=0 和 t=horizon，共 int(horizon/dt)+1 个点。
        """
        if dt <= 0:
            raise ValueError(f"[ERROR] dt 必须为正，实际 dt={dt}")
        if horizon < 0:
            raise ValueError(f"[ERROR] horizon 必须非负，实际 horizon={horizon}")

        # 1. 编码初始状态
        h0 = self.encode_state(world_state)

        # 2. 施加干预得到反事实起点
        h = self.apply_intervention(h0, intervention)

        # 3. 编码干预为 LTC 输入信号
        x = self._encode_intervention(intervention)

        # 4. 积分 LTC
        n_steps = int(round(horizon / dt))
        trajectory: List[dict] = []

        for i in range(n_steps + 1):
            t = float(i * dt)
            norm = float(np.linalg.norm(h))
            trajectory.append({
                "t": t,
                "state": self.decode_state(h),
                "norm": norm,
            })
            if i < n_steps:
                h = self.cell.forward(h, x, dt)

        # 5. 有界性检查（软断言：违反只记录 warning）
        if not self.is_bounded(trajectory):
            max_norm = max(p["norm"] for p in trajectory)
            init_norm = trajectory[0]["norm"] if trajectory else 0.0
            logger.warning(
                f"[WARN] 反事实轨迹违反有界性：max||h||={max_norm:.4f} > "
                f"2*||h_init||={2.0 * init_norm:.4f}（horizon={horizon}, dt={dt}）"
            )
        else:
            logger.debug(
                f"[OK] 反事实轨迹有界：max||h||={max(p['norm'] for p in trajectory):.4f} "
                f"<= 2*||h_init||={2.0 * trajectory[0]['norm']:.4f}"
            )

        return trajectory

    # ── 有界性检查 ────────────────────────────────────────────────

    def is_bounded(self, trajectory: List[dict]) -> bool:
        """检查轨迹所有状态的范数 <= 初始范数 × 2。

        参数：
            trajectory : counterfactual 返回的轨迹列表

        返回：
            True 如果所有点 ||h|| <= 2 * ||h_initial||
            （||h_initial|| = trajectory[0]["norm"]）

        边界情况：
            - 空轨迹返回 True
            - 初始范数为 0 时，要求所有点范数也为 0
        """
        if not trajectory:
            return True

        initial_norm = trajectory[0]["norm"]
        if initial_norm <= 0.0:
            # 初始为零向量：任何非零演化都视为违反
            return all(p["norm"] <= 1e-9 for p in trajectory)

        bound = 2.0 * initial_norm
        # 加一个微小容差，避免浮点比较误报
        tol = 1e-9
        return all(p["norm"] <= bound + tol for p in trajectory)

    def __repr__(self) -> str:
        return (
            f"LiquidCausalSimulator(state_dim={self.state_dim}, "
            f"action_dim={self.action_dim}, tau_sys={self.cell.tau_sys:.2f})"
        )
