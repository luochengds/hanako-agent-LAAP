"""
LAAP Embodied — 快控制环路 (Fast Loop)
=========================================

高速实时控制循环。运行在 100-1000Hz，纯数学/运动学计算。
不涉及 Aris 认知核心，不调用 LLM。

职责：
  - 接收 SlowLoop 的高级目标 → 分解为关节轨迹
  - 阻抗/位置/速度/力控制模式
  - 插值/滤波/平滑
  - 安全边界检查（超限即停止）

架构：
    SlowLoop ──→ "去抓(0.3, 0.5, 0.1)" ──→ FastLoop
                                              │
                                         [轨迹生成]
                                              │
                                         [PD控制律]
                                              │
                                         [限位检查] ← SafetyMonitor
                                              │
                                         [执行器指令]
                                              │
                                          Robot / Sim
"""

from __future__ import annotations

import time
import numpy as np
from typing import Optional, Callable, List, Tuple
from dataclasses import dataclass, field
from enum import Enum


class ControlMode(str, Enum):
    PD_JOINT_POSITION = "pd_joint_position"
    PD_JOINT_VELOCITY = "pd_joint_velocity"
    PD_EE_POSE = "pd_ee_pose"
    IMPEDANCE = "impedance"
    TORQUE = "torque"


@dataclass
class ControlCommand:
    """快循环控制指令"""
    target: np.ndarray           # 目标值（关节位置/速度/末端位姿）
    mode: ControlMode = ControlMode.PD_JOINT_POSITION
    duration: float = 1.0        # 期望运动时间（秒）
    kp: float = 100.0            # 比例增益
    kd: float = 10.0             # 微分增益
    max_force: float = 50.0      # 最大输出力
    timestamp: float = 0.0


@dataclass
class SafetyLimits:
    """安全边界"""
    joint_lower: np.ndarray = field(default_factory=lambda: np.full(9, -2.5))
    joint_upper: np.ndarray = field(default_factory=lambda: np.full(9, 2.5))
    max_velocity: float = 2.0        # rad/s
    max_torque: float = 50.0         # Nm
    max_ee_force: float = 50.0       # N
    singularity_threshold: float = 0.01  # 奇异位形检测


class FastControlLoop:
    """高频控制循环 (100-1000Hz)

    用法：
        loop = FastControlLoop(n_dofs=9, dt=0.001)
        
        # 设置目标
        loop.set_target(np.zeros(9), ControlMode.PD_JOINT_POSITION)
        
        # 每次 tick 获取控制输出
        cmd = loop.tick(current_pos, current_vel)
    """

    def __init__(
        self,
        n_dofs: int = 9,
        dt: float = 0.001,        # 1ms = 1000Hz
        safety: Optional[SafetyLimits] = None,
    ):
        self._n_dofs = n_dofs
        self._dt = dt
        self._safety = safety or SafetyLimits()

        # PD 控制器状态
        self._target: Optional[np.ndarray] = None
        self._mode = ControlMode.PD_JOINT_POSITION
        self._kp = 100.0
        self._kd = 10.0
        self._max_force = 50.0
        self._duration = 1.0
        self._elapsed = 0.0

        # 轨迹插值
        self._start_pos: Optional[np.ndarray] = None
        self._target_pos: Optional[np.ndarray] = None

        # 统计
        self._tick_count = 0
        self._last_tick_time = 0.0
        self._speed_safe = True

    def set_target(self, target: np.ndarray, mode: ControlMode = ControlMode.PD_JOINT_POSITION,
                   duration: float = 1.0, kp: float = 100.0, kd: float = 10.0,
                   max_force: float = 50.0, current_pos: Optional[np.ndarray] = None) -> None:
        """设置新目标

        支持轨迹插值（从当前位置渐进过渡到目标）。
        """
        self._target = target.copy()
        self._mode = mode
        self._kp = kp
        self._kd = kd
        self._max_force = max_force
        self._duration = duration
        self._elapsed = 0.0
        self._start_pos = current_pos.copy() if current_pos is not None else None
        self._target_pos = target.copy()

    def tick(self, current_pos: np.ndarray, current_vel: np.ndarray) -> Tuple[np.ndarray, bool]:
        """执行一个控制 tick

        Args:
            current_pos: 当前关节位置 (n_dofs,)
            current_vel: 当前关节速度 (n_dofs,)

        Returns:
            (torque_command, safe) — 力矩指令和安全状态
        """
        self._tick_count += 1
        self._elapsed += self._dt

        # 速度安全
        if np.any(np.abs(current_vel) > self._safety.max_velocity):
            self._speed_safe = False
            return np.zeros(self._n_dofs), False

        # 位置安全
        if np.any(current_pos < self._safety.joint_lower) or \
           np.any(current_pos > self._safety.joint_upper):
            self._speed_safe = False
            return np.zeros(self._n_dofs), False

        # 轨迹插值
        target = self._compute_interpolated_target(current_pos)

        # PD 控制器
        if self._mode in (ControlMode.PD_JOINT_POSITION, ControlMode.PD_EE_POSE):
            error = target - current_pos
            torque = self._kp * error - self._kd * current_vel
        elif self._mode == ControlMode.PD_JOINT_VELOCITY:
            error = target - current_vel
            torque = self._kp * error  # 只有P项
        elif self._mode == ControlMode.IMPEDANCE:
            # 简化阻抗控制
            error = target - current_pos
            torque = self._kp * error - self._kd * current_vel
        else:
            torque = np.zeros(self._n_dofs)

        # 力矩限幅
        torque = np.clip(torque, -self._max_force, self._max_force)

        return torque, True

    def _compute_interpolated_target(self, current_pos: np.ndarray) -> np.ndarray:
        """计算插值后的目标位置
        
        使用线性插值，在 duration 时间从起始位置过渡到目标位置。
        """
        if self._target is None:
            return current_pos

        if self._start_pos is None or self._duration <= 0:
            return self._target

        # 线性插值
        alpha = min(self._elapsed / self._duration, 1.0)
        # 五次多项式平滑（起止速度和加速度为零）
        alpha_smooth = 10 * alpha**3 - 15 * alpha**4 + 6 * alpha**5
        interpolated = self._start_pos + alpha_smooth * (self._target_pos - self._start_pos)
        return interpolated

    def is_motion_done(self) -> bool:
        """检查当前运动是否完成"""
        return self._elapsed >= self._duration

    def emergency_stop(self) -> np.ndarray:
        """紧急停止 — 返回零力矩"""
        self._speed_safe = False
        return np.zeros(self._n_dofs)

    def reset(self) -> None:
        """重置循环状态"""
        self._target = None
        self._start_pos = None
        self._target_pos = None
        self._elapsed = 0.0
        self._speed_safe = True

    @property
    def tick_count(self) -> int:
        return self._tick_count

    @property
    def is_safe(self) -> bool:
        return self._speed_safe

    @property
    def dt(self) -> float:
        return self._dt

    def get_stats(self) -> dict:
        return {
            "tick_count": self._tick_count,
            "speed_safe": self._speed_safe,
            "motion_done": self.is_motion_done(),
            "dt": self._dt,
            "mode": self._mode.value,
        }
