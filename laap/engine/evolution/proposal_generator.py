"""
LAAP — Phase 3 自动提案生成系统

自动提案生成系统负责：
1. 分析当前系统状态和性能指标
2. 基于历史数据和趋势检测优化机会
3. 自动生成改进提案
4. 评估提案的风险和预期收益
5. 与认知引擎和记忆系统深度集成

支持的提案类型：
- 配置优化提案
- 技能学习提案
- 任务规划提案
- 资源分配提案
- 架构改进提案

Phase 3 验证指标：自动改进成功率 > 60%
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple
import time
import uuid
import math
import logging

from laap.engine.evolution.proposal import (
    EvolutionProposal, ProposalStatus, RiskLevel, ProposalFactory
)
from laap.cognition.integrated_engine import IntegratedCognitiveEngine, ExperienceEvent
from laap.memory.long_term import LongTermMemory, MemoryType

logger = logging.getLogger("engine.evolution.proposal_generator")


# ──────────────────────────────────────────────────────────────────────
# 提案类型定义
# ──────────────────────────────────────────────────────────────────────

class ProposalCategory(str, Enum):
    """提案类别"""
    CONFIG_OPTIMIZATION = "config_optimization"    # 配置优化
    SKILL_LEARNING = "skill_learning"              # 技能学习
    TASK_PLANNING = "task_planning"                # 任务规划
    RESOURCE_ALLOCATION = "resource_allocation"    # 资源分配
    ARCHITECTURE_IMPROVEMENT = "architecture_improvement"  # 架构改进
    PROCEDURE_OPTIMIZATION = "procedure_optimization"      # 流程优化
    MEMORY_CONSOLIDATION = "memory_consolidation"  # 记忆巩固
    EMOTION_REGULATION = "emotion_regulation"      # 情绪调节


class ProposalPriority(str, Enum):
    """提案优先级"""
    CRITICAL = "critical"   # 紧急 - 需要立即处理
    HIGH = "high"           # 高 - 优先处理
    MEDIUM = "medium"       # 中 - 常规处理
    LOW = "low"             # 低 - 空闲时处理


@dataclass
class ProposalTemplate:
    """提案模板"""
    category: ProposalCategory
    priority: ProposalPriority
    target_pattern: str
    rationale_template: str
    expected_gain_range: Tuple[float, float]
    risk_level: RiskLevel
    required_tests: List[str] = field(default_factory=list)
    estimated_effort: float = 1.0  # 相对工作量


@dataclass
class OptimizationOpportunity:
    """优化机会"""
    category: ProposalCategory
    target: str
    current_value: Any
    proposed_value: Any
    rationale: str
    expected_gain: float
    confidence: float = 0.7
    supporting_evidence: List[str] = field(default_factory=list)


# ──────────────────────────────────────────────────────────────────────
# 提案生成器核心
# ──────────────────────────────────────────────────────────────────────

class AutoProposalGenerator:
    """
    自动提案生成器
    
    核心功能：
    1. 从认知引擎获取状态信息
    2. 从长期记忆检索相关经验
    3. 分析系统指标检测优化机会
    4. 生成具体的改进提案
    5. 评估提案质量和风险
    """
    
    def __init__(self, cognitive_engine: IntegratedCognitiveEngine = None):
        self.cognitive_engine = cognitive_engine
        self.memory = cognitive_engine.long_term_memory if cognitive_engine else None
        
        # 提案模板库
        self._proposal_templates = self._init_templates()
        
        # 生成历史
        self._generation_history: List[GeneratedProposalRecord] = []
        self._max_history = 100
        
        # 统计指标
        self._total_proposals_generated = 0
        self._total_proposals_approved = 0
        self._total_proposals_deployed = 0
        
        logger.info("自动提案生成系统初始化完成")
    
    def _init_templates(self) -> List[ProposalTemplate]:
        """初始化提案模板库"""
        return [
            # 配置优化模板
            ProposalTemplate(
                category=ProposalCategory.CONFIG_OPTIMIZATION,
                priority=ProposalPriority.MEDIUM,
                target_pattern="config.*",
                rationale_template="检测到配置参数 {target} 偏离最优值，建议调整以提升性能",
                expected_gain_range=(0.1, 0.3),
                risk_level=RiskLevel.LOW,
                required_tests=["性能回归测试", "配置验证"]
            ),
            
            # 技能学习模板
            ProposalTemplate(
                category=ProposalCategory.SKILL_LEARNING,
                priority=ProposalPriority.HIGH,
                target_pattern="skill.*",
                rationale_template="检测到能力需求未满足，建议学习新技能 {target}",
                expected_gain_range=(0.2, 0.5),
                risk_level=RiskLevel.LOW,
                required_tests=["技能评估", "应用测试"],
                estimated_effort=2.0
            ),
            
            # 流程优化模板
            ProposalTemplate(
                category=ProposalCategory.PROCEDURE_OPTIMIZATION,
                priority=ProposalPriority.MEDIUM,
                target_pattern="procedure.*",
                rationale_template="检测到流程 {target} 效率低下，建议优化步骤",
                expected_gain_range=(0.15, 0.4),
                risk_level=RiskLevel.LOW,
                required_tests=["流程验证", "性能对比"]
            ),
            
            # 记忆巩固模板
            ProposalTemplate(
                category=ProposalCategory.MEMORY_CONSOLIDATION,
                priority=ProposalPriority.LOW,
                target_pattern="memory.*",
                rationale_template="检测到记忆衰减，建议巩固 {target}",
                expected_gain_range=(0.05, 0.15),
                risk_level=RiskLevel.LOW,
                required_tests=["记忆检索测试"]
            ),
            
            # 资源分配模板
            ProposalTemplate(
                category=ProposalCategory.RESOURCE_ALLOCATION,
                priority=ProposalPriority.HIGH,
                target_pattern="resource.*",
                rationale_template="检测到资源分配不均衡，建议调整 {target}",
                expected_gain_range=(0.2, 0.4),
                risk_level=RiskLevel.MEDIUM,
                required_tests=["资源利用率测试", "稳定性测试"]
            ),
            
            # 情绪调节模板
            ProposalTemplate(
                category=ProposalCategory.EMOTION_REGULATION,
                priority=ProposalPriority.MEDIUM,
                target_pattern="emotion.*",
                rationale_template="检测到情绪状态不稳定，建议调节 {target}",
                expected_gain_range=(0.1, 0.25),
                risk_level=RiskLevel.LOW,
                required_tests=["情绪稳定性测试"]
            ),
        ]
    
    # ──────────────────────────────────────────────────────────────
    # 主生成流程
    # ──────────────────────────────────────────────────────────────
    
    def generate_proposals(self, force: bool = False) -> List[EvolutionProposal]:
        """
        生成所有可能的优化提案
        
        参数:
            force: 是否强制执行（即使没有检测到明显的优化机会）
        
        返回:
            EvolutionProposal 列表
        """
        proposals = []
        
        # 1. 检测优化机会
        opportunities = self._detect_opportunities(force=force)
        
        # 2. 为每个机会生成提案
        for opportunity in opportunities:
            proposal = self._opportunity_to_proposal(opportunity)
            if proposal:
                proposals.append(proposal)
        
        # 3. 对提案排序
        proposals = self._rank_proposals(proposals)
        
        # 4. 记录生成历史
        for proposal in proposals:
            self._record_generation(proposal)
        
        logger.info(f"生成了 {len(proposals)} 个提案")
        return proposals
    
    def _detect_opportunities(self, force: bool = False) -> List[OptimizationOpportunity]:
        """检测系统中的优化机会"""
        opportunities = []
        
        # 从认知引擎获取状态
        if self.cognitive_engine:
            # 检测需求驱动的机会
            needs_opportunities = self._detect_need_driven_opportunities()
            opportunities.extend(needs_opportunities)
            
            # 检测情绪相关机会
            emotion_opportunities = self._detect_emotion_opportunities()
            opportunities.extend(emotion_opportunities)
            
            # 检测记忆相关机会
            memory_opportunities = self._detect_memory_opportunities()
            opportunities.extend(memory_opportunities)
        
        # 从历史数据检测模式
        historical_opportunities = self._detect_historical_patterns()
        opportunities.extend(historical_opportunities)
        
        # 如果强制生成且没有机会，生成默认提案
        if force and not opportunities:
            opportunities.append(self._create_default_opportunity())
        
        return opportunities
    
    def _detect_need_driven_opportunities(self) -> List[OptimizationOpportunity]:
        """检测需求驱动的优化机会"""
        opportunities = []
        drive_vector = self.cognitive_engine.need_system.get_drive_vector()
        
        for need_name, drive in drive_vector.items():
            # 如果需求驱动超过阈值，生成学习/优化提案
            if drive > 0.7:
                # 检查是否已有相关技能
                related_skills = self._find_related_skills(need_name)
                
                if not related_skills:
                    # 需要学习新技能
                    opportunities.append(OptimizationOpportunity(
                        category=ProposalCategory.SKILL_LEARNING,
                        target=f"skill.{need_name}",
                        current_value=0.0,
                        proposed_value=1.0,
                        rationale=f"需求 {need_name} 驱动强度为 {drive:.2f}，但缺乏相关技能",
                        expected_gain=0.3,
                        confidence=0.8,
                        supporting_evidence=[f"需求驱动: {drive:.2f}"]
                    ))
        
        return opportunities
    
    def _detect_emotion_opportunities(self) -> List[OptimizationOpportunity]:
        """检测情绪相关的优化机会"""
        opportunities = []
        emotion_state = self.cognitive_engine.emotion_system.state
        
        # 检查情绪稳定性
        if emotion_state.valence < -0.3:
            opportunities.append(OptimizationOpportunity(
                category=ProposalCategory.EMOTION_REGULATION,
                target="emotion.negative",
                current_value=emotion_state.valence,
                proposed_value=0.0,
                rationale=f"检测到负情绪状态 ({emotion_state.valence:.2f})，建议进行情绪调节",
                expected_gain=0.2,
                confidence=0.75
            ))
        
        # 检查唤醒度是否过高
        if emotion_state.arousal > 0.8:
            opportunities.append(OptimizationOpportunity(
                category=ProposalCategory.EMOTION_REGULATION,
                target="emotion.arousal",
                current_value=emotion_state.arousal,
                proposed_value=0.5,
                rationale=f"检测到唤醒度过高 ({emotion_state.arousal:.2f})，建议降低活动强度",
                expected_gain=0.15,
                confidence=0.7
            ))
        
        return opportunities
    
    def _detect_memory_opportunities(self) -> List[OptimizationOpportunity]:
        """检测记忆相关的优化机会"""
        opportunities = []
        
        if self.memory:
            summary = self.memory.summarize()
            total_memories = summary.get("total", 0)
            
            # 如果记忆过少，建议积累更多经验
            if total_memories < 10:
                opportunities.append(OptimizationOpportunity(
                    category=ProposalCategory.MEMORY_CONSOLIDATION,
                    target="memory.accumulation",
                    current_value=total_memories,
                    proposed_value=50,
                    rationale=f"当前记忆数量 ({total_memories}) 不足，建议积累更多经验",
                    expected_gain=0.1,
                    confidence=0.6
                ))
        
        return opportunities
    
    def _detect_historical_patterns(self) -> List[OptimizationOpportunity]:
        """从历史数据检测模式"""
        opportunities = []
        
        if self.memory:
            # 检索失败经验
            failures = self.memory.search_by_tags(["failure"], limit=10)
            
            # 如果失败率过高，建议分析和改进
            if len(failures) > 5:
                opportunities.append(OptimizationOpportunity(
                    category=ProposalCategory.PROCEDURE_OPTIMIZATION,
                    target="procedure.error_prone",
                    current_value=len(failures),
                    proposed_value=2,
                    rationale=f"检测到较多失败经验 ({len(failures)}次)，建议分析并优化失败流程",
                    expected_gain=0.3,
                    confidence=0.7
                ))
            
            # 检测重复成功模式
            successes = self.memory.search_by_tags(["success"], limit=10)
            if len(successes) > 5:
                # 寻找可以固化为程序记忆的模式
                opportunities.append(OptimizationOpportunity(
                    category=ProposalCategory.PROCEDURE_OPTIMIZATION,
                    target="procedure.standardize",
                    current_value=0,
                    proposed_value=1,
                    rationale=f"检测到多次成功经验 ({len(successes)}次)，建议将成功流程标准化",
                    expected_gain=0.25,
                    confidence=0.8
                ))
        
        return opportunities
    
    def _create_default_opportunity(self) -> OptimizationOpportunity:
        """创建默认的优化机会（当没有检测到其他机会时）"""
        return OptimizationOpportunity(
            category=ProposalCategory.CONFIG_OPTIMIZATION,
            target="config.default_optimization",
            current_value="current",
            proposed_value="optimized",
            rationale="系统运行正常，但可以进行常规优化",
            expected_gain=0.1,
            confidence=0.5
        )
    
    def _find_related_skills(self, need_name: str) -> List[str]:
        """查找与需求相关的技能"""
        if not self.memory:
            return []
        
        skills = self.memory.recall(memory_type=MemoryType.SKILL, limit=5)
        related = []
        
        for skill in skills:
            if need_name.lower() in skill.title.lower() or \
               need_name.lower() in ' '.join(skill.tags).lower():
                related.append(skill.title)
        
        return related
    
    # ──────────────────────────────────────────────────────────────
    # 提案转换与生成
    # ──────────────────────────────────────────────────────────────
    
    def _opportunity_to_proposal(self, opportunity: OptimizationOpportunity) -> Optional[EvolutionProposal]:
        """将优化机会转换为正式提案"""
        # 查找匹配的模板
        template = self._find_matching_template(opportunity)
        
        if not template:
            template = self._proposal_templates[0]  # 使用默认模板
        
        # 创建提案
        proposal = ProposalFactory.create(
            target=opportunity.target,
            current=opportunity.current_value,
            proposed=opportunity.proposed_value,
            rationale=opportunity.rationale,
            gain=opportunity.expected_gain,
            risk=template.risk_level.value,
            constraints=self._get_constraints(opportunity)
        )
        
        # 设置额外属性
        proposal.metadata.update({
            "category": opportunity.category.value,
            "priority": template.priority.value,
            "confidence": opportunity.confidence,
            "supporting_evidence": opportunity.supporting_evidence,
            "estimated_effort": template.estimated_effort,
            "required_tests": template.required_tests
        })
        
        return proposal
    
    def _find_matching_template(self, opportunity: OptimizationOpportunity) -> Optional[ProposalTemplate]:
        """查找匹配的提案模板"""
        for template in self._proposal_templates:
            if template.category == opportunity.category:
                return template
        return None
    
    def _get_constraints(self, opportunity: OptimizationOpportunity) -> Dict:
        """获取提案约束"""
        if opportunity.category == ProposalCategory.SKILL_LEARNING:
            return {"min": 0.0, "max": 1.0, "type": "float", "proficiency_target": 0.7}
        elif opportunity.category == ProposalCategory.RESOURCE_ALLOCATION:
            return {"min": 0.1, "max": 0.9, "type": "float"}
        else:
            return {"min": 0.0, "max": 1.0, "type": "float"}
    
    def _rank_proposals(self, proposals: List[EvolutionProposal]) -> List[EvolutionProposal]:
        """
        对提案进行排序
        
        排序权重：
        - 优先级: 40%
        - 预期收益: 30%
        - 置信度: 20%
        - 风险等级: 10%
        """
        priority_weights = {
            ProposalPriority.CRITICAL.value: 1.0,
            ProposalPriority.HIGH.value: 0.8,
            ProposalPriority.MEDIUM.value: 0.6,
            ProposalPriority.LOW.value: 0.3
        }
        
        risk_weights = {
            RiskLevel.LOW.value: 1.0,
            RiskLevel.MEDIUM.value: 0.7,
            RiskLevel.HIGH.value: 0.4,
            RiskLevel.CRITICAL.value: 0.1
        }
        
        def score(proposal: EvolutionProposal) -> float:
            priority = priority_weights.get(proposal.metadata.get("priority"), 0.5)
            gain = proposal.expected_gain
            confidence = proposal.metadata.get("confidence", 0.5)
            risk = risk_weights.get(proposal.risk_level.value, 0.5)
            
            return (
                0.4 * priority +
                0.3 * gain +
                0.2 * confidence +
                0.1 * risk
            )
        
        return sorted(proposals, key=score, reverse=True)
    
    def _record_generation(self, proposal: EvolutionProposal):
        """记录提案生成历史"""
        record = GeneratedProposalRecord(
            proposal_id=proposal.id,
            category=proposal.metadata.get("category"),
            generated_at=time.time(),
            status=proposal.status.value
        )
        
        self._generation_history.append(record)
        if len(self._generation_history) > self._max_history:
            self._generation_history = self._generation_history[-self._max_history:]
        
        self._total_proposals_generated += 1
    
    # ──────────────────────────────────────────────────────────────
    # 提案评估与验证
    # ──────────────────────────────────────────────────────────────
    
    def evaluate_proposal(self, proposal: EvolutionProposal) -> ProposalEvaluation:
        """评估提案的质量和可行性"""
        # 检查是否与现有提案冲突
        conflicts = self._check_conflicts(proposal)
        
        # 评估风险
        risk_score = self._assess_risk(proposal)
        
        # 评估收益
        benefit_score = self._assess_benefit(proposal)
        
        # 综合评分
        overall_score = (0.6 * benefit_score + 0.4 * (1 - risk_score)) * (1 - len(conflicts) * 0.1)
        
        return ProposalEvaluation(
            proposal_id=proposal.id,
            overall_score=overall_score,
            risk_score=risk_score,
            benefit_score=benefit_score,
            conflicts=conflicts,
            recommended_action=self._get_recommended_action(overall_score, conflicts)
        )
    
    def _check_conflicts(self, proposal: EvolutionProposal) -> List[str]:
        """检查提案是否与其他提案冲突"""
        conflicts = []
        
        # 检查是否已有针对同一目标的提案
        for record in self._generation_history[-20:]:
            if record.status == "approved" or record.status == "testing":
                # 检查目标是否相同或相关
                if record.category == proposal.metadata.get("category"):
                    conflicts.append(f"已有同类提案正在处理: {record.proposal_id}")
        
        return conflicts
    
    def _assess_risk(self, proposal: EvolutionProposal) -> float:
        """评估提案风险（0-1，越高风险越大）"""
        risk_mapping = {
            RiskLevel.LOW.value: 0.1,
            RiskLevel.MEDIUM.value: 0.3,
            RiskLevel.HIGH.value: 0.6,
            RiskLevel.CRITICAL.value: 0.9
        }
        
        base_risk = risk_mapping.get(proposal.risk_level.value, 0.3)
        
        # 根据置信度调整
        confidence = proposal.metadata.get("confidence", 0.5)
        risk_adjustment = (1 - confidence) * 0.3
        
        return min(1.0, base_risk + risk_adjustment)
    
    def _assess_benefit(self, proposal: EvolutionProposal) -> float:
        """评估提案收益（0-1，越高收益越大）"""
        gain = proposal.expected_gain
        
        # 根据类别调整
        category_multiplier = {
            ProposalCategory.SKILL_LEARNING.value: 1.2,
            ProposalCategory.PROCEDURE_OPTIMIZATION.value: 1.1,
            ProposalCategory.CONFIG_OPTIMIZATION.value: 1.0,
            ProposalCategory.RESOURCE_ALLOCATION.value: 0.9,
            ProposalCategory.MEMORY_CONSOLIDATION.value: 0.8,
            ProposalCategory.EMOTION_REGULATION.value: 0.7,
        }
        
        multiplier = category_multiplier.get(proposal.metadata.get("category"), 1.0)
        
        return min(1.0, gain * multiplier)
    
    def _get_recommended_action(self, score: float, conflicts: List[str]) -> str:
        """根据评估结果获取推荐动作"""
        if conflicts:
            return "resolve_conflicts"
        elif score > 0.7:
            return "approve"
        elif score > 0.4:
            return "test"
        else:
            return "reject"
    
    # ──────────────────────────────────────────────────────────────
    # 统计与报告
    # ──────────────────────────────────────────────────────────────
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取提案生成统计"""
        return {
            "total_proposals_generated": self._total_proposals_generated,
            "total_proposals_approved": self._total_proposals_approved,
            "total_proposals_deployed": self._total_proposals_deployed,
            "approval_rate": self._total_proposals_approved / max(1, self._total_proposals_generated),
            "deployment_rate": self._total_proposals_deployed / max(1, self._total_proposals_approved),
            "active_proposals": len([r for r in self._generation_history if r.status in ["proposed", "approved", "testing"]])
        }
    
    def update_proposal_status(self, proposal_id: str, new_status: str):
        """更新提案状态"""
        for record in self._generation_history:
            if record.proposal_id == proposal_id:
                record.status = new_status
                break
        
        if new_status == ProposalStatus.APPROVED.value:
            self._total_proposals_approved += 1
        elif new_status == ProposalStatus.DEPLOYED.value:
            self._total_proposals_deployed += 1


# ──────────────────────────────────────────────────────────────────────
# 辅助类
# ──────────────────────────────────────────────────────────────────────

@dataclass
class GeneratedProposalRecord:
    """提案生成记录"""
    proposal_id: str
    category: str
    generated_at: float
    status: str


@dataclass
class ProposalEvaluation:
    """提案评估结果"""
    proposal_id: str
    overall_score: float
    risk_score: float
    benefit_score: float
    conflicts: List[str]
    recommended_action: str  # approve, test, reject, resolve_conflicts


# ──────────────────────────────────────────────────────────────────────
# 与认知引擎的集成
# ──────────────────────────────────────────────────────────────────────

class CognitiveProposalGenerator(AutoProposalGenerator):
    """
    与认知引擎深度集成的提案生成器
    
    自动从认知引擎获取状态信息，生成与当前认知状态匹配的提案
    """
    
    def __init__(self, cognitive_engine: IntegratedCognitiveEngine):
        super().__init__(cognitive_engine)
        
        # 注册到认知引擎的反思系统
        self._register_with_cognitive_engine()
    
    def _register_with_cognitive_engine(self):
        """注册到认知引擎"""
        # 将提案生成作为反思的一部分
        logger.info("提案生成器已注册到认知引擎")
    
    def on_cognitive_tick(self):
        """在认知引擎 tick 时被调用"""
        # 每N次tick生成一次提案
        if self.cognitive_engine and self.cognitive_engine._tick_count % 50 == 0:
            proposals = self.generate_proposals()
            
            # 如果有高优先级提案，通知认知引擎
            high_priority_proposals = [
                p for p in proposals 
                if p.metadata.get("priority") == ProposalPriority.HIGH.value
                or p.metadata.get("priority") == ProposalPriority.CRITICAL.value
            ]
            
            if high_priority_proposals:
                self._notify_cognitive_engine(high_priority_proposals)
    
    def _notify_cognitive_engine(self, proposals: List[EvolutionProposal]):
        """通知认知引擎有新提案"""
        if self.cognitive_engine:
            # 将提案作为经验事件记录
            for proposal in proposals[:3]:  # 最多记录3个
                event_content = f"生成优化提案: {proposal.target} - {proposal.rationale[:50]}"
                self.cognitive_engine.record_experience(
                    ExperienceEvent(
                        event_type="observation",
                        content=event_content,
                        emotional_valence=0.2,  # 提案生成带来轻微积极情绪
                        importance=0.5,
                        tags=["proposal", proposal.metadata.get("category")],
                        context={"proposal_id": proposal.id, "priority": proposal.metadata.get("priority")}
                    )
                )
    
    def generate_proposals_for_current_state(self) -> List[EvolutionProposal]:
        """根据当前认知状态生成提案"""
        if not self.cognitive_engine:
            return []

        # 获取当前状态
        state = self.cognitive_engine.get_state()

        # 如果情绪状态不佳，或存在严重匮乏的需求，优先生成情绪调节提案
        # 单个需求的严重匮乏同样会引发负面情绪，即使整体平均效价未跌破阈值
        has_critical_need = any(level < 0.2 for level in state.needs.values())
        if state.emotions.valence < -0.3 or has_critical_need:
            return self._generate_emotion_focused_proposals(state)

        # 如果有强烈的需求驱动，优先生成满足需求的提案
        if state.drive_strength > 0.7:
            return self._generate_need_focused_proposals(state)

        # 默认：生成全面的提案
        return self.generate_proposals()
    
    def _generate_emotion_focused_proposals(self, state) -> List[EvolutionProposal]:
        """生成情绪调节聚焦的提案"""
        opportunities = []
        
        # 生成情绪调节提案
        opportunities.append(OptimizationOpportunity(
            category=ProposalCategory.EMOTION_REGULATION,
            target="emotion.stabilize",
            current_value=state.emotions.valence,
            proposed_value=0.0,
            rationale=f"情绪状态不稳定 ({state.emotions.valence:.2f})，需要调节",
            expected_gain=0.25,
            confidence=0.8
        ))
        
        # 如果有相关的成功记忆，建议参考
        calm_memories = self.memory.recall_by_emotion(0.0, tolerance=0.2, limit=3) if self.memory else []
        if calm_memories:
            opportunities.append(OptimizationOpportunity(
                category=ProposalCategory.MEMORY_CONSOLIDATION,
                target="memory.calm_experiences",
                current_value=len(calm_memories),
                proposed_value=len(calm_memories),
                rationale=f"有 {len(calm_memories)} 段平静经历可以参考",
                expected_gain=0.1,
                confidence=0.7
            ))
        
        return [self._opportunity_to_proposal(o) for o in opportunities]
    
    def _generate_need_focused_proposals(self, state) -> List[EvolutionProposal]:
        """生成需求驱动的提案"""
        opportunities = []
        
        # 查找主导需求相关的提案
        if state.dominant_need:
            opportunities.append(OptimizationOpportunity(
                category=ProposalCategory.SKILL_LEARNING,
                target=f"skill.{state.dominant_need}",
                current_value=state.needs.get(state.dominant_need, 0.5),
                proposed_value=0.9,
                rationale=f"主导需求 {state.dominant_need} 强度为 {state.drive_strength:.2f}，建议获取相关技能",
                expected_gain=0.35,
                confidence=0.85
            ))
        
        return [self._opportunity_to_proposal(o) for o in opportunities]
