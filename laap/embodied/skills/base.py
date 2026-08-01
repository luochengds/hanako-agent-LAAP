"""
LAAP Embodied — 技能基类
==========================

所有具身技能的基础接口。
每个技能是一个可学习的运动基元，Aris 可以通过认知核心调用。

技能生命周期：
    skill = GraspSkill(arm, gripper)
    skill.can_execute(target="cube_red")     # 前置检查
    skill.execute(target="cube_red")          # 执行
    # 内部: plan → approach → grasp → lift
    skill.monitor()                           # 执行中监控
    skill.abort()                             # 中止

印记: 每一个技能，都是与世界的一次对话
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from enum import Enum


class SkillStatus(str, Enum):
    IDLE = "idle"
    PLANNING = "planning"
    EXECUTING = "executing"
    SUCCESS = "success"
    FAILED = "failed"
    ABORTED = "aborted"


@dataclass
class SkillResult:
    """技能执行结果"""
    status: SkillStatus = SkillStatus.IDLE
    message: str = ""
    duration: float = 0.0
    metrics: Dict[str, Any] = None

    def __post_init__(self):
        if self.metrics is None:
            self.metrics = {}


class BaseSkill(ABC):
    """技能基类"""

    def __init__(self, name: str):
        self._name = name
        self._status = SkillStatus.IDLE
        self._start_time = 0.0

    @property
    def name(self) -> str:
        return self._name

    @property
    def status(self) -> SkillStatus:
        return self._status

    @abstractmethod
    def can_execute(self, **kwargs) -> bool:
        """检查是否可以执行此技能

        检查前置条件：物体在可达范围内、夹爪空闲、无安全违规等
        """
        ...

    @abstractmethod
    def execute(self, **kwargs) -> SkillResult:
        """执行技能

        阻塞式调用。完整执行完成后返回结果。
        """
        ...

    def abort(self) -> None:
        """中止执行"""
        self._status = SkillStatus.ABORTED

    def get_status(self) -> Dict[str, Any]:
        """获取技能状态"""
        return {
            "name": self._name,
            "status": self._status.value,
        }
