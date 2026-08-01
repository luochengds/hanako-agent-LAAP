"""
LAAP Embodied — 硬件抽象层
============================

将不同机器人的硬件接口统一为 Aris 可以理解的抽象。

支持的机器人类型（规划）：
  • 机械臂：Franka Emika Panda (Genesis), UR5, Kinova
  • 夹爪：Franka Gripper (Genesis), Robotiq, BarrettHand
  • 移动底盘：Husky, Jackal, TurtleBot (规划)
  • 传感器套件：RGB-D, ForceTorque, IMU, Tactile

每个抽象提供标准接口：
  • get_state() → 关节位置/速度/力矩
  • send_command(cmd) → 目标位置/力/阻抗
  • get_sensors() → 力/触觉/视觉

印记: 每一种身体，同一个心灵
"""

from .base import (
    RobotState, ControlMode, ArmStatus,
    SensorReading, SensorSuiteSnapshot,
    pose_to_transform, transform_to_pose,
)
from .arm import RobotArm, GenesisArm
from .gripper import Gripper, GenesisGripper
from .sensors import SensorSuite, GenesisSensorSuite

__all__ = [
    "RobotArm", "GenesisArm",
    "Gripper", "GenesisGripper",
    "SensorSuite", "GenesisSensorSuite",
    "RobotState", "ControlMode", "ArmStatus",
    "SensorReading", "SensorSuiteSnapshot",
    "pose_to_transform", "transform_to_pose",
]
