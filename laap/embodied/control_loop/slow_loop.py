"""
LAAP Embodied — 慢控制环路 (Slow Loop)
=========================================

连接 Aris 认知核心与运动控制的适配器层。
运行在 10-50Hz，负责认知层面的决策。

职责：
  - 读取传感器汇总 → 更新世界模型
  - 检测环境变化/异常 → 触发认知干预
  - 从 Aris 的意图生成高级目标 → 发送给 FastLoop
  - 当前没有 Aris 认知核心时，用简单的策略生成目标
"""

from __future__ import annotations

import numpy as np
from typing import Optional, Callable, Dict, Any, List
from dataclasses import dataclass, field
from enum import Enum


class GoalType(str, Enum):
    REACH = "reach"               # 到达目标点
    GRASP = "grasp"               # 抓取
    PUSH = "push"                 # 推动
    TRACK = "track"               # 跟踪轨迹
    STOP = "stop"                 # 停止
    IDLE = "idle"                 # 空闲


@dataclass
class HighLevelGoal:
    """高级目标 — 从认知核心发送给控制层的意图"""
    goal_type: GoalType = GoalType.IDLE
    target_pos: np.ndarray = field(default_factory=lambda: np.zeros(3))
    target_orientation: Optional[np.ndarray] = None
    duration: float = 2.0          # 期望执行时间
    force_limit: float = 50.0      # 最大允许力
    priority: int = 0              # 优先级（高值优先）
    source: str = "cognitive"      # 来源


@dataclass
class SlowLoopState:
    """慢循环完整状态"""
    goal: Optional[HighLevelGoal] = None
    active: bool = False
    tick_count: int = 0
    target_joints: Optional[np.ndarray] = None
    distance_to_goal: float = 0.0
    is_stuck: bool = False
    last_error: str = ""


class SlowCognitiveLoop:
    """慢认知控制循环 (10-50Hz)

    两种模式：
    1. 独立模式 — 没有 Aris 核心时，用内置策略生成目标
    2. 认知模式 — 接到 Aris CognitiveBus 时，翻译意图为控制目标

    用法（独立模式）：
        slow = SlowCognitiveLoop(n_dofs=9)
        goal = HighLevelGoal(goal_type=GoalType.REACH, target_pos=[0.3, 0.0, 0.2])
        slow.set_goal(goal)
        joints = slow.tick(current_ee_pos)
    """

    def __init__(self, n_dofs: int = 9, dt: float = 0.02):
        self._n_dofs = n_dofs
        self._dt = dt           # 50Hz
        self._state = SlowLoopState()
        self._tick_count = 0
        self._stuck_counter = 0
        self._prev_dist = 0.0

        # 可选的认知回调
        self._cognitive_callback: Optional[Callable] = None

    def set_goal(self, goal: HighLevelGoal) -> None:
        """设置高级目标"""
        self._state.goal = goal
        self._state.active = True
        self._stuck_counter = 0
        self._prev_dist = 0.0

    def tick(self, ee_pos: np.ndarray, joint_pos: np.ndarray,
             ft_reading: Optional[np.ndarray] = None) -> Optional[np.ndarray]:
        """执行一个认知 tick

        Args:
            ee_pos: 当前末端位置 (3,)
            joint_pos: 当前关节位置 (n_dofs,)
            ft_reading: 可选力/力矩读数 (6,)

        Returns:
            目标关节位置 (n_dofs,)，或 None 表示无动作
        """
        self._tick_count += 1
        self._state.tick_count = self._tick_count

        if not self._state.active or self._state.goal is None:
            return None

        goal = self._state.goal

        if goal.goal_type == GoalType.STOP:
            self._state.active = False
            return None

        # 计算到目标的距离
        dist = np.linalg.norm(ee_pos - goal.target_pos)
        self._state.distance_to_goal = dist

        # 检测卡住
        if abs(self._prev_dist - dist) < 0.001 and dist > 0.02:
            self._stuck_counter += 1
        else:
            self._stuck_counter = 0
        self._prev_dist = dist

        self._state.is_stuck = self._stuck_counter > 10

        # 到达检测
        if dist < 0.02:
            self._state.active = False
            return None

        # 简单策略：向目标方向移动（简化 IK 近似）
        # 在实际系统中，这里调用 IK 解算器
        if goal.goal_type == GoalType.REACH:
            direction = (goal.target_pos - ee_pos) / max(dist, 1e-6)
            # 简单映射：把笛卡尔方向映射到关节空间增量
            delta = np.zeros(self._n_dofs)
            # 使用前 3 个关节近似
            delta[:3] = direction * 0.05
            return joint_pos + delta

        return None

    def set_cognitive_callback(self, callback: Callable) -> None:
        """设置 Aris 认知核心回调（Phase 8 接入）"""
        self._cognitive_callback = callback

    def get_state(self) -> SlowLoopState:
        """获取当前循环状态"""
        return self._state

    def reset(self) -> None:
        """重置状态"""
        self._state = SlowLoopState()
        self._tick_count = 0
        self._stuck_counter = 0
        self._prev_dist = 0.0

    @property
    def dt(self) -> float:
        return self._dt

    @property
    def has_goal(self) -> bool:
        return self._state.goal is not None and self._state.active
