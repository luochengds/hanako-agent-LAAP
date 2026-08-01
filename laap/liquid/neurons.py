"""LAAP Liquid Neurons — LTC / CfC / NCP 神经元（纯 numpy 实现）

本模块实现三种液态神经网络神经元/回路，全部用 numpy 完成，不依赖 torch：
  - LTCCell      : Liquid Time-Constant 神经元（Hasani et al., AAAI-21, Eq.1）
  - CfCCell      : Closed-form Continuous-depth 神经元（Lechner et al., Nature MI 2022）
  - NCPCircuit   : Neural Circuit Policy 回路（C. elegans 19 神经元布线）

核心思想：
  所有神经元都用"输入驱动的可变时间常数 τ(t)"演化连续时间 ODE，
  这使得它们能在任意 dt（含不规则时间间隔）上保持稳定，并天然支持
  LAAP 事件驱动认知循环中的不规则时间步。

数值稳定性策略：
  - sigmoid 输出裁剪到 [1e-6, 1-1e-6]，避免饱和区梯度消失/除零
  - 隐状态 h 裁剪到 [-1e3, 1e3]，防止数值爆炸
  - 权重用 He / Xavier 初始化，方差不爆炸

LAAP 日志风格：使用 [OK]/[INFO]/[WARN]/[ERROR] 标签。
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np

logger = logging.getLogger("laap.liquid.neurons")

# ── 数值稳定性常数 ──────────────────────────────────────────────────
_SIGMOID_EPS = 1e-6          # sigmoid 裁剪下界（上界为 1 - 1e-6）
_H_CLIP = 1e3                # 隐状态裁剪上界（下界为 -1e3）
_H_INIT_SCALE = 0.1          # 默认隐状态初始化标准差


# ════════════════════════════════════════════════════════════════════
# 通用工具函数
# ════════════════════════════════════════════════════════════════════

def _sigmoid(x: np.ndarray) -> np.ndarray:
    """数值稳定的 sigmoid，输出裁剪到 [1e-6, 1-1e-6]。"""
    # 用 np.where 避免大正数 exp 溢出
    out = np.where(
        x >= 0,
        1.0 / (1.0 + np.exp(-np.clip(x, -50.0, 50.0))),
        np.exp(np.clip(x, -50.0, 50.0)) / (1.0 + np.exp(np.clip(x, -50.0, 50.0))),
    )
    return np.clip(out, _SIGMOID_EPS, 1.0 - _SIGMOID_EPS)


def _tanh(x: np.ndarray) -> np.ndarray:
    """数值稳定的 tanh（numpy 内建已足够稳定，这里统一入口便于维护）。"""
    return np.tanh(np.clip(x, -50.0, 50.0))


def _situ_glu(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """SiTU-GLU 激活函数（Kimi K3 启发，实验性）。

    SiTU-GLU(x, y) = sigmoid(x) * tanh(y)

    相比标准 sigmoid 门控，tanh(y) 的输出值域为 [-1, 1]，
    允许负向调制而非完全抑制。适合需要锐利门控边界的场景，
    例如注意力焦点切换和情感涌现消退边界。

    参数：
        x : 门控输入（任意 shape）
        y : 调制输入（与 x 同 shape）

    返回：
        sigmoid(x) * tanh(y)，与输入同 shape
    """
    return _sigmoid(x) * _tanh(y)


def _clip_h(h: np.ndarray) -> np.ndarray:
    """裁剪隐状态到 [-1e3, 1e3]，防止数值爆炸。"""
    return np.clip(h, -_H_CLIP, _H_CLIP)


def _xavier_init(shape: tuple[int, ...], rng: np.random.Generator) -> np.ndarray:
    """Xavier/Glorot 初始化，适合 sigmoid/tanh 激活。"""
    fan_in = shape[0] if len(shape) == 1 else shape[1]
    fan_out = shape[0] if len(shape) == 1 else shape[0]
    limit = np.sqrt(6.0 / (fan_in + fan_out))
    return rng.uniform(-limit, limit, size=shape).astype(np.float64)


def _he_init(shape: tuple[int, ...], rng: np.random.Generator) -> np.ndarray:
    """He 初始化，适合 ReLU 类激活（这里保留作为可选）。"""
    fan_in = shape[1] if len(shape) == 2 else shape[0]
    std = np.sqrt(2.0 / fan_in)
    return (rng.standard_normal(shape) * std).astype(np.float64)


# ════════════════════════════════════════════════════════════════════
# LTCCell — Liquid Time-Constant 神经元
# ════════════════════════════════════════════════════════════════════

class LTCCell:
    """Liquid Time-Constant 神经元（Hasani et al., AAAI-21, Eq.1）

    ODE 形式：
        dh/dt = −[1/τ_sys + f₁(x, I, θ)] · h + A · f₂(x, I, θ)

    本实现采用简化但保真的形式：
        - 时间常数调制：f(x) = sigmoid(W @ x)
        - 有效时间常数：τ_eff = τ_sys / (1 + τ_sys * f(x))
                          → f(x) 大（强输入）时 τ_eff 小（响应快）
                          → f(x) 小（弱输入）时 τ_eff 大（记忆长）
        - 演化目标状态：A * sigmoid(W @ x) 作为驱动项
        - forward 用融合显式-隐式（半隐式欧拉）法积分 dt 时间：
              h_new = h + dt * ( -h / τ_eff + A * sigmoid(W @ x) )
          这是稳定的一阶近似；对大 dt 仍受 _clip_h 保护。

    属性：
        τ_sys       : 系统基础时间常数（float, 默认 1.0）
        input_dim   : 输入维度 I
        hidden_dim  : 隐状态维度 H
        W           : 输入权重矩阵 (hidden_dim, input_dim)
        A           : 驱动幅度向量 (hidden_dim,)
        b           : 偏置 (hidden_dim,) —— 用于 f(x) 的输入驱动调制
    """

    def __init__(
        self,
        input_dim: int,
        hidden_dim: int,
        tau_sys: float = 1.0,
        *,
        W: Optional[np.ndarray] = None,
        A: Optional[np.ndarray] = None,
        b: Optional[np.ndarray] = None,
        seed: Optional[int] = None,
    ) -> None:
        if input_dim <= 0 or hidden_dim <= 0:
            raise ValueError(f"[ERROR] LTCCell 维度必须为正：input_dim={input_dim}, hidden_dim={hidden_dim}")
        if tau_sys <= 0:
            raise ValueError(f"[ERROR] tau_sys 必须为正：tau_sys={tau_sys}")

        self.input_dim = int(input_dim)
        self.hidden_dim = int(hidden_dim)
        self.tau_sys = float(tau_sys)

        rng = np.random.default_rng(seed)

        # 输入权重 W (hidden_dim, input_dim)，Xavier 初始化（配合 sigmoid）
        if W is not None:
            W = np.asarray(W, dtype=np.float64)
            if W.shape != (self.hidden_dim, self.input_dim):
                raise ValueError(f"[ERROR] W 形状应为 ({self.hidden_dim},{self.input_dim})，实际 {W.shape}")
            self.W = W
        else:
            self.W = _xavier_init((self.hidden_dim, self.input_dim), rng)

        # 驱动幅度 A (hidden_dim,)，初始化为正小值保证有驱动力
        if A is not None:
            A = np.asarray(A, dtype=np.float64)
            if A.shape != (self.hidden_dim,):
                raise ValueError(f"[ERROR] A 形状应为 ({self.hidden_dim},)，实际 {A.shape}")
            self.A = A
        else:
            self.A = np.ones(self.hidden_dim, dtype=np.float64)

        # 偏置 b (hidden_dim,)
        if b is not None:
            b = np.asarray(b, dtype=np.float64)
            if b.shape != (self.hidden_dim,):
                raise ValueError(f"[ERROR] b 形状应为 ({self.hidden_dim},)，实际 {b.shape}")
            self.b = b
        else:
            self.b = np.zeros(self.hidden_dim, dtype=np.float64)

        # 记录最近一次 forward 计算的有效时间常数（供 get_tau_effective 查询）
        self._last_tau_eff: np.ndarray = np.full(self.hidden_dim, self.tau_sys, dtype=np.float64)

        logger.debug(
            f"[INFO] LTCCell 初始化: input_dim={input_dim}, hidden_dim={hidden_dim}, "
            f"tau_sys={tau_sys}"
        )

    # ── 核心数学 ──────────────────────────────────────────────────

    def _f_input(self, x: np.ndarray) -> np.ndarray:
        """输入驱动的时间常数调制项 f(x) = sigmoid(W @ x + b)。

        返回值域 (1e-6, 1-1e-6)，shape=(hidden_dim,)。
        """
        return _sigmoid(self.W @ x + self.b)

    def compute_tau_effective(self, x: np.ndarray) -> np.ndarray:
        """计算输入 x 对应的有效时间常数向量 τ_eff。

            τ_eff = τ_sys / (1 + τ_sys * f(x))

        强输入（f(x) 大）→ τ_eff 小 → 响应快
        弱输入（f(x) 小）→ τ_eff 大 → 记忆长

        返回 shape=(hidden_dim,) 的正实数向量。
        """
        f = self._f_input(x)
        tau_eff = self.tau_sys / (1.0 + self.tau_sys * f)
        # 保证严格正
        return np.maximum(tau_eff, 1e-8)

    def get_tau_effective(self) -> np.ndarray:
        """返回最近一次 forward 使用过的有效时间常数向量。"""
        return self._last_tau_eff.copy()

    # ── 前向演化 ──────────────────────────────────────────────────

    def forward(self, h: np.ndarray, x: np.ndarray, dt: float) -> np.ndarray:
        """用半隐式欧拉法积分 ODE dt 时间，返回新的隐状态。

        参数：
            h  : 隐状态 (hidden_dim,)
            x  : 输入 (input_dim,)
            dt : 积分步长（任意正实数，支持不规则时间间隔）

        返回：
            new_h : 新隐状态 (hidden_dim,)
        """
        if dt < 0:
            raise ValueError(f"[ERROR] dt 必须非负，实际 dt={dt}")

        h = np.asarray(h, dtype=np.float64)
        x = np.asarray(x, dtype=np.float64)
        if h.shape != (self.hidden_dim,):
            raise ValueError(f"[ERROR] h 形状应为 ({self.hidden_dim},)，实际 {h.shape}")
        if x.shape != (self.input_dim,):
            raise ValueError(f"[ERROR] x 形状应为 ({self.input_dim},)，实际 {x.shape}")

        if dt == 0.0:
            return _clip_h(h)

        # 输入驱动项
        f = self._f_input(x)
        # 有效时间常数
        tau_eff = self.tau_sys / (1.0 + self.tau_sys * f)
        tau_eff = np.maximum(tau_eff, 1e-8)
        self._last_tau_eff = tau_eff

        # 驱动目标：A * sigmoid(W @ x) —— 与 f 同源以保证符号一致
        drive = self.A * f

        # 半隐式欧拉（隐式处理 -h/τ_eff 项，显式处理 drive 项）：
        #   dh/dt = -h/τ_eff + drive
        #   (h_new - h)/dt = -h_new/τ_eff + drive
        #   h_new * (1 + dt/τ_eff) = h + dt * drive
        #   h_new = (h + dt * drive) / (1 + dt/τ_eff)
        # 这是 LTC/CfC 类网络常用的稳定离散化，对任意 dt > 0 都不会发散。
        alpha = dt / tau_eff  # shape=(hidden_dim,)
        new_h = (h + dt * drive) / (1.0 + alpha)
        return _clip_h(new_h.astype(np.float64))

    # ── 工具 ──────────────────────────────────────────────────────

    def default_state(self) -> np.ndarray:
        """返回一个零初始化的隐状态。"""
        return np.zeros(self.hidden_dim, dtype=np.float64)

    def __repr__(self) -> str:
        return (
            f"LTCCell(input_dim={self.input_dim}, hidden_dim={self.hidden_dim}, "
            f"tau_sys={self.tau_sys:.4f})"
        )


# ════════════════════════════════════════════════════════════════════
# CfCCell — Closed-form Continuous-depth 神经元
# ════════════════════════════════════════════════════════════════════

class CfCCell:
    """Closed-form Continuous-depth 神经元（Lechner et al., Nature MI 2022）

    CfC 是 LTC ODE 的闭合式解，无需 ODE 求解器即可一步前向：

        h(t+Δt) = σ(−W_τ · Δt) ⊙ h(t) + (1 − σ(−W_τ · Δt)) ⊙ h̃(t)

    其中显式目标状态：
        h̃(t) = tanh(W_h @ x + W_hh @ h + b_h)

    关键特性：
        - dt 是任意正实数，原生支持不规则时间间隔
        - σ(−W_τ · Δt) 是"记忆保留比例"：dt 大 → 趋近 0（遗忘旧状态）；
          dt 小 → 趋近 1（保留旧状态）。W_τ 控制每个维度的遗忘速度。
        - 单次前向，无迭代，计算量与 MLP 相当

    属性：
        input_dim   : 输入维度 I
        hidden_dim  : 隐状态维度 H
        W_h         : 输入→隐层权重 (hidden_dim, input_dim)
        W_hh        : 隐层→隐层权重 (hidden_dim, hidden_dim)
        b_h         : 偏置 (hidden_dim,)
        W_tau       : 每维度的时间常数倒数 (hidden_dim,)，正实数
    """

    def __init__(
        self,
        input_dim: int,
        hidden_dim: int,
        tau: float = 1.0,
        *,
        W_h: Optional[np.ndarray] = None,
        W_hh: Optional[np.ndarray] = None,
        b_h: Optional[np.ndarray] = None,
        W_tau: Optional[np.ndarray] = None,
        W_gate: Optional[np.ndarray] = None,  # K3 启发：输入依赖门控权重 (hidden_dim, input_dim)
        seed: Optional[int] = None,
    ) -> None:
        if input_dim <= 0 or hidden_dim <= 0:
            raise ValueError(f"[ERROR] CfCCell 维度必须为正：input_dim={input_dim}, hidden_dim={hidden_dim}")
        if tau <= 0:
            raise ValueError(f"[ERROR] tau 必须为正：tau={tau}")

        self.input_dim = int(input_dim)
        self.hidden_dim = int(hidden_dim)
        self.tau = float(tau)

        rng = np.random.default_rng(seed)

        # W_h (hidden_dim, input_dim) —— Xavier（tanh 输出）
        if W_h is not None:
            W_h = np.asarray(W_h, dtype=np.float64)
            if W_h.shape != (self.hidden_dim, self.input_dim):
                raise ValueError(f"[ERROR] W_h 形状应为 ({self.hidden_dim},{self.input_dim})，实际 {W_h.shape}")
            self.W_h = W_h
        else:
            self.W_h = _xavier_init((self.hidden_dim, self.input_dim), rng)

        # W_hh (hidden_dim, hidden_dim) —— Xavier
        if W_hh is not None:
            W_hh = np.asarray(W_hh, dtype=np.float64)
            if W_hh.shape != (self.hidden_dim, self.hidden_dim):
                raise ValueError(f"[ERROR] W_hh 形状应为 ({self.hidden_dim},{self.hidden_dim})，实际 {W_hh.shape}")
            self.W_hh = W_hh
        else:
            self.W_hh = _xavier_init((self.hidden_dim, self.hidden_dim), rng)

        # b_h (hidden_dim,)
        if b_h is not None:
            b_h = np.asarray(b_h, dtype=np.float64)
            if b_h.shape != (self.hidden_dim,):
                raise ValueError(f"[ERROR] b_h 形状应为 ({self.hidden_dim},)，实际 {b_h.shape}")
            self.b_h = b_h
        else:
            self.b_h = np.zeros(self.hidden_dim, dtype=np.float64)

        # W_tau (hidden_dim,) —— 每维时间常数倒数，初始化为 1/tau
        if W_tau is not None:
            W_tau = np.asarray(W_tau, dtype=np.float64)
            if W_tau.shape != (self.hidden_dim,):
                raise ValueError(f"[ERROR] W_tau 形状应为 ({self.hidden_dim},)，实际 {W_tau.shape}")
            self.W_tau = W_tau
        else:
            self.W_tau = np.full(self.hidden_dim, 1.0 / self.tau, dtype=np.float64)

        # W_gate (hidden_dim, input_dim) —— K3 启发：输入依赖门控权重
        # 当不为 None 时，门控变为 r = sigmoid(-W_tau * dt) * sigmoid(W_gate @ x)
        if W_gate is not None:
            W_gate = np.asarray(W_gate, dtype=np.float64)
            if W_gate.shape != (self.hidden_dim, self.input_dim):
                raise ValueError(f"[ERROR] W_gate 形状应为 ({self.hidden_dim},{self.input_dim})，实际 {W_gate.shape}")
            self.W_gate = W_gate
        else:
            self.W_gate = None

        # 最近一次 forward 的有效时间常数（每维 τ_eff = 1/W_tau）
        self._last_tau_eff: np.ndarray = 1.0 / self.W_tau

        logger.debug(
            f"[INFO] CfCCell 初始化: input_dim={input_dim}, hidden_dim={hidden_dim}, tau={tau}, "
            f"W_gate={'set' if W_gate is not None else 'None'}"
        )

    # ── 核心数学 ──────────────────────────────────────────────────

    def _target_state(self, h: np.ndarray, x: np.ndarray) -> np.ndarray:
        """计算显式目标状态 h̃(t) = tanh(W_h @ x + W_hh @ h + b_h)。"""
        return _tanh(self.W_h @ x + self.W_hh @ h + self.b_h)

    def get_tau_effective(self) -> np.ndarray:
        """返回每维的有效时间常数 τ_eff = 1/W_tau。

        CfC 的时间常数是输入无关的（由 W_tau 固定），但为了与 LTC 接口一致，
        仍提供此方法。返回 shape=(hidden_dim,)。
        """
        return self._last_tau_eff.copy()

    # ── 前向演化 ──────────────────────────────────────────────────

    def forward(self, h: np.ndarray, x: np.ndarray, dt: float) -> np.ndarray:
        """单步前向，返回新隐状态。

        参数：
            h  : 隐状态 (hidden_dim,)
            x  : 输入 (input_dim,)
            dt : 任意正实数步长

        返回：
            new_h : 新隐状态 (hidden_dim,)

        数学（基础版，W_gate=None）：
            new_h = σ(−W_τ · Δt) ⊙ h + (1 − σ(−W_τ · Δt)) ⊙ h̃

        数学（输入依赖版，W_gate 已设置）：
            r_time = σ(−W_τ · Δt)             — 时间依赖遗忘
            r_input = σ(W_gate @ x)            — K3 启发：输入依赖门控
            r = r_time * r_input               — 组合门控
            new_h = r ⊙ h + (1 − r) ⊙ h̃
        """
        if dt < 0:
            raise ValueError(f"[ERROR] dt 必须非负，实际 dt={dt}")

        h = np.asarray(h, dtype=np.float64)
        x = np.asarray(x, dtype=np.float64)
        if h.shape != (self.hidden_dim,):
            raise ValueError(f"[ERROR] h 形状应为 ({self.hidden_dim},)，实际 {h.shape}")
        if x.shape != (self.input_dim,):
            raise ValueError(f"[ERROR] x 形状应为 ({self.input_dim},)，实际 {x.shape}")

        if dt == 0.0:
            return _clip_h(h)

        # 时间依赖遗忘比例 r_time = σ(-W_tau * dt) ∈ (0,1)
        r_time = _sigmoid(-self.W_tau * dt)

        # K3 启发：输入依赖门控
        # 公式：r = σ(-W_tau · dt) * σ(-W_gate @ x)
        # 推理：强输入信号 → -W_gate @ x 为负 → σ(负) 小 → r 小 → 更新多（遗忘旧状态）
        #       弱输入信号 → -W_gate @ x 接近 0 → σ(0)≈0.5 → 适度保留
        if self.W_gate is not None:
            r_input = _sigmoid(-(self.W_gate @ x))    # (hidden_dim,)，每维依赖输入
            r = r_time * r_input                      # 组合门控
        else:
            r = r_time

        h_tilde = self._target_state(h, x)            # 显式目标状态
        new_h = r * h + (1.0 - r) * h_tilde
        return _clip_h(new_h.astype(np.float64))

    # ── 工具 ──────────────────────────────────────────────────────

    def default_state(self) -> np.ndarray:
        """返回一个零初始化的隐状态。"""
        return np.zeros(self.hidden_dim, dtype=np.float64)

    def __repr__(self) -> str:
        return (
            f"CfCCell(input_dim={self.input_dim}, hidden_dim={self.hidden_dim}, "
            f"tau={self.tau:.4f})"
        )


# ════════════════════════════════════════════════════════════════════
# NCPCircuit — Neural Circuit Policy（C. elegans 19 神经元布线）
# ════════════════════════════════════════════════════════════════════

class NCPCircuit:
    """Neural Circuit Policy 回路（Lechner et al., Nature MI 2020）

    基于 C. elegans 线虫神经回路布线的 19 神经元网络：
        - 感觉神经元 sensory  : 4 个   (索引 0..3)
        - 中间神经元 inter    : 6 个   (索引 4..9)
        - 命令神经元 command  : 4 个   (索引 10..13，含循环连接)
        - 运动神经元 motor    : 5 个   (索引 14..18)

    信号流向：sensory → inter → command → motor
    命令神经元之间有循环连接（自反馈 + 互相抑制/兴奋），用于产生持续振荡。

    每个神经元用 CfCCell 作为动力学（19 个独立的 1 维 CfC 单元），
    神经元之间通过稀疏突触权重矩阵传播信号。

    forward 按层级顺序传播：
        1. 感觉神经元接收外部输入 x (维度 = 4)
        2. 中间神经元接收感觉神经元的输出
        3. 命令神经元接收中间神经元的输出 + 命令层循环连接
        4. 运动神经元接收命令神经元的输出

    命令神经元激活值（经 softmax 后）可用于 LAAP 注意力机制。
    """

    # ── 神经元类型常量 ────────────────────────────────────────────
    N_SENSORY = 4
    N_INTER = 6
    N_COMMAND = 4
    N_MOTOR = 5
    N_TOTAL = N_SENSORY + N_INTER + N_COMMAND + N_MOTOR  # = 19

    # 索引区间
    SENSORY_IDX = (0, N_SENSORY)                                  # 0..4
    INTER_IDX = (N_SENSORY, N_SENSORY + N_INTER)                  # 4..10
    COMMAND_IDX = (N_SENSORY + N_INTER, N_SENSORY + N_INTER + N_COMMAND)  # 10..14
    MOTOR_IDX = (N_SENSORY + N_INTER + N_COMMAND, N_TOTAL)        # 14..19

    def __init__(
        self,
        input_dim: int = 4,
        seed: Optional[int] = None,
    ) -> None:
        """初始化 19 神经元 NCP 回路。

        参数：
            input_dim : 外部输入维度，默认 4（与感觉神经元数量一致）
            seed      : 随机种子（可复现）
        """
        self.input_dim = int(input_dim)
        self.hidden_dim = self.N_TOTAL  # 19
        rng = np.random.default_rng(seed)

        # 每个神经元是一个 1 维 CfC 单元（hidden_dim=1）
        # 用独立 seed 保证可复现
        self.cells: list[CfCCell] = [
            CfCCell(input_dim=1, hidden_dim=1, seed=int(rng.integers(0, 2**31 - 1)))
            for _ in range(self.N_TOTAL)
        ]

        # ── 构建稀疏突触连接 ──────────────────────────────────────
        # sensory → inter : 4×6 全连接（稀疏可由权重接近 0 体现）
        self.W_sensory_inter = _xavier_init((self.N_INTER, self.N_SENSORY), rng) * 0.5
        # inter → command : 6×4
        self.W_inter_command = _xavier_init((self.N_COMMAND, self.N_INTER), rng) * 0.5
        # command → command : 4×4 循环连接（含自反馈）
        # 用较小初始化避免循环爆炸
        self.W_command_command = _xavier_init((self.N_COMMAND, self.N_COMMAND), rng) * 0.3
        # command → motor : 5×4
        self.W_command_motor = _xavier_init((self.N_MOTOR, self.N_COMMAND), rng) * 0.5
        # sensory 输入投影：input_dim → 4 个感觉神经元
        if self.input_dim == self.N_SENSORY:
            self.W_input_sensory = np.eye(self.N_SENSORY, dtype=np.float64)
        else:
            self.W_input_sensory = _xavier_init((self.N_SENSORY, self.input_dim), rng) * 0.5

        # 每个神经元接收外部/突触输入的偏置
        self.b_neurons = np.zeros(self.N_TOTAL, dtype=np.float64)

        # 记录最近一次 forward 的命令神经元激活值（原始，未 softmax）
        self._command_activations: np.ndarray = np.zeros(self.N_COMMAND, dtype=np.float64)

        logger.debug(
            f"[INFO] NCPCircuit 初始化: 19 神经元 "
            f"(sensory={self.N_SENSORY}, inter={self.N_INTER}, "
            f"command={self.N_COMMAND}, motor={self.N_MOTOR}), input_dim={input_dim}"
        )

    # ── 索引辅助 ──────────────────────────────────────────────────

    @property
    def sensory_slice(self) -> slice:
        return slice(*self.SENSORY_IDX)

    @property
    def inter_slice(self) -> slice:
        return slice(*self.INTER_IDX)

    @property
    def command_slice(self) -> slice:
        return slice(*self.COMMAND_IDX)

    @property
    def motor_slice(self) -> slice:
        return slice(*self.MOTOR_IDX)

    # ── 前向传播 ──────────────────────────────────────────────────

    def forward(self, h: np.ndarray, x: np.ndarray, dt: float) -> np.ndarray:
        """按布线层级传播信号，返回新的 19 维隐状态。

        参数：
            h : 19 维隐状态（每维对应一个神经元的激活）
            x : input_dim 维外部输入
            dt: 任意正实数步长

        返回：
            new_h : 19 维新隐状态

        传播顺序：sensory → inter → command(含循环) → motor
        每层用对应 CfCCell 演化一维状态，输入为外部/突触加权和。
        """
        if dt < 0:
            raise ValueError(f"[ERROR] dt 必须非负，实际 dt={dt}")

        h = np.asarray(h, dtype=np.float64)
        x = np.asarray(x, dtype=np.float64)
        if h.shape != (self.N_TOTAL,):
            raise ValueError(f"[ERROR] h 形状应为 ({self.N_TOTAL},)，实际 {h.shape}")
        if x.shape != (self.input_dim,):
            raise ValueError(f"[ERROR] x 形状应为 ({self.input_dim},)，实际 {x.shape}")

        if dt == 0.0:
            return _clip_h(h)

        new_h = h.copy()

        # ── 1. 感觉神经元：接收外部输入 ──────────────────────────
        # 每个感觉神经元 i 的输入 = W_input_sensory[i] @ x
        sensory_in = self.W_input_sensory @ x  # shape=(4,)
        for i in range(self.N_SENSORY):
            idx = self.SENSORY_IDX[0] + i
            # CfCCell 输入是 1 维
            hi = np.array([h[idx]])
            xi = np.array([sensory_in[i] + self.b_neurons[idx]])
            new_h[idx] = self.cells[idx].forward(hi, xi, dt)[0]

        # ── 2. 中间神经元：接收感觉神经元的输出 ──────────────────
        sensory_out = new_h[self.sensory_slice]  # 用更新后的值
        inter_in = self.W_sensory_inter @ sensory_out  # shape=(6,)
        for i in range(self.N_INTER):
            idx = self.INTER_IDX[0] + i
            hi = np.array([h[idx]])
            xi = np.array([inter_in[i] + self.b_neurons[idx]])
            new_h[idx] = self.cells[idx].forward(hi, xi, dt)[0]

        # ── 3. 命令神经元：接收中间神经元输出 + 命令层循环连接 ────
        inter_out = new_h[self.inter_slice]  # 用更新后的值
        command_feedback = self.W_command_command @ h[self.command_slice]  # 用旧值（避免循环依赖）
        command_in = self.W_inter_command @ inter_out + command_feedback  # shape=(4,)
        for i in range(self.N_COMMAND):
            idx = self.COMMAND_IDX[0] + i
            hi = np.array([h[idx]])
            xi = np.array([command_in[i] + self.b_neurons[idx]])
            new_h[idx] = self.cells[idx].forward(hi, xi, dt)[0]

        # 记录命令神经元激活值（tanh 压缩到 [-1,1]，便于后续注意力 softmax）
        self._command_activations = np.tanh(new_h[self.command_slice])

        # ── 4. 运动神经元：接收命令神经元输出 ────────────────────
        command_out = new_h[self.command_slice]
        motor_in = self.W_command_motor @ command_out  # shape=(5,)
        for i in range(self.N_MOTOR):
            idx = self.MOTOR_IDX[0] + i
            hi = np.array([h[idx]])
            xi = np.array([motor_in[i] + self.b_neurons[idx]])
            new_h[idx] = self.cells[idx].forward(hi, xi, dt)[0]

        return _clip_h(new_h.astype(np.float64))

    # ── 查询接口 ──────────────────────────────────────────────────

    def get_command_activations(self) -> np.ndarray:
        """返回命令神经元的激活值（tanh 压缩后，shape=(4,)）。

        LAAP 注意力层可对返回值做 softmax 得到注意力权重。
        """
        return self._command_activations.copy()

    def get_tau_effective(self) -> np.ndarray:
        """返回 19 维向量，每维是对应 CfCCell 的有效时间常数。"""
        return np.array([c.get_tau_effective()[0] for c in self.cells], dtype=np.float64)

    def default_state(self) -> np.ndarray:
        """返回 19 维零初始化隐状态。"""
        return np.zeros(self.N_TOTAL, dtype=np.float64)

    def __repr__(self) -> str:
        return (
            f"NCPCircuit(n_total={self.N_TOTAL}, "
            f"sensory={self.N_SENSORY}, inter={self.N_INTER}, "
            f"command={self.N_COMMAND}, motor={self.N_MOTOR}, "
            f"input_dim={self.input_dim})"
        )
