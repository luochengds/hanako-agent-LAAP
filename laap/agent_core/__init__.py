"""LAAP Agent Core — 统一对外入口

推荐用法:
    from laap.agent_core.agent import Agent, AgentConfig
    agent = Agent(mode="kernel" | "hermes" | "agi")

向后兼容:
    from laap.agent_core import LAAPAgent  # = Agent (mode="hermes" 子类)
"""
from laap.agent_core.agent import (
    Agent, AgentConfig, AgentState, AgentMode, LAAPAgent,
)
from laap.agent_core.planner import Planner, Task, Plan
from laap.agent_core.executor import Executor
from laap.agent_core.context import Context, Message, Role
from laap.agent_core.llm_provider import LLMProvider, LLMConfig, LLMResponse
from laap.agent_core.tool_manager import ToolManager, Tool, ToolResult
from laap.agent_core.memory_bridge import MemoryBridge

__all__ = [
    # 统一对外类
    "Agent", "AgentConfig", "AgentState", "AgentMode",
    # 向后兼容别名
    "LAAPAgent",
    # 组件
    "Planner", "Task", "Plan", "Executor",
    "Context", "Message", "Role",
    "LLMProvider", "LLMConfig", "LLMResponse",
    "ToolManager", "Tool", "ToolResult",
    "MemoryBridge",
]
