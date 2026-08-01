"""
LAAP Embodied — ROS 2 传感器数据订阅器
==========================================

从真实机器人订阅传感器数据（关节状态、力传感器、相机等），
转换为 Aris 认知核心可以消费的格式。

用法：
    # 真实机器人
    sub = SensorSubscriber(node_name='aris_sensors')
    joint_state = sub.get_latest_joint_state()
    
    # 仿真/测试
    mock = MockSubscriber()
    mock.inject_joint_state(np.zeros(7), np.zeros(7))

印记: 看到世界
"""

from __future__ import annotations

import numpy as np
from typing import Optional, Dict, Any, Callable
from dataclasses import dataclass


@dataclass
class SensorMessage:
    """传感器消息（通用格式）"""
    timestamp: float = 0.0
    data: Optional[np.ndarray] = None
    frame_id: str = ""


try:
    import rclpy
    from rclpy.node import Node
    from sensor_msgs.msg import JointState, Image, Imu
    from geometry_msgs.msg import WrenchStamped
    from cv_bridge import CvBridge
    _ROS2_AVAILABLE = True
except ImportError:
    _ROS2_AVAILABLE = False
    CvBridge = None


class SensorSubscriber:
    """ROS 2 传感器订阅器

    订阅标准 ROS 2 传感器话题，缓存最新数据。
    """

    def __init__(self, node_name: str = 'aris_sensors'):
        self._node = None

        if _ROS2_AVAILABLE:
            rclpy.init(args=None)
            self._node = Node(node_name)

            # 关节状态
            self._joint_state = None
            self._node.create_subscription(
                JointState, '/joint_states', self._joint_cb, 10
            )
            # 力传感器
            self._wrench = None
            self._node.create_subscription(
                WrenchStamped, '/ft_sensor', self._ft_cb, 10
            )

    def _joint_cb(self, msg) -> None:
        self._joint_state = msg

    def _ft_cb(self, msg) -> None:
        self._wrench = msg

    def get_latest_joint_state(self) -> Optional[Dict[str, Any]]:
        """获取最新关节状态"""
        if self._joint_state is None:
            return None
        return {
            "name": list(self._joint_state.name),
            "position": np.array(self._joint_state.position),
            "velocity": np.array(self._joint_state.velocity),
            "effort": np.array(self._joint_state.effort),
            "timestamp": self._joint_state.header.stamp.sec
                       + self._joint_state.header.stamp.nanosec * 1e-9,
        }

    def get_latest_wrench(self) -> Optional[Dict[str, Any]]:
        """获取最新力/力矩读数"""
        if self._wrench is None:
            return None
        return {
            "force": np.array([
                self._wrench.wrench.force.x,
                self._wrench.wrench.force.y,
                self._wrench.wrench.force.z,
            ]),
            "torque": np.array([
                self._wrench.wrench.torque.x,
                self._wrench.wrench.torque.y,
                self._wrench.wrench.torque.z,
            ]),
        }

    def spin_once(self, timeout: float = 0.01) -> None:
        """处理一个 ROS 消息"""
        if _ROS2_AVAILABLE and self._node is not None:
            rclpy.spin_once(self._node, timeout_sec=timeout)

    def destroy(self) -> None:
        if _ROS2_AVAILABLE and self._node is not None:
            self._node.destroy_node()
            rclpy.shutdown()


class MockSubscriber:
    """仿真/测试用模拟订阅器"""

    def __init__(self):
        self._joint_state: Optional[Dict] = None
        self._wrench: Optional[Dict] = None
        self._callbacks: Dict[str, Callable] = {}

    def inject_joint_state(self, positions: np.ndarray,
                           velocities: Optional[np.ndarray] = None,
                           efforts: Optional[np.ndarray] = None,
                           names: Optional[list] = None) -> None:
        """注入模拟关节状态"""
        self._joint_state = {
            "name": names or [f'joint{i}' for i in range(len(positions))],
            "position": np.array(positions),
            "velocity": np.array(velocities) if velocities is not None else np.zeros_like(positions),
            "effort": np.array(efforts) if efforts is not None else np.zeros_like(positions),
            "timestamp": 0.0,
        }

    def inject_wrench(self, force: np.ndarray,
                      torque: np.ndarray) -> None:
        """注入模拟力/力矩"""
        self._wrench = {
            "force": np.array(force),
            "torque": np.array(torque),
        }

    def get_latest_joint_state(self) -> Optional[Dict]:
        return self._joint_state

    def get_latest_wrench(self) -> Optional[Dict]:
        return self._wrench

    def spin_once(self, timeout: float = 0.01) -> None:
        pass
