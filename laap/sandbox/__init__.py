"""LAAP Sandbox — 数字生命体认知沙箱

Cognitive Sandbox 是 LAAP 2.0 Living Runtime 的核心容器，
封装每个数字生命体的全部认知状态，确保隔离性。

核心组件：
    - CognitiveSandbox: 数字生命体容器（8 个认知子系统）
    - Boundary: 认知边界（控制输入输出）
    - ResourceBudget: 资源预算（防止资源耗尽）
    - ColonyEventBus: 跨 sandbox 通信总线
    - SkillLibrary: 全局只读技能库
"""

from laap.sandbox._types import (
    BuildState,
    ColonyEvent,
    DependencyReport,
    FileTreeState,
    GitState,
    ProjectSnapshot,
    SandboxConfig,
    SandboxID,
    Suggestion,
    TechDebtReport,
    TestState,
    WorkspaceEvent,
)
from laap.sandbox.boundary import Boundary
from laap.sandbox.colony import ColonyEventBus
from laap.sandbox.container import CognitiveSandbox
from laap.sandbox.migration import (
    LAAPSNAP_MAGIC,
    LAAPSNAP_VERSION,
    SnapHeader,
    export_sandbox,
    import_sandbox,
)
from laap.sandbox.resource_budget import DegradationLevel, ResourceBudget, ResourceType
from laap.sandbox.skill_library import Skill, SkillLibrary

__all__ = [
    # 数据类型
    "SandboxID", "SandboxConfig", "Suggestion",
    "ProjectSnapshot", "GitState", "FileTreeState", "TestState",
    "BuildState", "TechDebtReport", "DependencyReport",
    "WorkspaceEvent", "ColonyEvent",
    # 技能库
    "Skill", "SkillLibrary",
    # 核心组件
    "Boundary", "ResourceBudget", "ResourceType", "DegradationLevel",
    "ColonyEventBus", "CognitiveSandbox",
    # 迁移工具
    "export_sandbox", "import_sandbox", "SnapHeader",
    "LAAPSNAP_VERSION", "LAAPSNAP_MAGIC",
]
