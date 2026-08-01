# -*- coding: utf-8 -*-
"""LAAP × SimWorld 集成模块.

实现"阶段 A:LAAPBrain 替换 A2ALLM"+"阶段 B:EventedCommunicator + 状态同步"。
把 LAAP 的因果/反事实/PSI 能力注入 SimWorld 的 LLM 决策环节，
同时把 SimWorld 的真实感知/物理反馈注入 LAAP 的认知总线。

组件:
  - LAAPBrain: 继承 SimWorld A2ALLM，在 generate_instructions 中调用
    LAAP UnifiedCausalEngine 做反事实推演，选择 regret 最低的动作。
  - EventedCommunicator: 继承 SimWorld Communicator，在关键方法前后
    向 LAAP CognitiveBus 发布 PERCEPTION_INCOMING / ACTION_TAKEN 事件。
  - MockCommunicator: 鸭子类型 Communicator，内存虚拟 2D 世界，
    不连接 UE，用于 headless 测试和 CI。
  - SimWorldBridge: 双向桥接 SimWorld 与 LAAP UnifiedWorldModel。
  - SimWorldConfig: 集成运行时配置。

Usage:
    from laap.integrations.simworld import (
        LAAPBrain, EventedCommunicator, MockCommunicator,
        SimWorldBridge, SimWorldConfig,
    )

    cfg = SimWorldConfig(use_mock=True)
    comm = MockCommunicator()
    brain = LAAPBrain(
        causal_engine=UnifiedCausalEngine(),
        world_model=UnifiedWorldModel(),
        cognitive_bus=CognitiveBus(),
    )
    bridge = SimWorldBridge(comm, brain.world_model, brain.cognitive_bus)
"""

from __future__ import annotations

from laap.integrations.simworld.brain import LAAPBrain
from laap.integrations.simworld.communicator import (
    EventedCommunicator,
    MockCommunicator,
)
from laap.integrations.simworld.bridge import SimWorldBridge
from laap.integrations.simworld.config import SimWorldConfig

__all__ = [
    "LAAPBrain",
    "EventedCommunicator",
    "MockCommunicator",
    "SimWorldBridge",
    "SimWorldConfig",
]
__version__ = "0.1.0"
