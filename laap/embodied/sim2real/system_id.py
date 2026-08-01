"""
LAAP Embodied — 系统辨识 (System Identification)
==================================================

从真实机器人的运行数据中辨识动力学参数，
用于校准仿真引擎使其更接近真实物理。

方法：
  1. 记录真实机器人的激励-响应数据（如扫频信号、阶跃响应）
  2. 使用最小二乘法/优化估计关节摩擦、惯性、刚度等参数
  3. 将辨识结果输出为仿真配置文件

用法：
    identifier = SystemIdentifier(n_dofs=7)
    identifier.add_observation(joint_pos, joint_vel, torque_cmd)
    identified_params = identifier.identify()

印记: 数据不会说谎
"""

from __future__ import annotations

import numpy as np
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass, field
import json


@dataclass
class IdentifiedParams:
    """辨识出的系统参数"""
    # 关节摩擦参数 (Coulomb + Viscous)
    coulomb_friction: np.ndarray = field(default_factory=lambda: np.zeros(7))
    viscous_friction: np.ndarray = field(default_factory=lambda: np.zeros(7))

    # 关节刚度和阻尼（柔性关节模型）
    joint_stiffness: np.ndarray = field(default_factory=lambda: np.ones(7) * 1000)
    joint_damping: np.ndarray = field(default_factory=lambda: np.ones(7) * 10)

    # 惯性参数（对角线近似）
    inertia_scale: np.ndarray = field(default_factory=lambda: np.ones(7))

    # 辨识质量
    r_squared: float = 0.0           # 拟合优度
    n_samples: int = 0


class SystemIdentifier:
    """系统辨识器

    从真实机器人的力矩-运动数据辨识动力学参数。

    用法：
        identifier = SystemIdentifier(n_dofs=7)
        for joint_pos, joint_vel, torque in data_stream:
            identifier.add_observation(joint_pos, joint_vel, torque)
        params = identifier.identify()
        print(f'库伦摩擦: {params.coulomb_friction}')
    """

    def __init__(self, n_dofs: int = 7):
        self._n_dofs = n_dofs
        self._observations: List[Tuple[np.ndarray, np.ndarray, np.ndarray]] = []

    def add_observation(self, joint_pos: np.ndarray,
                        joint_vel: np.ndarray,
                        torque_command: np.ndarray) -> None:
        """添加一组观测数据（位置, 速度, 力矩）"""
        self._observations.append((
            np.array(joint_pos).flatten(),
            np.array(joint_vel).flatten(),
            np.array(torque_command).flatten(),
        ))

    def identify(self) -> IdentifiedParams:
        """执行系统辨识

        使用线性最小二乘法估计摩擦参数：
            torque = coulomb * sign(vel) + viscous * vel + gravity(pos) + inertia * accel

        简化模型：只辨识摩擦参数。
        """
        if len(self._observations) < self._n_dofs * 2:
            return IdentifiedParams(n_samples=len(self._observations))

        # 整理数据
        n = len(self._observations)
        positions = np.array([obs[0] for obs in self._observations])
        velocities = np.array([obs[1] for obs in self._observations])
        torques = np.array([obs[2] for obs in self._observations])

        coulomb = np.zeros(self._n_dofs)
        viscous = np.zeros(self._n_dofs)

        for dof in range(self._n_dofs):
            vel = velocities[:, dof]
                            # ^^ actual variable, not a typo
            tq = torques[:, dof]

            # 构建设计矩阵: [sign(vel), vel]
            X = np.column_stack([
                np.sign(vel + 1e-10),  # 避免除零
                vel,
            ])
            y = tq

            try:
                # 最小二乘解
                beta, residuals, rank, s = np.linalg.lstsq(X, y, rcond=None)
                coulomb[dof] = beta[0]
                viscous[dof] = beta[1]
            except Exception:
                coulomb[dof] = 0.0
                viscous[dof] = 0.0

        # R² 计算
        y_mean = np.mean(torques)
        ss_total = np.sum((torques - y_mean) ** 2)
        ss_residual = 0.0
        for dof in range(self._n_dofs):
            vel = velocities[:, dof]
            tq = torques[:, dof]
            pred = coulomb[dof] * np.sign(vel + 1e-10) + viscous[dof] * vel
            ss_residual += np.sum((tq - pred) ** 2)
        r2 = 1 - ss_residual / max(ss_total, 1e-10)

        params = IdentifiedParams(
            coulomb_friction=coulomb,
            viscous_friction=viscous,
            n_samples=n,
            r_squared=r2,
        )
        return params

    def reset(self) -> None:
        """清除所有观测数据"""
        self._observations.clear()

    @property
    def n_observations(self) -> int:
        return len(self._observations)
