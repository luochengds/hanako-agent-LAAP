"""
LAAP Embodied — 夹爪硬件抽象
================================

定义 Gripper 抽象接口和 Genesis 仿真实现。
"""

from __future__ import annotations

import numpy as np
from abc import ABC, abstractmethod
from typing import Tuple, Optional

try:
    import genesis as gs
    _GS_AVAILABLE = True
except ImportError:
    _GS_AVAILABLE = False
    gs = None


class Gripper(ABC):
    """夹爪抽象接口"""

    @abstractmethod
    def open(self, width: Optional[float] = None) -> bool:
        """打开夹爪"""
        ...

    @abstractmethod
    def close(self, force: Optional[float] = None) -> bool:
        """闭合夹爪"""
        ...

    @abstractmethod
    def grasp(self, force: float = 5.0) -> bool:
        """抓取（闭合并保持力）"""
        ...

    @abstractmethod
    def release(self) -> bool:
        """释放"""
        ...

    @abstractmethod
    def get_state(self) -> Tuple[float, float]:
        """获取夹爪状态

        Returns:
            (opening_width, grip_force)
        """
        ...

    @property
    @abstractmethod
    def is_grasping(self) -> bool:
        """是否正在抓取中"""
        ...

    @property
    @abstractmethod
    def max_opening(self) -> float:
        """最大开口宽度"""
        ...


class GenesisGripper(Gripper):
    """基于 Genesis 物理仿真的夹爪实现"""

    def __init__(self, genesis_entity, finger_joints: Tuple[int, int] = (0, 1)):
        self._entity = genesis_entity
        self._finger_joints = finger_joints
        self._grasping = False

    def open(self, width: Optional[float] = None) -> bool:
        try:
            target = width if width is not None else 0.04  # 4cm default
            if hasattr(self._entity, "control_dofs_position"):
                positions = self._entity.get_dofs_position().cpu().numpy().flatten()
                for idx in self._finger_joints:
                    if idx < len(positions):
                        positions[idx] = target
                self._entity.control_dofs_position(positions, gs.CTRL_MODE.position)
            self._grasping = False
            return True
        except Exception:
            return False

    def close(self, force: Optional[float] = None) -> bool:
        try:
            f = force if force is not None else 20.0
            if hasattr(self._entity, "control_dofs_force"):
                n_dofs = self._entity.n_dofs
                torques = np.zeros(n_dofs)
                for idx in self._finger_joints:
                    if idx < n_dofs:
                        torques[idx] = -f
                self._entity.control_dofs_force(torques)
            return True
        except Exception:
            return False

    def grasp(self, force: float = 5.0) -> bool:
        ok = self.close(force)
        if ok:
            self._grasping = True
        return ok

    def release(self) -> bool:
        ok = self.open()
        if ok:
            self._grasping = False
        return ok

    def get_state(self) -> Tuple[float, float]:
        try:
            positions = self._entity.get_dofs_position().cpu().numpy().flatten()
            width = 0.0
            for idx in self._finger_joints:
                if idx < len(positions):
                    width += positions[idx]
            # 简化：力传感器读数
            force = 20.0 if self._grasping else 0.0
            return width, force
        except Exception:
            return 0.0, 0.0

    @property
    def is_grasping(self) -> bool:
        return self._grasping

    @property
    def max_opening(self) -> float:
        return 0.08  # 8cm (typical for Franka gripper)
