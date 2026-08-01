"""
LAAP Embodied — 传感器套件抽象
================================

统一访问所有机器人传感器（相机、力传感器、IMU、关节编码器等）。
"""

from __future__ import annotations

import numpy as np
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any

from .base import RobotState, SensorSuiteSnapshot


class SensorSuite(ABC):
    """传感器套件抽象接口"""

    @abstractmethod
    def read_all(self) -> SensorSuiteSnapshot:
        """一次性读取所有传感器"""
        ...

    @abstractmethod
    def read_rgb(self) -> np.ndarray:
        """RGB 图像 (HxWx3 uint8)"""
        ...

    @abstractmethod
    def read_depth(self) -> np.ndarray:
        """深度图 (HxW float, meters)"""
        ...

    @abstractmethod
    def read_joint_states(self) -> RobotState:
        """关节状态"""
        ...

    @abstractmethod
    def calibrate(self) -> bool:
        """传感器标定"""
        ...


class GenesisSensorSuite(SensorSuite):
    """基于 Genesis 仿真环境的传感器套件

    通过 Genesis 场景的相机和传感器实体获取数据。
    """

    def __init__(self, scene, arm_entity=None, 
                 camera_entity=None, has_depth: bool = True):
        self._scene = scene
        self._arm = arm_entity
        self._camera = camera_entity
        self._has_depth = has_depth

    def read_all(self) -> SensorSuiteSnapshot:
        return SensorSuiteSnapshot(
            rgb=self.read_rgb(),
            depth=self.read_depth() if self._has_depth else None,
            joint_states=self.read_joint_states() if self._arm else None,
            timestamp=0.0,
        )

    def read_rgb(self) -> np.ndarray:
        try:
            # 尝试通过场景视觉器获取渲染
            if self._camera is not None:
                rgb = self._camera.render(rgb=True)
                return rgb.cpu().numpy().astype(np.uint8)
            # 回退：返回占位图像
            return np.zeros((480, 640, 3), dtype=np.uint8)
        except Exception:
            return np.zeros((480, 640, 3), dtype=np.uint8)

    def read_depth(self) -> np.ndarray:
        try:
            if self._camera is not None and self._has_depth:
                depth = self._camera.render(depth=True)
                return depth.cpu().numpy()
            return np.zeros((480, 640), dtype=np.float32)
        except Exception:
            return np.zeros((480, 640), dtype=np.float32)

    def read_joint_states(self) -> RobotState:
        if self._arm is None:
            return RobotState()
        try:
            pos = self._arm.get_dofs_position().cpu().numpy().flatten()
            vel = self._arm.get_dofs_velocity().cpu().numpy().flatten()
            return RobotState(
                joint_positions=pos,
                joint_velocities=vel,
                timestamp=0.0,
            )
        except Exception:
            return RobotState()

    def calibrate(self) -> bool:
        return True  # 仿真中默认已标定
