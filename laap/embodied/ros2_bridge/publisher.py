"""
LAAP Embodied — ROS 2 控制指令发布器
========================================

将 Aris 的控制指令发布到真实机器人。
使用 ROS 2 标准消息类型 (JointTrajectory, WrenchStamped 等)。

注意：需要安装 ROS 2 和 rclpy。纯仿真环境下使用 MockPublisher 代替。

用法：
    # 真实机器人（需要 ROS 2 环境）
    pub = CommandPublisher(node_name='aris_cortex')
    pub.publish_joint_command([0.1, -0.3, ...], ['joint1', 'joint2', ...])
    pub.publish_ee_pose([0.3, 0.0, 0.2], [1, 0, 0, 0])
    
    # 仿真/测试模式
    mock = MockPublisher()
    mock.publish_joint_command([0.1, -0.3, ...])
    print(mock.last_command)

印记: 意识驱动身体
"""

from __future__ import annotations

import numpy as np
from typing import Optional, List, Dict, Any
from dataclasses import dataclass


@dataclass
class ROSCommand:
    """ROS 控制指令（用于记录/回放）"""
    timestamp: float = 0.0
    joint_positions: Optional[np.ndarray] = None
    joint_velocities: Optional[np.ndarray] = None
    ee_pose: Optional[np.ndarray] = None
    gripper_command: Optional[float] = None


try:
    import rclpy
    from rclpy.node import Node
    from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint
    from geometry_msgs.msg import PoseStamped, WrenchStamped
    from std_msgs.msg import Float64
    _ROS2_AVAILABLE = True
except ImportError:
    _ROS2_AVAILABLE = False


class CommandPublisher:
    """ROS 2 控制指令发布器

    发布到标准 ROS 2 控制话题。
    """

    def __init__(self, node_name: str = 'aris_cortex',
                 joint_topics: Optional[List[str]] = None):
        self._node = None
        self._joint_pubs = []
        self._ee_pub = None
        self._gripper_pub = None

        if _ROS2_AVAILABLE:
            rclpy.init(args=None)
            self._node = Node(node_name)
            # 关节位置控制器话题
            self._joint_pubs = []
            if joint_topics:
                for topic in joint_topics:
                    pub = self._node.create_publisher(
                        JointTrajectory, topic, 10
                    )
                    self._joint_pubs.append(pub)
            # 末端位姿话题
            self._ee_pub = self._node.create_publisher(
                PoseStamped, '/ee_target_pose', 10
            )
            # 夹爪话题
            self._gripper_pub = self._node.create_publisher(
                Float64, '/gripper_command', 10
            )
        else:
            import warnings
            warnings.warn("ROS 2 (rclpy) 未安装。使用 MockPublisher 进行测试。")

    def publish_joint_command(self, positions: np.ndarray,
                              joint_names: Optional[List[str]] = None,
                              velocities: Optional[np.ndarray] = None,
                              duration: float = 1.0) -> bool:
        """发布关节位置指令"""
        if not _ROS2_AVAILABLE or self._node is None:
            return False

        msg = JointTrajectory()
        msg.joint_names = joint_names or [f'joint{i}' for i in range(len(positions))]

        point = JointTrajectoryPoint()
        point.positions = positions.tolist()
        if velocities is not None:
            point.velocities = velocities.tolist()
        point.time_from_start.sec = int(duration)
        point.time_from_start.nanosec = int((duration % 1.0) * 1e9)
        msg.points = [point]

        for pub in self._joint_pubs:
            pub.publish(msg)
        return True

    def publish_ee_pose(self, position: np.ndarray,
                        orientation: Optional[np.ndarray] = None) -> bool:
        """发布末端位姿指令"""
        if not _ROS2_AVAILABLE or self._node is None:
            return False

        msg = PoseStamped()
        msg.header.stamp = self._node.get_clock().now().to_msg()
        msg.pose.position.x = float(position[0])
        msg.pose.position.y = float(position[1])
        msg.pose.position.z = float(position[2])
        if orientation is not None:
            msg.pose.orientation.w = float(orientation[0])
            msg.pose.orientation.x = float(orientation[1])
            msg.pose.orientation.y = float(orientation[2])
            msg.pose.orientation.z = float(orientation[3])
        self._ee_pub.publish(msg)
        return True

    def publish_gripper(self, width: float) -> bool:
        """发布夹爪指令 (0=closed, 1=open)"""
        if not _ROS2_AVAILABLE or self._node is None:
            return False
        msg = Float64()
        msg.data = width
        self._gripper_pub.publish(msg)
        return True

    def destroy(self) -> None:
        if self._node is not None:
            self._node.destroy_node()
            rclpy.shutdown()


class MockPublisher:
    """仿真/测试用模拟发布器

    不连接真实 ROS 2，记录所有发布的指令供测试和验证。
    """

    def __init__(self):
        self.last_command: Optional[ROSCommand] = None
        self.command_history: List[ROSCommand] = []
        self._publish_count = 0

    def publish_joint_command(self, positions: np.ndarray,
                              joint_names: Optional[List[str]] = None,
                              velocities: Optional[np.ndarray] = None,
                              duration: float = 1.0) -> bool:
        cmd = ROSCommand(
            joint_positions=np.array(positions),
            joint_velocities=np.array(velocities) if velocities is not None else None,
        )
        self.last_command = cmd
        self.command_history.append(cmd)
        self._publish_count += 1
        return True

    def publish_ee_pose(self, position: np.ndarray,
                        orientation: Optional[np.ndarray] = None) -> bool:
        T = np.eye(4)
        T[:3, 3] = position
        cmd = ROSCommand(ee_pose=T)
        self.last_command = cmd
        self.command_history.append(cmd)
        self._publish_count += 1
        return True

    def publish_gripper(self, width: float) -> bool:
        cmd = ROSCommand(gripper_command=width)
        self.last_command = cmd
        self.command_history.append(cmd)
        self._publish_count += 1
        return True

    @property
    def publish_count(self) -> int:
        return self._publish_count
