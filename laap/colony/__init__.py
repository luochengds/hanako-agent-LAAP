"""LAAP Colony — 数字生命体集群

Colony 是 LAAP 2.0 的多 Agent 协作框架，包含各种特化的数字生命体。

使用:
    from laap.colony import (
        ColonyProtocol, TaskDispatcher, CollaborationScenario,
        AgentMessage, TestEngineerAgent,
    )

延迟导入（需要 laap.agi 依赖）:
    from laap.colony import get_available_agents
    agents = get_available_agents()  # 返回可用的 Agent 类字典
"""

from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger("laap.colony")

# 轻量协议层 — 无外部依赖，始终可用
from laap.colony.protocol import (
    AgentMessage,
    ColonyProtocol,
    CollaborationScenario,
    TaskDispatcher,
)
from laap.colony.doc_agent import DocAgent
from laap.colony.performance_agent import PerformanceAgent
from laap.colony.security_agent import SecurityAgent

# 需要 AGI 模块的 Agent — 尝试导入，失败则降级
_heavy_agents: Dict[str, Any] = {}

try:
    from laap.colony.architect import ArchitectAgent
    from laap.colony.test_engineer import TestEngineerAgent

    _heavy_agents["ArchitectAgent"] = ArchitectAgent
    _heavy_agents["TestEngineerAgent"] = TestEngineerAgent
    _ARCHITECT_AVAILABLE = True
except ImportError as e:
    _ARCHITECT_AVAILABLE = False
    logger.warning("ArchitectAgent/TestEngineerAgent 不可用 (需要 laap.agi): %s", e)


def get_available_agents() -> Dict[str, Any]:
    """返回所有可用的 Agent 类字典（key=类名, value=类本身）。"""
    agents: Dict[str, Any] = {
        # 轻量 Agent（始终可用）
        "DocAgent": DocAgent,
        "PerformanceAgent": PerformanceAgent,
        "SecurityAgent": SecurityAgent,
    }
    agents.update(_heavy_agents)
    return agents


__all__ = [
    "AgentMessage",
    "ColonyProtocol",
    "CollaborationScenario",
    "TaskDispatcher",
    "DocAgent",
    "PerformanceAgent",
    "SecurityAgent",
    "ArchitectAgent",
    "TestEngineerAgent",
    "get_available_agents",
]
