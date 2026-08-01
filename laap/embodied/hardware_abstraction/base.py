"""
LAAP Embodied — 硬件抽象层共享类型
===================================

定义所有硬件抽象模块共用的数据结构、枚举和变换工具。
"""

from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Tuple, Dict, Any


class ControlMode(str, Enum):
    """控制模式"""
    POSITION = "position"       # 位置控制 (关节空间)
    VELOCITY = "velocity"       # 速度控制
    TORQUE = "torque"           # 力矩控制
    IMPEDANCE = "impedance"     # 阻抗控制 (力位混合)
    EEF_POSE = "eef_pose"       # 末端位姿控制 (笛卡尔空间)


class ArmStatus(str, Enum):
    """机械臂状态"""
    IDLE = "idle"
    MOVING = "moving"
    HOLDING = "holding"         # 在目标位置保持
    STALLED = "stalled"         # 堵转/卡住
    ERROR = "error"
    EMERGENCY_STOP = "emergency_stop"
    DISCONNECTED = "disconnected"


@dataclass
class RobotState:
    """机器人完整状态快照"""
    joint_positions: np.ndarray = field(default_factory=lambda: np.zeros(7))
    joint_velocities: np.ndarray = field(default_factory=lambda: np.zeros(7))
    joint_torques: np.ndarray = field(default_factory=lambda: np.zeros(7))
    ee_pose: np.ndarray = field(default_factory=lambda: np.eye(4))
    ee_velocity: np.ndarray = field(default_factory=lambda: np.zeros(6))
    gripper_opening: float = 0.0       # 0=closed, 1=open
    gripper_force: float = 0.0         # N
    timestamp: float = 0.0
    status: ArmStatus = ArmStatus.IDLE

    def to_dict(self) -> Dict[str, Any]:
        return {
            "joint_positions": self.joint_positions.tolist(),
            "joint_velocities": self.joint_velocities.tolist(),
            "joint_torques": self.joint_torques.tolist(),
            "ee_pose": self.ee_pose.tolist(),
            "ee_velocity": self.ee_velocity.tolist(),
            "gripper_opening": self.gripper_opening,
            "gripper_force": self.gripper_force,
            "timestamp": self.timestamp,
            "status": self.status.value,
        }


@dataclass
class SensorReading:
    """单传感器读数"""
    modality: str          # "rgb", "depth", "force", "tactile", "imu"
    data: np.ndarray
    timestamp: float = 0.0
    frame_id: str = "world"


@dataclass
class SensorSuiteSnapshot:
    """传感器套件快照"""
    rgb: Optional[np.ndarray] = None       # HxWx3 uint8
    depth: Optional[np.ndarray] = None     # HxW float (meters)
    force_torque: Optional[np.ndarray] = None  # (Fx,Fy,Fz,Tx,Ty,Tz)
    joint_states: Optional[RobotState] = None
    imu: Optional[np.ndarray] = None       # (ax,ay,az,gx,gy,gz)
    tactile: Optional[np.ndarray] = None   # NxM tactile grid
    timestamp: float = 0.0


def pose_to_transform(pos: np.ndarray, quat: np.ndarray) -> np.ndarray:
    """(位置 xyz, 四元数 wxyz) → 4x4 变换矩阵"""
    import numpy as np
    qw, qx, qy, qz = quat
    T = np.eye(4)
    T[0, 0] = 1 - 2*qy**2 - 2*qz**2
    T[0, 1] = 2*qx*qy - 2*qw*qz
    T[0, 2] = 2*qx*qz + 2*qw*qy
    T[1, 0] = 2*qx*qy + 2*qw*qz
    T[1, 1] = 1 - 2*qx**2 - 2*qz**2
    T[1, 2] = 2*qy*qz - 2*qw*qx
    T[2, 0] = 2*qx*qz - 2*qw*qy
    T[2, 1] = 2*qy*qz + 2*qw*qx
    T[2, 2] = 1 - 2*qx**2 - 2*qy**2
    T[:3, 3] = pos
    return T


def transform_to_pose(T: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """4x4 变换矩阵 → (位置 xyz, 四元数 wxyz)"""
    pos = T[:3, 3].copy()
    R = T[:3, :3]
    trace = R[0, 0] + R[1, 1] + R[2, 2]
    if trace > 0:
        s = np.sqrt(trace + 1.0) * 2
        qw = 0.25 * s
        qx = (R[2, 1] - R[1, 2]) / s
        qy = (R[0, 2] - R[2, 0]) / s
        qz = (R[1, 0] - R[0, 1]) / s
    else:
        # 处理数值不稳定情况
        qw, qx, qy, qz = 1.0, 0.0, 0.0, 0.0
    return pos, np.array([qw, qx, qy, qz])
