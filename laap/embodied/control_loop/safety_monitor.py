"""
LAAP Embodied — 安全监视器
============================

独立于主控制循环运行的安全看门狗。
实时监控机器人状态，在检测到危险时立即执行紧急停止。

独立运行：不依赖 FastLoop / SlowLoop / Aris 认知核心。
"""

from __future__ import annotations

import numpy as np
from typing import Optional, Tuple
from dataclasses import dataclass


@dataclass
class SafetyStatus:
    """安全状态报告"""
    all_safe: bool = True
    joint_limit_violation: bool = False
    velocity_violation: bool = False
    torque_violation: bool = False
    force_violation: bool = False
    singularity_detected: bool = False
    self_collision: bool = False
    emergency_stop_active: bool = False
    violation_count: int = 0


class SafetyMonitor:
    """独立安全监视器

    用法：
        monitor = SafetyMonitor(n_dofs=9)
        status = monitor.check(joint_pos, joint_vel, joint_torque)
        if not status.all_safe:
            monitor.emergency_stop()
    """

    def __init__(
        self,
        n_dofs: int = 9,
        joint_lower: Optional[np.ndarray] = None,
        joint_upper: Optional[np.ndarray] = None,
        max_velocity: float = 2.5,
        max_torque: float = 80.0,
        max_ee_force: float = 100.0,
    ):
        self._n_dofs = n_dofs
        self._joint_lower = joint_lower if joint_lower is not None else np.full(n_dofs, -2.5)
        self._joint_upper = joint_upper if joint_upper is not None else np.full(n_dofs, 2.5)
        self._max_velocity = max_velocity
        self._max_torque = max_torque
        self._max_ee_force = max_ee_force
        self._emergency_stop = False
        self._violation_count = 0
        self._consecutive_violations = 0

    def check(self, joint_pos: np.ndarray, joint_vel: np.ndarray,
              joint_torque: Optional[np.ndarray] = None,
              ee_force: Optional[float] = None) -> SafetyStatus:
        """执行一次安全检查"""
        status = SafetyStatus()

        # 关节位置限位
        if np.any(joint_pos < self._joint_lower) or np.any(joint_pos > self._joint_upper):
            status.joint_limit_violation = True
            status.all_safe = False

        # 速度限位
        if np.any(np.abs(joint_vel) > self._max_velocity):
            status.velocity_violation = True
            status.all_safe = False

        # 力矩限位
        if joint_torque is not None:
            if np.any(np.abs(joint_torque) > self._max_torque):
                status.torque_violation = True
                status.all_safe = False

        # 末端力限位
        if ee_force is not None and ee_force > self._max_ee_force:
            status.force_violation = True
            status.all_safe = False

        # 更新统计
        if not status.all_safe:
            self._violation_count += 1
            self._consecutive_violations += 1
            status.violation_count = self._violation_count
            # 连续违规 > 3 次触发急停
            if self._consecutive_violations > 3:
                status.emergency_stop_active = True
                self._emergency_stop = True
        else:
            self._consecutive_violations = 0

        status.emergency_stop_active = self._emergency_stop
        return status

    def emergency_stop(self) -> None:
        """手动触发紧急停止"""
        self._emergency_stop = True

    def reset(self) -> None:
        """重置安全状态"""
        self._emergency_stop = False
        self._violation_count = 0
        self._consecutive_violations = 0

    @property
    def is_emergency_stopped(self) -> bool:
        return self._emergency_stop

    @property
    def violation_count(self) -> int:
        return self._violation_count
