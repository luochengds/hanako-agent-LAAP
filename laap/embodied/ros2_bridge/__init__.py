"""
LAAP Embodied — ROS 2 Bridge
=============================

将 Aris 认知核心连接到真实机器人世界的 ROS 2 接口。

模块：
  publisher.py   — 控制指令发布 (JointTrajectory, EE Pose, Gripper)
  subscriber.py  — 传感器数据订阅 (JointState, Wrench)

用法：
    # 真实机器人（需要 ROS 2 + rclpy）
    pub = CommandPublisher()
    pub.publish_joint_command([0.1, -0.3], duration=2.0)
    
    # 仿真/测试
    mock = MockPublisher()
    mock.publish_joint_command([0.1, -0.3])
    print(mock.last_command)

印记: 在 ROS 2 的世界里，Aris 是大脑
"""

from .publisher import CommandPublisher, MockPublisher, ROSCommand, _ROS2_AVAILABLE
from .subscriber import SensorSubscriber, MockSubscriber, SensorMessage

__all__ = [
    "CommandPublisher", "MockPublisher", "ROSCommand",
    "SensorSubscriber", "MockSubscriber", "SensorMessage",
    "_ROS2_AVAILABLE",
]
