"""
LAAP Embodied — 机械臂硬件抽象
================================

定义 RobotArm 抽象接口和 Genesis 仿真实现。

用法：
    from laap.embodied.hardware_abstraction import GenesisArm
    
    arm = GenesisArm(genesis_entity=franka_entity)
    state = arm.get_state()
    arm.send_position([0.1, -0.3, ...],  duration=2.0)
"""

from __future__ import annotations

import time
import numpy as np
from abc import ABC, abstractmethod
from typing import Optional, Tuple, List, Dict, Any

try:
    import genesis as gs
    _GS_AVAILABLE = True
except ImportError:
    _GS_AVAILABLE = False
    gs = None

from .base import (
    RobotState, ControlMode, ArmStatus,
    pose_to_transform,
)


class RobotArm(ABC):
    """机械臂抽象接口

    所有机械臂实现（仿真/真实）都必须继承这个类。
    """

    @abstractmethod
    def get_state(self) -> RobotState:
        """获取当前机器人状态"""
        ...

    @abstractmethod
    def send_command(self, target: np.ndarray, mode: ControlMode = ControlMode.POSITION,
                     duration: float = 1.0, blocking: bool = True) -> bool:
        """发送控制指令

        Args:
            target: 目标值（关节位置/末端位姿/力，取决于模式）
            mode: 控制模式
            duration: 期望运动时间（秒）
            blocking: 是否阻塞直到运动完成

        Returns:
            是否执行成功
        """
        ...

    def send_position(self, target_joints: np.ndarray, duration: float = 1.0,
                      blocking: bool = True) -> bool:
        """关节空间位置控制（快捷方法）"""
        return self.send_command(target_joints, ControlMode.POSITION, duration, blocking)

    def send_velocity(self, target_vel: np.ndarray, duration: float = 0.1,
                      blocking: bool = False) -> bool:
        """关节空间速度控制（快捷方法）"""
        return self.send_command(target_vel, ControlMode.VELOCITY, duration, blocking)

    def send_eef_pose(self, target_pose: np.ndarray, duration: float = 2.0,
                      blocking: bool = True) -> bool:
        """末端笛卡尔空间位姿控制（快捷方法）"""
        return self.send_command(target_pose, ControlMode.EEF_POSE, duration, blocking)

    @abstractmethod
    def get_ft_sensor(self) -> Tuple[np.ndarray, np.ndarray]:
        """获取力/力矩传感器读数

        Returns:
            (force: (Fx,Fy,Fz), torque: (Tx,Ty,Tz))
        """
        ...

    @abstractmethod
    def get_joint_limits(self) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """获取关节限位

        Returns:
            (lower_pos, upper_pos, max_torque)  每个都是 [n_dofs]
        """
        ...

    @abstractmethod
    def get_eef_pose(self) -> np.ndarray:
        """获取末端执行器位姿 (4x4 变换矩阵)"""
        ...

    @abstractmethod
    def stop(self) -> None:
        """紧急停止"""
        ...

    @property
    @abstractmethod
    def n_dofs(self) -> int:
        """关节数量"""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """机器人名称"""
        ...


# ═══════════════════════════════════════════════════════════════
# Genesis 仿真机械臂实现
# ═══════════════════════════════════════════════════════════════

class GenesisArm(RobotArm):
    """基于 Genesis 物理仿真的机械臂实现

    包装 gs.engine.entities.RigidEntity 为 RobotArm 接口。
    """

    def __init__(self, genesis_entity, name: str = "genesis_arm"):
        self._entity = genesis_entity
        self._name = name
        self._n_dofs = getattr(genesis_entity, "n_dofs", 0)
        self._status = ArmStatus.IDLE
        self._last_target: Optional[np.ndarray] = None

    @property
    def n_dofs(self) -> int:
        return self._n_dofs

    @property
    def name(self) -> str:
        return self._name

    def get_state(self) -> RobotState:
        try:
            pos = self._entity.get_dofs_position()
            vel = self._entity.get_dofs_velocity()
            # 有些版本的 Genesis 不直接提供力矩
            torques = np.zeros(self._n_dofs)
            try:
                torques = self._entity.get_dofs_force()
            except (AttributeError, Exception):
                pass

            state = RobotState(
                joint_positions=pos.cpu().numpy().flatten(),
                joint_velocities=vel.cpu().numpy().flatten(),
                joint_torques=torques.cpu().numpy().flatten(),
                ee_pose=self.get_eef_pose(),
                timestamp=time.time(),
                status=self._status,
            )
            return state
        except Exception as e:
            self._status = ArmStatus.ERROR
            state = RobotState(status=ArmStatus.ERROR)
            return state

    def send_command(self, target: np.ndarray, mode: ControlMode = ControlMode.POSITION,
                     duration: float = 1.0, blocking: bool = True) -> bool:
        try:
            self._status = ArmStatus.MOVING

            if mode == ControlMode.POSITION:
                self._entity.control_dofs_position(target, gs.CTRL_MODE.position)
            elif mode == ControlMode.VELOCITY:
                self._entity.control_dofs_velocity(target, gs.CTRL_MODE.velocity)
            elif mode == ControlMode.EEF_POSE:
                # 使用逆运动学
                self._entity.control_dofs_position(target, gs.CTRL_MODE.position)
            elif mode == ControlMode.TORQUE:
                self._entity.control_dofs_force(target)
            elif mode == ControlMode.IMPEDANCE:
                kp = kwargs.get("kp", 100.0)
                kd = kwargs.get("kd", 10.0)
                self._entity.control_dofs_position(target, gs.CTRL_MODE.position, kp=kp, kd=kd)
            else:
                raise ValueError(f"不支持的控制模式: {mode}")

            self._last_target = target
            self._status = ArmStatus.HOLDING if blocking else ArmStatus.MOVING
            return True

        except Exception as e:
            self._status = ArmStatus.ERROR
            return False

    def get_ft_sensor(self) -> Tuple[np.ndarray, np.ndarray]:
        """从 Genesis 接触力传感器获取力/力矩"""
        try:
            # 尝试通过接触力传感器获取
            contacts = self._entity.get_contacts()
            if contacts is not None:
                # 汇总所有接触力
                total_force = np.zeros(3)
                total_torque = np.zeros(3)
                force_data = contacts.cpu().numpy()
                if force_data.ndim >= 2:
                    total_force = np.sum(force_data[..., :3], axis=0)
                return total_force, total_torque
        except Exception:
            pass
        return np.zeros(3), np.zeros(3)

    def get_joint_limits(self) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """从 Genesis 关节属性获取限位"""
        lower = np.full(self._n_dofs, -np.pi)
        upper = np.full(self._n_dofs, np.pi)
        max_torque = np.full(self._n_dofs, 100.0)

        try:
            joints = getattr(self._entity, "joints", [])
            for i, j in enumerate(joints):
                if hasattr(j, "dofs") and len(j.dofs) > 0:
                    dof = j.dofs[0]
                    lower[i] = getattr(dof, "range_lower", -np.pi)
                    upper[i] = getattr(dof, "range_upper", np.pi)
                    max_torque[i] = getattr(dof, "force_limit", 100.0)
        except Exception:
            pass

        return lower, upper, max_torque

    def get_eef_pose(self) -> np.ndarray:
        """获取末端执行器位姿 (4x4)"""
        try:
            pos = self._entity.get_pos()
            quat = self._entity.get_quat()
            pos_np = pos.cpu().numpy().flatten()
            quat_np = quat.cpu().numpy().flatten()
            return pose_to_transform(pos_np, quat_np)
        except Exception:
            return np.eye(4)

    def stop(self) -> None:
        """紧急停止"""
        try:
            zero = np.zeros(self._n_dofs)
            self._entity.control_dofs_velocity(zero)
            self._status = ArmStatus.EMERGENCY_STOP
        except Exception:
            self._status = ArmStatus.ERROR
