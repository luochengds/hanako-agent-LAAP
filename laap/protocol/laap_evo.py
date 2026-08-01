"""LAAP-EVO 进化引擎协议

定义生命体变异-选择-传播闭环的协议契约。本模块仅定义抽象基类与数据类，
具体实现由 `realize-laap-agi-vision` spec 的 M4 阶段（True RSI）完成。

References:
- LAAP2.0大版本升级方案 § LAAP-EVO
- realize-laap-agi-vision spec M4 Task E1-E4
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class MutationType(Enum):
    """变异类型"""
    SKILL_NEW = "skill_new"  # 新技能生成
    SKILL_REFINE = "skill_refine"  # 现有技能精化
    PARAMETER_TUNING = "parameter_tuning"  # 参数调优
    ARCHITECTURE_CHANGE = "architecture_change"  # 架构变更
    BEHAVIOR_ADJUST = "behavior_adjust"  # 行为调整


class SelectionStatus(Enum):
    """选择评估状态"""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    ROLLED_BACK = "rolled_back"


@dataclass
class MutationProposal:
    """变异提议"""
    proposal_id: str
    mutation_type: MutationType
    capability_gap: str  # 触发变异的能力缺口描述
    target_module: str  # 目标模块路径
    proposed_change: Dict[str, Any]  # 提议的变更内容（AST diff 或参数 diff）
    expected_benefit: str  # 预期收益描述
    risk_assessment: str = "unknown"  # 风险评估：low/medium/high/unknown
    created_at: datetime = field(default_factory=datetime.utcnow)
    sandbox_id: Optional[str] = None  # 提议来源的 sandbox


@dataclass
class ExperiencePacket:
    """经验包：用于跨生命体传播"""
    experience_id: str
    source_sandbox_id: str
    task_context: Dict[str, Any]  # 任务上下文
    outcome: Dict[str, Any]  # 结果与教训
    lesson_summary: str  # 经验教训一句话总结
    confidence: float = 0.0  # 置信度 [0, 1]
    timestamp: datetime = field(default_factory=datetime.utcnow)
    tags: List[str] = field(default_factory=list)


@dataclass
class SelectionReport:
    """选择评估报告"""
    proposal_id: str
    status: SelectionStatus
    test_results: Dict[str, Any]  # 测试结果
    performance_delta: float  # 性能变化（正为提升）
    quality_delta: float  # 质量变化
    decided_at: datetime = field(default_factory=datetime.utcnow)
    decided_by: str = "auto"  # auto/human
    rollback_reason: Optional[str] = None


class EvolutionProtocol(ABC):
    """LAAP-EVO 进化引擎协议抽象基类

    定义生命体内生的变异-选择-传播闭环。所有方法均为抽象方法，
    具体实现由子类提供（如 TrueRSIEngine、ParameterTuningEngine 等）。
    """

    @abstractmethod
    def propose_mutation(self, capability_gap: str) -> MutationProposal:
        """基于能力缺口生成变异提议

        Args:
            capability_gap: 能力缺口描述（如"无法处理 XX 类型任务"）

        Returns:
            MutationProposal 包含提议的变更内容
        """
        ...

    @abstractmethod
    def select_variant(
        self, proposal: MutationProposal, test_results: Dict[str, Any]
    ) -> SelectionReport:
        """评估变异候选是否通过选择

        在四区沙箱的 Sandbox/Quarantine 区运行测试套件，
        基于测试结果、性能、质量指标决定 approve/reject。

        Args:
            proposal: 变异提议
            test_results: 测试结果数据

        Returns:
            SelectionReport 包含决策与指标
        """
        ...

    @abstractmethod
    def propagate_experience(self, experience: ExperiencePacket) -> None:
        """传播经验到其他生命体

        通过 ColonyEventBus 广播 ExperiencePropagation 事件，
        让其他 sandbox 学习此次经验。

        Args:
            experience: 经验包
        """
        ...

    @abstractmethod
    def list_proposals(
        self, status: Optional[SelectionStatus] = None
    ) -> List[MutationProposal]:
        """查询变异提议历史

        Args:
            status: 可选的状态过滤

        Returns:
            提议列表（按时间倒序）
        """
        ...
