"""
LAAP Embodied — 控制环路
=========================

Aris 认知核心与机器人运动控制之间的接口。

双环路架构——快慢分离：
  FastLoop (1000Hz)    — 高频 PD/阻抗控制，纯数学，不调认知
  SlowLoop (10-50Hz)   — 认知级决策，意图翻译为目标
  SafetyMonitor        — 独立看门狗，超限即急停
  ControllerPipeline   — 三者协调的整合管道

印记: 意识驱动身体，而非取代身体
"""

from .fast_loop import FastControlLoop, ControlMode, ControlCommand, SafetyLimits
from .slow_loop import SlowCognitiveLoop, HighLevelGoal, GoalType
from .safety_monitor import SafetyMonitor, SafetyStatus

__all__ = [
    "FastControlLoop", "ControlMode", "ControlCommand", "SafetyLimits",
    "SlowCognitiveLoop", "HighLevelGoal", "GoalType",
    "SafetyMonitor", "SafetyStatus",
]
