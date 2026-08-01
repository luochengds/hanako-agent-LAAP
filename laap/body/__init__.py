"""LAAP Body Layer — 感知与执行层统一入口

Body 层封装 LAAP 对外的工具、模型、协议、技能、插件和网关能力，
作为 Aether 编排层（Petri net + Actor + PSI）与外部环境之间的可复用躯体。

公共子模块通过 `laap.body.*` 暴露，底层实现仍位于 `laap.tools.*`、`laap.llm.*` 等位置。
"""

from __future__ import annotations

from dataclasses import dataclass
from types import ModuleType
from typing import Any, Dict

# 将既有实现层重新导出为 body 层公共 API。
# 底层实现位置保持不变：`laap.tools.*`、`laap.llm.*` 等。
from laap import llm, mcp, skills, plugins, gateway

# The public ``laap.body.tools`` entry is the unified tool-registry module;
# importing it here ensures ``from laap.body import tools`` resolves correctly.
from laap.body import tools
from laap.body.session import Message, SessionManager

__all__ = [
    "tools",
    "llm",
    "mcp",
    "skills",
    "plugins",
    "gateway",
    "create_default_body_system",
    "BodySystem",
    "SessionManager",
    "Message",
]


@dataclass
class BodySystem:
    """LAAP Body 层子系统容器。

    提供对工具、LLM、MCP、技能、插件和网关子模块的便捷访问。
    """

    tools: ModuleType
    llm: ModuleType
    mcp: ModuleType
    skills: ModuleType
    plugins: ModuleType
    gateway: ModuleType
    config: Dict[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.config is None:
            self.config = {}


def create_default_body_system(config: Dict[str, Any] | None = None) -> BodySystem:
    """构造默认 Body 层子系统集合。

    Args:
        config: 可选配置字典，会注入到返回的 ``BodySystem.config`` 中。

    Returns:
        包含 ``tools``、``llm``、``mcp``、``skills``、``plugins``、``gateway``
        六个公共子模块的 ``BodySystem`` 实例。
    """
    return BodySystem(
        tools=tools,
        llm=llm,
        mcp=mcp,
        skills=skills,
        plugins=plugins,
        gateway=gateway,
        config=config or {},
    )
