"""LAAP — AGI Agent Layer v3.0

统一对外入口: `from laap.agent_core.agent import Agent`
本包保留 AGIBrain 等组件供高级用户直接使用。
"""
from laap.agent.base import (
    AGIBrain, AgentConfig, ToolCallLoop,
    AttentionController, AttentionFocus,
    # 向后兼容别名 (会触发 DeprecationWarning)
    Agent,
)
from laap.agent.lifelike import LifelikeAgent, LifelikeConfig
from laap.agent.codex import CodexAgent, CodexConfig
from laap.agent.context import ContextManager, compress_messages
from laap.agent.meta_cognition import (
    MetaCognitionEngine, CognitiveTrace, CognitiveStrategy,
    MetaCognitiveState, ThinkingMode, CognitiveBias,
)
from laap.agent.parliament import (
    Parliament, MemberProfile, MemberRole,
    Deliberation, Opinion, AgendaItem,
)

__all__ = [
    # Core (v3.0 — AGIBrain 是正式名称, Agent 是弃用别名)
    "AGIBrain", "AgentConfig", "ToolCallLoop",
    "AttentionController", "AttentionFocus",
    "Agent",  # 弃用别名, 触发 DeprecationWarning
    # Lifelike
    "LifelikeAgent", "LifelikeConfig",
    # Codex
    "CodexAgent", "CodexConfig",
    # Context
    "ContextManager", "compress_messages",
    # Meta-Cognition
    "MetaCognitionEngine", "CognitiveTrace", "CognitiveStrategy",
    "MetaCognitiveState", "ThinkingMode", "CognitiveBias",
    # Parliament
    "Parliament", "MemberProfile", "MemberRole",
    "Deliberation", "Opinion", "AgendaItem",
]
