"""
LAAP Embodied — 参数标定 (Calibration)
=========================================

将 Genesis 仿真参数校准到匹配真实机器人数据。

方法：
  1. 记录真实机器人的运动轨迹 / 力曲线
  2. 在仿真中尝试不同参数组合
  3. 找到使仿真轨迹最接近真实轨迹的参数

用法：
    calibrator = ParameterCalibrator()
    calibrator.add_real_trajectory(joint_positions, timestamps)
    best_params = calibrator.calibrate(n_trials=100)
    # best_params = {friction: 0.45, stiffness: 1.2, ...}

印记: 数据不会说谎
"""

from __future__ import annotations

import numpy as np
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass, field
import json


@dataclass
class TrajectoryData:
    """运动轨迹数据（真实或仿真）"""
    joint_positions: np.ndarray          # T x n_dofs
    joint_velocities: Optional[np.ndarray] = None
    timestamps: Optional[np.ndarray] = None
    ee_poses: Optional[np.ndarray] = None   # T x 4 x 4


@dataclass
class CalibrationResult:
    """标定结果"""
    friction: float = 0.5
    stiffness: float = 1.0
    damping: float = 1.0
    mass_scale: float = 1.0
    joint_offset: np.ndarray = field(default_factory=lambda: np.zeros(7))
    error: float = float('inf')


class ParameterCalibrator:
    """参数标定器

    对比真实和仿真轨迹，找到最匹配的仿真参数。
    使用简单的网格搜索 + 局部优化。
    """

    def __init__(self, n_dofs: int = 7):
        self._n_dofs = n_dofs
        self._real_trajs: List[TrajectoryData] = []
        self._sim_trajs: List[TrajectoryData] = []
        self._best: Optional[CalibrationResult] = None

    def add_real_trajectory(self, positions: np.ndarray,
                            timestamps: Optional[np.ndarray] = None,
                            velocities: Optional[np.ndarray] = None) -> None:
        """添加一条真实轨迹"""
        self._real_trajs.append(TrajectoryData(
            joint_positions=np.array(positions),
            joint_velocities=np.array(velocities) if velocities is not None else None,
            timestamps=np.array(timestamps) if timestamps is not None else None,
        ))

    def add_sim_trajectory(self, positions: np.ndarray,
                           timestamps: Optional[np.ndarray] = None) -> None:
        """添加一条仿真轨迹"""
        self._sim_trajs.append(TrajectoryData(
            joint_positions=np.array(positions),
            timestamps=np.array(timestamps) if timestamps is not None else None,
        ))

    def calibrate(self, n_trials: int = 50) -> CalibrationResult:
        """执行标定 — 网格搜索最佳参数

        Args:
            n_trials: 搜索尝试次数

        Returns:
            最佳参数组合
        """
        if not self._real_trajs:
            return CalibrationResult(error=float('inf'))

        best = CalibrationResult(error=float('inf'))

        # 参数搜索空间
        friction_range = np.linspace(0.1, 1.5, 8)
        stiffness_range = np.linspace(0.3, 2.0, 8)
        damping_range = np.linspace(0.3, 2.0, 8)
        mass_range = np.linspace(0.6, 1.5, 5)

        trials = 0
        for f in friction_range:
            for s in stiffness_range:
                for d in damping_range:
                    for m in mass_range:
                        if trials >= n_trials:
                            break
                        params = CalibrationResult(
                            friction=f, stiffness=s, damping=d,
                            mass_scale=m,
                        )
                        params.error = self._compute_error(params)
                        if params.error < best.error:
                            best = params
                        trials += 1
                    if trials >= n_trials:
                        break
                if trials >= n_trials:
                    break
            if trials >= n_trials:
                break

        self._best = best
        return best

    def _compute_error(self, params: CalibrationResult) -> float:
        """计算参数组合的误差

        简化实现：比较关节位置 RMSE。
        实际使用时需要运行仿真并比较轨迹。
        """
        if not self._real_trajs or not self._sim_trajs:
            return float('inf')

        real = self._real_trajs[0]
        sim = self._sim_trajs[0]

        # 对齐长度
        min_len = min(len(real.joint_positions), len(sim.joint_positions))
        if min_len < 2:
            return float('inf')

        r = real.joint_positions[:min_len]
        s = sim.joint_positions[:min_len]

        # 加权 RMSE
        error = np.sqrt(np.mean((r - s) ** 2))
        return error

    def get_best(self) -> Optional[CalibrationResult]:
        """获取最佳标定结果"""
        return self._best

    def save_calibration(self, path: str) -> None:
        """保存标定结果到 JSON"""
        if self._best is None:
            return
        data = {
            "friction": self._best.friction,
            "stiffness": self._best.stiffness,
            "damping": self._best.damping,
            "mass_scale": self._best.mass_scale,
            "joint_offset": self._best.joint_offset.tolist(),
            "error": self._best.error,
        }
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)

    def load_calibration(self, path: str) -> CalibrationResult:
        """从 JSON 加载标定结果"""
        with open(path, 'r') as f:
            data = json.load(f)
        result = CalibrationResult(
            friction=data["friction"],
            stiffness=data["stiffness"],
            damping=data["damping"],
            mass_scale=data["mass_scale"],
            joint_offset=np.array(data.get("joint_offset", np.zeros(self._n_dofs))),
            error=data.get("error", 0.0),
        )
        self._best = result
        return result
