"""
LAAP — 认知熵与粗粒化系统

Hilbert 6th Problem 启发下的认知统计力学测量层。
不是 PDE 求解器，而是将认知系统的"微观状态分布"映射到
可观测的"宏观热力学量"（熵、场梯度、流态）。

核心概念映射：
  需求 deficit 分布  ≡ 认知粒子的动量分布
  情绪唤醒度        ≡ 认知温度
  目标激活分布      ≡ 宏观序参量
  熵增率 dH/dt      ≡ 认知湍流度指标

设计原则：
  - 零外部依赖（纯 numpy）
  - 计算量 O(n) 或 O(n log n)，不引入 PDE 求解
  - 所有结果可直接嵌入现有 CognitiveState
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
import time
import numpy as np
import logging

logger = logging.getLogger("laap.cognition.entropy")


# ──────────────────────────────────────────────────────────────
# 认知熵 (Consciousness Entropy)
# ──────────────────────────────────────────────────────────────

@dataclass
class EntropySnapshot:
    """单个时间点的认知熵状态"""
    shannon_entropy: float          # H = -Σ p_i log p_i
    boltzmann_entropy: float        # S = k_B log Ω (微观状态数的对数)
    production_rate: float          # dH/dt
    temperature: float              # 认知温度（基于 arousal 映射）
    flow_regime: str                # laminar / transitional / turbulent
    free_energy: float              # F = U - T·S（认知自由能）
    activation_sparsity: float      # 激活分布的稀疏度（0~1）
    timestamp: float = field(default_factory=time.time)


class CognitiveEntropyMonitor:
    """
    认知熵监控器

    持续追踪认知系统的统计力学量，提供：
    1. Shannon 熵：需求分布的不确定性
    2. Boltzmann 熵：微观状态数的对数
    3. 熵产率 dH/dt：认知变化速度
    4. 流态检测：层流（稳定）vs 湍流（创造性）
    5. 认知自由能：U - T·S

    用法：
      monitor = CognitiveEntropyMonitor(window_size=20)
      snapshot = monitor.compute(need_levels, arousal, goal_activations)
    """

    def __init__(self, window_size: int = 20):
        self.window_size = window_size
        self._entropy_history: List[float] = []      # H(t) 时间序列
        self._temperature_history: List[float] = []  # T(t)
        self._snapshots: List[EntropySnapshot] = []
        self._last_raw: Optional[Dict] = None

    # ── 核心计算 ──────────────────────────────────────────

    def compute(
        self,
        need_levels: Dict[str, float],
        arousal: float = 0.5,
        goal_activations: Optional[List[float]] = None,
        valence: float = 0.0,
    ) -> EntropySnapshot:
        """
        计算当前认知熵状态

        参数:
          need_levels:   {need_name: current_level} — 来自 NeedDriveSystem
          arousal:       情绪唤醒度 (0~1)
          goal_activations: 各目标的激活强度列表
          valence:       情绪效价 (-1~1)，用于自由能修正
        """
        # 1. Shannon 熵 from need deficits
        deficits = np.array([
            max(0.0, 0.8 - level)  # target_level = 0.8
            for level in need_levels.values()
        ])
        p_deficit = deficits / (deficits.sum() + 1e-12)
        H_shannon = -np.sum(p_deficit * np.log(p_deficit + 1e-12))
        # 归一化到 [0, 1]：5 个需求的最大熵是 log(5) ≈ 1.609
        H_shannon_norm = H_shannon / np.log(len(need_levels) + 1e-12)

        # 2. Boltzmann 熵：把每维 deficit 离散化为 N_bins 个微观态
        n_bins = 10
        microstates = np.prod(
            np.clip(np.floor(deficits * n_bins).astype(int), 1, n_bins)
        )
        S_boltzmann = np.log(microstates + 1e-12)

        # 3. 认知温度：arousal 映射到温度
        temperature = 0.1 + 0.9 * arousal  # [0.1, 1.0]

        # 4. 熵产率
        self._entropy_history.append(H_shannon_norm)
        if len(self._entropy_history) > self.window_size:
            self._entropy_history.pop(0)

        if len(self._entropy_history) >= 2:
            dH_dt = H_shannon_norm - self._entropy_history[-2]
        else:
            dH_dt = 0.0

        # 5. 流态检测
        flow_regime = self._detect_flow_regime(dH_dt, arousal, H_shannon_norm)

        # 6. 认知自由能 F = U - T·S
        # 内部能量 U = 平均 deficit（需求不满足度）
        U = float(np.mean(deficits))
        F = U - temperature * H_shannon_norm

        # 7. 激活稀疏度（如果有目标激活数据）
        if goal_activations and len(goal_activations) > 0:
            g = np.array(goal_activations) / (np.sum(goal_activations) + 1e-12)
            sparsity = 1.0 + np.sum(g * np.log(g + 1e-12)) / np.log(len(g) + 1e-12)
        else:
            sparsity = 0.0

        snapshot = EntropySnapshot(
            shannon_entropy=round(H_shannon_norm, 4),
            boltzmann_entropy=round(S_boltzmann, 4),
            production_rate=round(dH_dt, 4),
            temperature=round(temperature, 4),
            flow_regime=flow_regime,
            free_energy=round(F, 4),
            activation_sparsity=round(sparsity, 4),
        )

        self._snapshots.append(snapshot)
        if len(self._snapshots) > self.window_size:
            self._snapshots.pop(0)

        self._last_raw = {
            "need_levels": need_levels,
            "deficits": deficits.tolist(),
            "arousal": arousal,
            "valence": valence,
        }

        return snapshot

    def _detect_flow_regime(
        self, dH_dt: float, arousal: float, H: float
    ) -> str:
        """
        流态检测逻辑

        laminar（层流）:  低熵产率 + 低唤醒 → 稳定聚焦
        transitional（过渡）: 中等熵产率 | 中等唤醒 → 探索与聚焦切换
        turbulent（湍流）: 高熵产率 + 高唤醒 → 创造性跳跃
        """
        # 阈值基于 window 内的统计
        if len(self._entropy_history) >= self.window_size:
            # 用滚动标准差作为基线
            H_std = float(np.std(self._entropy_history))
        else:
            H_std = 0.05

        # 归一化 dH_dt 到标准差倍数
        if H_std > 1e-8:
            z_score = abs(dH_dt) / H_std
        else:
            z_score = 0.0

        if z_score > 2.0 and arousal > 0.6:
            return "turbulent"
        elif z_score > 1.0 or (arousal > 0.5 and arousal < 0.75):
            return "transitional"
        else:
            return "laminar"

    # ── 趋势分析 ──────────────────────────────────────────

    def is_creative_window(self, lookback: int = 5) -> bool:
        """
        检测是否处于"创造性窗口"
        特征：过渡/湍流状态持续但不过度
        """
        if len(self._snapshots) < lookback:
            return False
        recent = self._snapshots[-lookback:]
        regimes = [s.flow_regime for s in recent]
        turbulent_count = regimes.count("turbulent")
        transitional_count = regimes.count("transitional")
        # 窗口内 60% 以上为非层流，且没有持续性的极高熵
        non_laminar = (turbulent_count + transitional_count) / len(recent)
        avg_H = np.mean([s.shannon_entropy for s in recent])
        return non_laminar >= 0.6 and avg_H < 0.85  # 避免完全混乱

    def get_entropy_trend(self) -> Dict[str, Any]:
        """获取熵的时间序列趋势"""
        if len(self._snapshots) < 2:
            return {"trend": "stable", "volatility": 0.0}
        H_vals = [s.shannon_entropy for s in self._snapshots]
        H_trend = np.polyfit(range(len(H_vals)), H_vals, 1)[0]
        volatility = float(np.std(H_vals))
        if abs(H_trend) < 0.01:
            trend = "stable"
        elif H_trend > 0:
            trend = "increasing_entropy"
        else:
            trend = "decreasing_entropy"
        return {
            "trend": trend,
            "slope": round(float(H_trend), 4),
            "volatility": round(volatility, 4),
            "current_H": H_vals[-1],
        }

    def get_summary(self) -> Dict[str, Any]:
        """获取当前熵系统的完整摘要"""
        if not self._snapshots:
            return {"status": "no_data"}
        latest = self._snapshots[-1]
        trend = self.get_entropy_trend()
        creative = self.is_creative_window()
        return {
            "entropy": latest.shannon_entropy,
            "flow_regime": latest.flow_regime,
            "production_rate": latest.production_rate,
            "temperature": latest.temperature,
            "free_energy": latest.free_energy,
            "trend": trend["trend"],
            "volatility": trend["volatility"],
            "creative_window": creative,
            "n_snapshots": len(self._snapshots),
        }


# ──────────────────────────────────────────────────────────────
# 粗粒化算子 (Coarse-Graining Operator)
# ──────────────────────────────────────────────────────────────

@dataclass
class CoarseGrainedField:
    """
    粗粒化后的认知场

    将高维的认知状态（need_deficits × arousal × valence × ...）
    投影到可观测的低维场中。
    """
    density: np.ndarray           # 认知密度场 (grid, grid)
    velocity: np.ndarray          # 认知流场 (grid, grid, 2)
    pressure: np.ndarray          # 认知压力场 (grid, grid) — 需求紧迫度
    temperature: np.ndarray       # 认知温度场 (grid, grid)
    gradient_magnitude: float     # 场的梯度幅度 — 认知不均匀度
    divergence: float             # 散度 — 认知"膨胀/收缩"
    vorticity: float              # 旋度 — 认知循环/反刍程度


class CoarseGrainer:
    """
    粗粒化算子

    将认知系统的微观状态映射到 2D 网格上的宏观场。
    这不是 PDE 求解，而是一种可视化/诊断工具：

    认知空间轴的映射:
      x 轴 → competence & certainty 的联合维度（能力-确定空间）
      y 轴 → autonomy & relatedness 的联合维度（自主-社交空间）
      第三维（强度）→ energy 作为颜色编码

    用法:
      cg = CoarseGrainer(grid_resolution=8)
      field = cg.coarse_grain(need_levels, arousal, valence)
    """

    def __init__(self, grid_resolution: int = 8, sigma: float = 0.15):
        self.grid_resolution = grid_resolution
        self.sigma = sigma
        self._last_field: Optional[CoarseGrainedField] = None

        # 创建网格
        x = np.linspace(0, 1, grid_resolution)
        y = np.linspace(0, 1, grid_resolution)
        self._X, self._Y = np.meshgrid(x, y)

    def coarse_grain(
        self,
        need_levels: Dict[str, float],
        arousal: float = 0.5,
        valence: float = 0.0,
    ) -> CoarseGrainedField:
        """
        对当前认知状态执行粗粒化

        映射方案:
          x = (1 - competence) * 0.6 + (1 - certainty) * 0.4    能力-确定空间
          y = (1 - autonomy) * 0.5 + (1 - relatedness) * 0.5    自主-社交空间
          energy = (1 - energy_level)                            能量作为"高度"
        """
        c = 1.0 - need_levels.get("competence", 0.5)
        cert = 1.0 - need_levels.get("certainty", 0.5)
        a = 1.0 - need_levels.get("autonomy", 0.5)
        r = 1.0 - need_levels.get("relatedness", 0.5)
        e = 1.0 - need_levels.get("energy", 0.5)

        x = c * 0.6 + cert * 0.4
        y = a * 0.5 + r * 0.5
        z = e  # "高度"或"密度"

        # 用单个点的高斯散布做核密度估计
        # 这样即使只有一个认知状态也能生成有结构的场
        density = np.exp(
            -((self._X - x) ** 2 + (self._Y - y) ** 2) / (2 * self.sigma ** 2)
        )
        density = density * (1.0 + z * 0.5)  # energy 调制幅度
        density = density / (density.sum() + 1e-12)

        # 认知压力：deficit 的联合紧迫度
        pressure = (c + cert + a + r + e) / 5.0 * density

        # 温度场：arousal 为基底 + 局部调制
        temperature = (0.1 + 0.9 * arousal) * np.ones_like(density)

        # 速度场：从当前帧到上一帧的差分（如无可用的则用梯度近似）
        if self._last_field is not None:
            # 用密度梯度近似速度方向
            grad_y, grad_x = np.gradient(density)
            velocity = np.stack([grad_x, grad_y], axis=-1)
            # 归一化
            norm = np.linalg.norm(velocity, axis=-1, keepdims=True) + 1e-12
            velocity = velocity / norm * 0.1
        else:
            velocity = np.zeros((self.grid_resolution, self.grid_resolution, 2))

        # 场的微分几何量
        grad_y, grad_x = np.gradient(density)
        gradient_magnitude = float(np.sqrt(np.mean(grad_x ** 2 + grad_y ** 2)))
        divergence = float(np.mean(np.gradient(velocity[..., 0])[0] +
                                    np.gradient(velocity[..., 1])[1]))
        # 旋度（2D 标量）
        dv_dx = np.gradient(velocity[..., 1])[1]
        du_dy = np.gradient(velocity[..., 0])[0]
        vorticity = float(np.mean(dv_dx - du_dy))

        field = CoarseGrainedField(
            density=density,
            velocity=velocity,
            pressure=pressure,
            temperature=temperature,
            gradient_magnitude=round(gradient_magnitude, 4),
            divergence=round(divergence, 4),
            vorticity=round(vorticity, 4),
        )

        self._last_field = field
        return field

    def get_field_snapshot(self) -> Optional[CoarseGrainedField]:
        """获取最近一次粗粒化的场"""
        return self._last_field


# ──────────────────────────────────────────────────────────────
# 便捷入口：一次调用获取所有 Hilbert6 指标
# ──────────────────────────────────────────────────────────────

@dataclass
class Hilbert6Metrics:
    """一次认知循环的完整 Hilbert6 测量结果"""
    entropy: EntropySnapshot
    field: Optional[CoarseGrainedField] = None
    creative_window: bool = False


# ──────────────────────────────────────────────────────────────
# 可视化
# ──────────────────────────────────────────────────────────────

# 主题色
_COLOR_LAMINAR = "#4FC3F7"      # 层流 — 浅蓝
_COLOR_TRANSITIONAL = "#FFB74D"  # 过渡 — 琥珀
_COLOR_TURBULENT = "#EF5350"      # 湍流 — 红
_COLOR_BG = "#1a1a2e"            # 深空背景
_COLOR_GRID = "#2a2a4e"          # 网格线
_COLOR_TEXT = "#e0e0e0"          # 文字
_COLOR_ACCENT = "#7c4dff"        # 强调色


def render_field_svg(
    field: CoarseGrainedField,
    entropy_snapshot: Optional[EntropySnapshot] = None,
    width: int = 600,
    height: int = 480,
) -> str:
    """
    将粗粒化认知场渲染为 SVG 字符串

    包含：
    - 密度场热力图（颜色编码）
    - 流场箭头叠加
    - 关键指标数据面板
    - 流态指示器

    可直接用于 show_card 或保存为 .svg 文件
    """
    n = field.density.shape[0]
    cell_size = width // n
    margin = 60  # 左侧边距留给标签
    top_margin = 30
    plot_width = n * cell_size
    plot_height = n * cell_size
    total_width = plot_width + margin + 220  # 图表 + 数据面板
    total_height = max(plot_height + top_margin + 30, height)

    # 密度映射到颜色 (深蓝→青→黄→红)
    d = field.density
    d_min, d_max = d.min(), d.max()
    d_range = d_max - d_min if d_max > d_min else 1.0
    d_norm = (d - d_min) / d_range

    lines = []
    lines.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total_width} {total_height}">')
    lines.append(f'<rect width="{total_width}" height="{total_height}" fill="{_COLOR_BG}" rx="12"/>')

    # ---- 标题 ----
    lines.append(f'<text x="{total_width // 2}" y="22" text-anchor="middle" fill="{_COLOR_TEXT}" font-size="16" font-family="sans-serif" font-weight="bold">认知场 (Coarse-Grained Field)</text>')

    # ---- 热力图 ----
    for i in range(n):
        for j in range(n):
            val = d_norm[i, j]
            # R/G/B 插值：低=蓝紫，中=青，高=黄红
            r = int(min(255, val * 3 * 255))
            g = int(min(255, val * 2 * 200))
            b = int(max(0, (1 - val) * 200))
            color = f"rgb({r},{g},{b})"
            x = margin + j * cell_size
            y = top_margin + i * cell_size
            lines.append(f'<rect x="{x}" y="{y}" width="{cell_size - 1}" height="{cell_size - 1}" fill="{color}" opacity="0.85"/>')

    # ---- 流场箭头 ----
    # 每 2 格画一个箭头避免过密
    arrow_scale = cell_size * 0.8
    for i in range(0, n, 2):
        for j in range(0, n, 2):
            vx = field.velocity[i, j, 0]
            vy = field.velocity[i, j, 1]
            mag = np.sqrt(vx ** 2 + vy ** 2)
            if mag < 1e-6:
                continue
            cx = margin + j * cell_size + cell_size // 2
            cy = top_margin + i * cell_size + cell_size // 2
            dx = vx / mag * arrow_scale
            dy = vy / mag * arrow_scale
            # 箭头线
            lines.append(
                f'<line x1="{cx - dx / 2}" y1="{cy - dy / 2}" '
                f'x2="{cx + dx / 2}" y2="{cy + dy / 2}" '
                f'stroke="{_COLOR_ACCENT}" stroke-width="1.5" opacity="0.7"/>'
            )
            # 箭头头部
            angle = np.arctan2(vy, vx)
            head_len = 6
            for sign in (-1, 1):
                ha = angle + sign * 2.5
                hx = cx + dx / 2 + head_len * np.cos(ha)
                hy = cy + dy / 2 + head_len * np.sin(ha)
                lines.append(
                    f'<line x1="{cx + dx / 2}" y1="{cy + dy / 2}" '
                    f'x2="{hx}" y2="{hy}" '
                    f'stroke="{_COLOR_ACCENT}" stroke-width="1.5" opacity="0.7"/>'
                )

    # ---- 网格边框 ----
    lines.append(
        f'<rect x="{margin}" y="{top_margin}" '
        f'width="{plot_width}" height="{plot_height}" '
        f'fill="none" stroke="{_COLOR_GRID}" stroke-width="1"/>'
    )

    # ---- 轴标签 ----
    lines.append(f'<text x="{margin + plot_width // 2}" y="{top_margin + plot_height + 18}" text-anchor="middle" fill="{_COLOR_TEXT}" font-size="11" font-family="sans-serif">自主·社交空间 (y)</text>')
    lines.append(f'<text x="{12}" y="{top_margin + plot_height // 2}" text-anchor="middle" fill="{_COLOR_TEXT}" font-size="11" font-family="sans-serif" transform="rotate(-90, 12, {top_margin + plot_height // 2})">能力·确定空间 (x)</text>')

    # ---- 右侧数据面板 ----
    px = margin + plot_width + 20
    py = top_margin + 10
    line_h = 22

    lines.append(f'<text x="{px}" y="{py}" fill="{_COLOR_ACCENT}" font-size="13" font-family="sans-serif" font-weight="bold">场指标</text>')
    py += line_h + 5

    metrics = [
        ("梯度", f"{field.gradient_magnitude:.4f}"),
        ("散度", f"{field.divergence:.4f}"),
        ("旋度", f"{field.vorticity:.4f}"),
        ("密度峰", f"{float(d_max):.3f}"),
    ]
    for label, value in metrics:
        lines.append(f'<text x="{px}" y="{py}" fill="{_COLOR_TEXT}" font-size="11" font-family="sans-serif">{label}</text>')
        lines.append(f'<text x="{px + 120}" y="{py}" fill="#fff" font-size="11" font-family="sans-serif" text-anchor="end">{value}</text>')
        py += line_h

    # ---- 流态指示器 ----
    if entropy_snapshot:
        py += 10
        lines.append(f'<text x="{px}" y="{py}" fill="{_COLOR_ACCENT}" font-size="13" font-family="sans-serif" font-weight="bold">认知流体</text>')
        py += line_h + 5

        regime = entropy_snapshot.flow_regime
        if regime == "laminar":
            rc = _COLOR_LAMINAR
            rl = "层流"
        elif regime == "transitional":
            rc = _COLOR_TRANSITIONAL
            rl = "过渡"
        else:
            rc = _COLOR_TURBULENT
            rl = "湍流"

        lines.append(f'<circle cx="{px + 8}" cy="{py - 4}" r="5" fill="{rc}"/>')
        lines.append(f'<text x="{px + 20}" y="{py}" fill="{rc}" font-size="13" font-family="sans-serif" font-weight="bold">{rl}</text>')
        py += line_h

        entropy_items = [
            ("熵", f"{entropy_snapshot.shannon_entropy:.3f}"),
            ("产率", f"{entropy_snapshot.production_rate:.4f}"),
            ("温度", f"{entropy_snapshot.temperature:.2f}"),
            ("自由能", f"{entropy_snapshot.free_energy:.3f}"),
            ("稀疏度", f"{entropy_snapshot.activation_sparsity:.2f}"),
        ]
        for label, value in entropy_items:
            lines.append(f'<text x="{px}" y="{py}" fill="{_COLOR_TEXT}" font-size="11" font-family="sans-serif">{label}</text>')
            lines.append(f'<text x="{px + 120}" y="{py}" fill="#fff" font-size="11" font-family="sans-serif" text-anchor="end">{value}</text>')
            py += line_h

    lines.append('</svg>')
    return "\n".join(lines)


def measure_cognitive_state(
    need_levels: Dict[str, float],
    arousal: float,
    valence: float,
    goal_activations: Optional[List[float]] = None,
    entropy_monitor: Optional[CognitiveEntropyMonitor] = None,
    coarse_grainer: Optional[CoarseGrainer] = None,
) -> Hilbert6Metrics:
    """
    一站式认知状态测量

    参数:
      need_levels: {need_name: current_level}
      arousal: 情绪唤醒度
      valence: 情绪效价
      goal_activations: 目标激活强度列表
      entropy_monitor: 可复用的熵监控器（内部自动创建）
      coarse_grainer: 可复用的粗粒化器（内部自动创建）

    返回:
      Hilbert6Metrics 包含熵快照、粗粒化场、创造性窗口检测
    """
    if entropy_monitor is None:
        entropy_monitor = CognitiveEntropyMonitor()
    if coarse_grainer is None:
        coarse_grainer = CoarseGrainer()

    entropy = entropy_monitor.compute(need_levels, arousal, goal_activations, valence)
    field = coarse_grainer.coarse_grain(need_levels, arousal, valence)
    creative = entropy_monitor.is_creative_window()

    return Hilbert6Metrics(
        entropy=entropy,
        field=field,
        creative_window=creative,
    )
