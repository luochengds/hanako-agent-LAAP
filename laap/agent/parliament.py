"""
LAAP — 议会系统 (Parliament System)

AGI 核心模式：内部多视角 deliberation (内部对话)

概念源自 Minsky 的"心灵社会"(Society of Mind)：
Agent 内部有多个"议员"(perspectives)，每个代表不同的
认知视角、价值观、专业知识。重大决策前，议会进行辩论，
最终由"议长"综合各方意见做出明智决策。

议员角色示例：
  - 理性分析员 (Rational Analyst): 逻辑和数据分析
  - 创意专家 (Creative Expert): 创新和发散思维
  - 安全卫士 (Safety Guardian): 风险和伦理审查
  - 实用主义者 (Pragmatist): 可执行性和效率
  - 经验顾问 (Experience Advisor): 基于过往经验
  - 元认知观察员 (Meta Observer): 过程监控
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple
from enum import Enum
import time, logging, json, uuid

logger = logging.getLogger("laap.agent.parliament")


class MemberRole(Enum):
    """议会成员角色"""
    RATIONAL = "rational"           # 理性分析员
    CREATIVE = "creative"           # 创意专家
    SAFETY = "safety"              # 安全卫士
    PRAGMATIST = "pragmatist"      # 实用主义者
    EXPERIENCE = "experience"      # 经验顾问
    META = "meta"                  # 元认知观察员
    EMPATH = "empath"              # 共情者（用户视角）
    SKEPTIC = "skeptic"            # 怀疑论者（挑战假设）
    CUSTOM = "custom"              # 自定义


@dataclass
class Opinion:
    """
    议员意见 — 一次议会对某个议题的表态
    
    包含：立场、论证、置信度、风险识别、可替代方案
    """
    member_id: str = ""
    member_role: str = ""
    stance: str = ""                    # 支持/反对/中立/条件支持
    argument: str = ""                  # 核心论证
    confidence: float = 0.5             # 置信度 0-1
    risks: List[str] = field(default_factory=list)     # 识别的风险
    alternatives: List[str] = field(default_factory=list)  # 替代方案
    conditions: List[str] = field(default_factory=list)   # 支持的条件
    weight: float = 1.0                 # 权重（基于历史准确度）
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "member": self.member_id,
            "role": self.member_role,
            "stance": self.stance[:50],
            "argument": self.argument[:100],
            "confidence": round(self.confidence, 2),
            "risks": self.risks[:3],
            "weight": round(self.weight, 2),
        }


@dataclass
class Deliberation:
    """
    议会审议记录
    
    包含：议题、各议员意见、议长综合、最终决议
    """
    id: str = ""
    topic: str = ""
    context: str = ""
    opinions: List[Opinion] = field(default_factory=list)
    consensus: Optional[str] = None      # 议长综合意见
    final_decision: str = ""             # 最终决议
    decision_confidence: float = 0.5     # 决议置信度
    dissenting_views: List[str] = field(default_factory=list)
    duration_ms: float = 0.0
    timestamp: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id[:8],
            "topic": self.topic[:60],
            "members": len(self.opinions),
            "consensus": (self.consensus or "")[:100] if self.consensus else None,
            "confidence": round(self.decision_confidence, 2),
            "dissenting": len(self.dissenting_views),
            "duration_ms": round(self.duration_ms, 1),
        }


@dataclass
class MemberProfile:
    """
    议员档案 — 每个议员的身份、专业知识、历史表现
    
    类比人的"内部声音"：每个议员有自己的
    知识领域、价值观、思维偏好。
    """
    id: str = ""
    name: str = ""
    role: MemberRole = MemberRole.CUSTOM
    expertise: List[str] = field(default_factory=list)      # 专长领域
    personality: str = ""              # 性格描述
    thinking_style: str = ""           # 思考风格
    decision_weight: float = 1.0       # 决策权重（动态调整）
    historical_accuracy: float = 0.7   # 历史准确率
    participation_count: int = 0
    last_active: float = 0.0

    def to_dict(self) -> dict:
        return {
            "id": self.id[:8],
            "name": self.name,
            "role": self.role.value,
            "expertise": self.expertise[:3],
            "accuracy": round(self.historical_accuracy, 2),
            "weight": round(self.decision_weight, 2),
            "participation": self.participation_count,
        }


# ════════════════════════════════════════════════════════════
# 议程 (Agenda)
# ════════════════════════════════════════════════════════════

@dataclass
class AgendaItem:
    """议程项 — 议会要讨论的事项"""
    id: str = ""
    title: str = ""
    description: str = ""
    priority: int = 5                  # 1-10 优先级
    urgency: float = 0.5               # 紧迫程度
    required_roles: List[str] = field(default_factory=list)  # 需要哪些角色参与
    deadline: float = 0.0
    status: str = "pending"            # pending, deliberating, decided, deferred


class Parliament:
    """
    议会系统 — Agent 内部的多视角审议机制
    
    核心流程：
      1. 提出议题 (submit_agenda)
      2. 各议员发表意见 (deliberate)
      3. 议长综合 (synthesize)
      4. 做出决议 (decide)
      5. 记录学习 (learn)
    
    关键特性：
      - 议员角色可自定义、可扩展
      - 基于历史准确率动态调整权重
      - 支持快速模式（关键议员）和完整模式（全体议员）
      - 审议过程可追踪、可审计
      - 支持辩论过程可视化（通过 ParliamentWithVisualization）
    """

    def __init__(self, agent_id: str = ""):
        self.agent_id = agent_id
        self.members: Dict[str, MemberProfile] = {}
        self.deliberations: List[Deliberation] = []
        self._max_deliberations = 50
        self._init_default_members()
        
        # 议程队列
        self.agenda: List[AgendaItem] = []
        self._max_agenda = 20
        
        # 统计
        self._total_deliberations = 0
        self._consensus_rate = 0.0
        self._start_time = time.time()
        
        logger.info(f"议会系统初始化完成, {len(self.members)} 名议员 [{agent_id[:8]}]")

    def _init_default_members(self):
        """初始化默认议员角色"""
        default_members = [
            MemberProfile(
                name="逻辑",
                role=MemberRole.RATIONAL,
                expertise=["analysis", "logic", "data", "推理", "分析"],
                personality="严谨、逻辑导向，追求最优解",
                thinking_style="逐步推理，依赖证据和数据",
            ),
            MemberProfile(
                name="想象",
                role=MemberRole.CREATIVE,
                expertise=["innovation", "design", "creative", "创意", "设计"],
                personality="开放、发散，追求新可能性",
                thinking_style="联想思维，跳出框架",
            ),
            MemberProfile(
                name="守护",
                role=MemberRole.SAFETY,
                expertise=["security", "ethics", "risk", "安全", "伦理"],
                personality="谨慎、保守，优先考虑风险",
                thinking_style="风险评估，逆向思维",
            ),
            MemberProfile(
                name="实干",
                role=MemberRole.PRAGMATIST,
                expertise=["execution", "efficiency", "implementation", "执行", "效率"],
                personality="务实、高效，追求可执行方案",
                thinking_style="结果导向，关注可行性",
            ),
            MemberProfile(
                name="经验",
                role=MemberRole.EXPERIENCE,
                expertise=["memory", "pattern", "history", "经验", "模式"],
                personality="沉稳、智慧，从过去吸取教训",
                thinking_style="类比推理，模式匹配",
            ),
            MemberProfile(
                name="共情",
                role=MemberRole.EMPATH,
                expertise=["user_needs", "communication", "emotion", "用户", "沟通"],
                personality="温暖、敏感，从用户角度思考",
                thinking_style="换位思考，情感理解",
            ),
            MemberProfile(
                name="质疑",
                role=MemberRole.SKEPTIC,
                expertise=["critique", "validation", "challenge", "批判", "验证"],
                personality="批判性、执着，挑战一切假设",
                thinking_style="反证思维，寻找漏洞",
            ),
            MemberProfile(
                name="元觉",
                role=MemberRole.META,
                expertise=["process", "reflection", "improvement", "元认知", "改进"],
                personality="客观、抽离，观察思考过程本身",
                thinking_style="元认知监控，过程优化",
            ),
        ]
        
        for member in default_members:
            member.id = f"member_{member.name}"
            self.register_member(member)

    def register_member(self, profile: MemberProfile):
        """注册新议员"""
        if profile.id in self.members:
            logger.warning(f"议员 {profile.id} 已存在，将被覆盖")
        profile.last_active = time.time()
        self.members[profile.id] = profile
        logger.info(
            f"注册议员: {profile.name} ({profile.role.value}) "
            f"专长: {profile.expertise[:3]}"
        )

    def remove_member(self, member_id: str):
        """移除议员"""
        if member_id in self.members:
            name = self.members[member_id].name
            del self.members[member_id]
            logger.info(f"移除议员: {name}")

    # ═══════════════════════════════════════════════════
    # 议程管理
    # ═══════════════════════════════════════════════════

    def submit_agenda(self, title: str, description: str,
                      priority: int = 5, urgency: float = 0.5,
                      required_roles: List[str] = None) -> str:
        """提交一个议题到议程队列"""
        item = AgendaItem(
            id=str(uuid.uuid4())[:8],
            title=title,
            description=description,
            priority=max(1, min(10, priority)),
            urgency=max(0.0, min(1.0, urgency)),
            required_roles=required_roles or [],
            status="pending",
        )
        self.agenda.append(item)
        
        # 按优先级排序
        self.agenda.sort(key=lambda x: (x.priority, x.urgency), reverse=True)
        
        # 限制队列长度
        if len(self.agenda) > self._max_agenda:
            self.agenda = self.agenda[:self._max_agenda]
        
        logger.debug(f"提交议题: {title[:40]} (优先级={priority})")
        return item.id

    def get_next_agenda(self) -> Optional[AgendaItem]:
        """获取下一个待处理的议程项"""
        pending = [a for a in self.agenda if a.status == "pending"]
        if pending:
            return pending[0]
        return None

    # ═══════════════════════════════════════════════════
    # 审议核心流程
    # ═══════════════════════════════════════════════════

    def deliberate(self, topic: str, context: str = "",
                   roles: List[str] = None,
                   fast_mode: bool = False) -> Deliberation:
        """
        对某个议题进行议会审议

        Args:
            topic: 审议议题
            context: 背景信息
            roles: 需要参与的议员角色（None=全体）
            fast_mode: 快速模式（只邀请关键议员）

        Returns:
            Deliberation: 审议记录（含各议员意见和最终决议）
        """
        deliberation = Deliberation(
            id=str(uuid.uuid4())[:12],
            topic=topic,
            context=context,
            timestamp=time.time(),
        )
        t0 = time.time()
        
        # 1. 选择参与议员
        participants = self._select_participants(topic, roles, fast_mode)
        
        if not participants:
            logger.warning(f"没有可参与的议员: topic={topic[:40]}")
            deliberation.final_decision = "无可用议员"
            deliberation.decision_confidence = 0.0
            self._record_deliberation(deliberation)
            return deliberation
        
        # 2. 每个议员发表意见
        for member_id in participants:
            member = self.members.get(member_id)
            if not member:
                continue
            
            opinion = self._generate_opinion(member, topic, context, deliberation)
            deliberation.opinions.append(opinion)
            
            logger.debug(
                f"  议员 {member.name}: {opinion.stance[:30]} "
                f"(conf={opinion.confidence:.2f})"
            )
        
        # 3. 议长综合意见
        deliberation.consensus = self._synthesize(deliberation.opinions, topic)
        
        # 4. 做出决议
        deliberation.final_decision, deliberation.decision_confidence = \
            self._decide(deliberation)
        
        # 5. 记录反对意见
        deliberation.dissenting_views = [
            o.argument for o in deliberation.opinions
            if self._is_dissenting(o, deliberation.final_decision)
        ]
        
        deliberation.duration_ms = (time.time() - t0) * 1000
        self._record_deliberation(deliberation)
        
        logger.info(
            f"议会审议完成: topic={topic[:30]} "
            f"members={len(participants)} "
            f"decision={deliberation.final_decision[:30]} "
            f"conf={deliberation.decision_confidence:.2f} "
            f"({deliberation.duration_ms:.0f}ms)"
        )
        return deliberation

    def quick_deliberate(self, topic: str) -> str:
        """
        快速审议 — 只返回决议文本，适合简单决策
        
        Returns:
            最终决议的简要文本
        """
        deliberation = self.deliberate(topic, fast_mode=True)
        return deliberation.final_decision

    def full_deliberate(self, topic: str, context: str = "") -> Deliberation:
        """
        完整审议 — 所有角色参与，返回完整记录
        """
        return self.deliberate(topic, context=context, fast_mode=False)

    # ═══════════════════════════════════════════════════
    # 内部方法
    # ═══════════════════════════════════════════════════

    def _select_participants(self, topic: str, 
                              roles: List[str] = None,
                              fast_mode: bool = False) -> List[str]:
        """根据议题选择参与议员"""
        if roles:
            # 按指定角色选择
            return [
                mid for mid, m in self.members.items()
                if m.role.value in roles
            ]
        
        if fast_mode:
            # 快速模式：只选3个关键角色
            key_roles = {"rational", "pragmatist", "experience"}
            return [
                mid for mid, m in self.members.items()
                if m.role.value in key_roles
            ]
        
        # 完整模式：所有议员
        # 但排除最近参与度过高的议员（避免疲劳）
        participants = []
        for mid, member in self.members.items():
            if member.participation_count > 0:
                # 检查是否过度活跃
                recent_active = time.time() - member.last_active
                if recent_active < 10 and member.participation_count > 5:
                    continue
            participants.append(mid)
        
        return participants

    def _generate_opinion(self, member: MemberProfile, topic: str,
                           context: str, deliberation: Deliberation) -> Opinion:
        """生成议员的意见（基于角色特征和主题）"""
        member.participation_count += 1
        member.last_active = time.time()
        
        # 根据角色类型生成风格化的意见
        role_stances = {
            MemberRole.RATIONAL: {
                "default_stance": self._rational_stance(topic),
                "style": "基于数据和分析",
            },
            MemberRole.CREATIVE: {
                "default_stance": self._creative_stance(topic),
                "style": "探索新可能性",
            },
            MemberRole.SAFETY: {
                "default_stance": self._safety_stance(topic),
                "style": "识别风险",
            },
            MemberRole.PRAGMATIST: {
                "default_stance": self._pragmatist_stance(topic),
                "style": "聚焦可执行性",
            },
            MemberRole.EXPERIENCE: {
                "default_stance": self._experience_stance(topic),
                "style": "借鉴过往经验",
            },
            MemberRole.EMPATH: {
                "default_stance": self._empath_stance(topic),
                "style": "从用户视角出发",
            },
            MemberRole.SKEPTIC: {
                "default_stance": self._skeptic_stance(topic),
                "style": "挑战假设",
            },
            MemberRole.META: {
                "default_stance": self._meta_stance(topic, deliberation),
                "style": "过程监控",
            },
        }
        
        stance_info = role_stances.get(
            member.role, 
            {"default_stance": ("中立", "待评估", ["暂无"], []), "style": ""}
        )
        stance, argument, risks, alternatives = stance_info["default_stance"]
        
        # 置信度受历史准确率影响
        confidence = 0.5 + 0.3 * member.historical_accuracy
        
        return Opinion(
            member_id=member.id,
            member_role=member.role.value,
            stance=stance,
            argument=argument,
            confidence=confidence,
            risks=risks,
            alternatives=alternatives,
            weight=member.decision_weight + member.historical_accuracy * 0.5,
        )

    def _rational_stance(self, topic: str) -> Tuple[str, str, List[str], List[str]]:
        """理性分析员的立场模板"""
        # 关键词检测
        if any(w in topic.lower() for w in ["分析", "analyze", "数据", "data"]):
            return ("支持", "推荐使用系统化分析方法，有足够的数据支持决策",
                    ["数据质量不确定性"], ["收集更多数据后再决策"])
        elif len(topic) > 100:
            return ("条件支持", "需要先分解复杂问题为可分析的子问题",
                    ["复杂度过高可能导致分析偏差"], 
                    ["先做问题分解，逐步分析"])
        else:
            return ("中立", "需要在更多信息基础上进行分析",
                    ["信息不完备可能导致错误推断"],
                    ["收集更多相关信息"])

    def _creative_stance(self, topic: str) -> Tuple[str, str, List[str], List[str]]:
        """创意专家的立场模板"""
        return ("探索", "这个问题有多个创新解决方案值得尝试",
                ["过度追求创新可能忽视实用性"],
                ["先做可行性验证再全面实施"])

    def _safety_stance(self, topic: str) -> Tuple[str, str, List[str], List[str]]:
        """安全卫士的立场模板"""
        return ("谨慎", "需要评估潜在风险和安全影响",
                ["可能存在的安全风险", "未考虑的负面后果"],
                ["先做风险评估，设置安全边界"])

    def _pragmatist_stance(self, topic: str) -> Tuple[str, str, List[str], List[str]]:
        """实用主义者的立场模板"""
        if any(w in topic.lower() for w in ["复杂", "complex", "large"]):
            return ("条件支持", "可行但需要分阶段实施，控制复杂度",
                    ["实施周期可能过长"], ["先做最小可行版本"])
        return ("支持", "有明确的执行路径，资源投入合理",
                ["执行效率可以优化"], ["考虑并行执行或简化方案"])

    def _experience_stance(self, topic: str) -> Tuple[str, str, List[str], List[str]]:
        """经验顾问的立场模板"""
        return ("参考经验", "类似的模式在过往经验中曾出现过",
                ["简单套用经验可能忽略新环境差异"],
                ["结合当前具体情境调整历史方案"])

    def _empath_stance(self, topic: str) -> Tuple[str, str, List[str], List[str]]:
        """共情者的立场模板"""
        return ("用户优先", "从用户角度看这是一个有价值的方向",
                ["可能未充分考虑用户的多样需求"],
                ["增加用户视角验证环节"])

    def _skeptic_stance(self, topic: str) -> Tuple[str, str, List[str], List[str]]:
        """怀疑论者的立场模板"""
        return ("质疑", "需要检验假设的有效性和逻辑的完备性",
                ["可能存在未被发现的逻辑漏洞"],
                ["做更多假设检验和反向推理"])

    def _meta_stance(self, topic: str, 
                      deliberation: Deliberation) -> Tuple[str, str, List[str], List[str]]:
        """元认知观察员的立场模板"""
        return ("监控", "关注审议过程本身的质量和效率",
                ["审议可能受到认知偏差影响"],
                ["引入外部验证或增加反思环节"])

    def _synthesize(self, opinions: List[Opinion], topic: str) -> str:
        """议长综合各方意见"""
        if not opinions:
            return "无意见"
        
        # 按权重汇总立场
        stances = {}
        for o in opinions:
            s = o.stance[:10]
            stances[s] = stances.get(s, 0) + o.weight
        
        # 找出主流立场
        dominant_stance = max(stances, key=stances.get)
        
        # 识别共同点的风险
        common_risks = []
        risk_counts = {}
        for o in opinions:
            for r in o.risks:
                risk_counts[r] = risk_counts.get(r, 0) + 1
        common_risks = [r for r, c in risk_counts.items() 
                        if c >= len(opinions) * 0.5]
        
        # 整合意见
        parts = [
            f"议会讨论: {len(opinions)}位议员参与",
            f"主流立场: {dominant_stance}",
        ]
        if common_risks:
            parts.append(f"共同风险: {'; '.join(common_risks[:3])}")
        
        # 不同意见
        dissenting = [o for o in opinions 
                      if o.stance != dominant_stance and o.confidence > 0.6]
        if dissenting:
            parts.append(f"反对意见({len(dissenting)}): " +
                         "; ".join(o.argument[:30] for o in dissenting[:2]))
        
        return " | ".join(parts)

    def _decide(self, deliberation: Deliberation) -> Tuple[str, float]:
        """根据审议结果做出决议"""
        if not deliberation.opinions:
            return ("无法决策", 0.0)
        
        # 加权投票
        vote_score = 0.0
        total_weight = 0.0
        
        for o in deliberation.opinions:
            w = o.weight
            total_weight += w
            if "支持" in o.stance:
                vote_score += w
            elif "反对" in o.stance or "拒绝" in o.stance:
                vote_score -= w
            elif "条件" in o.stance:
                vote_score += w * 0.5
            # 中立 = 0
        
        if total_weight == 0:
            return ("无有效投票", 0.0)
        
        normalized = vote_score / total_weight  # -1 to 1
        confidence = abs(normalized)
        
        if normalized > 0.3:
            decision = "执行提案"
        elif normalized > -0.3:
            decision = "需要重新讨论"
        else:
            decision = "否决提案"
        
        return (decision, confidence)

    def _is_dissenting(self, opinion: Opinion, decision: str) -> bool:
        """判断某个意见是否与最终决议相悖"""
        if "执行" in decision and ("反对" in opinion.stance or "拒绝" in opinion.stance):
            return True
        if "否决" in decision and ("支持" in opinion.stance):
            return True
        return False

    def _record_deliberation(self, deliberation: Deliberation):
        """记录审议"""
        self.deliberations.append(deliberation)
        if len(self.deliberations) > self._max_deliberations:
            self.deliberations = self.deliberations[-self._max_deliberations:]
        
        self._total_deliberations += 1
        
        # 更新共识率
        if deliberation.opinions:
            support_count = sum(
                1 for o in deliberation.opinions 
                if "支持" in o.stance or "条件" in o.stance
            )
            self._consensus_rate = (
                self._consensus_rate * 0.95 + 
                (support_count / len(deliberation.opinions)) * 0.05
            )

    # ═══════════════════════════════════════════════════
    # 学习与适应
    # ═══════════════════════════════════════════════════

    def learn_from_outcome(self, deliberation_id: str, outcome_score: float):
        """
        根据实际结果更新各议员权重
        
        Args:
            deliberation_id: 审议ID
            outcome_score: 实际结果评分 (0-1)
        """
        deliberation = None
        for d in self.deliberations:
            if d.id == deliberation_id:
                deliberation = d
                break
        
        if not deliberation:
            logger.warning(f"未找到审议记录: {deliberation_id}")
            return
        
        for opinion in deliberation.opinions:
            member_id = opinion.member_id
            if member_id not in self.members:
                continue
            
            member = self.members[member_id]
            
            # 如果议员的立场与实际结果一致，提升权重
            agreement = self._compute_agreement(opinion, outcome_score)
            member.historical_accuracy = (
                member.historical_accuracy * 0.9 + agreement * 0.1
            )
            
            # 动态调整决策权重
            if agreement > 0.7:
                member.decision_weight = min(2.0, member.decision_weight * 1.05)
            elif agreement < 0.3:
                member.decision_weight = max(0.5, member.decision_weight * 0.95)
        
        logger.debug(
            f"议会学习: deliberation={deliberation_id[:8]} "
            f"outcome={outcome_score:.2f}"
        )

    def _compute_agreement(self, opinion: Opinion, outcome: float) -> float:
        """计算议员意见与实际结果的一致性"""
        # 支持 → 结果好 = 一致
        # 反对 → 结果差 = 一致
        if "支持" in opinion.stance:
            return outcome
        elif "反对" in opinion.stance or "否决" in opinion.stance:
            return 1.0 - outcome
        else:
            return 0.5  # 中立不计算

    # ═══════════════════════════════════════════════════
    # 查询与分析
    # ═══════════════════════════════════════════════════

    def get_member_stats(self) -> Dict[str, dict]:
        """获取所有议员统计"""
        return {
            mid: m.to_dict() 
            for mid, m in self.members.items()
        }

    def get_recent_decisions(self, n: int = 5) -> List[Dict]:
        """获取最近N次决议"""
        return [d.to_dict() for d in self.deliberations[-n:]]

    def introspect(self) -> str:
        """内省：返回议会状态描述"""
        parts = [
            "=== 议会系统状态 ===",
            f"议员数量: {len(self.members)}",
            f"总审议次数: {self._total_deliberations}",
            f"共识率: {self._consensus_rate:.0%}",
            "",
            "议员档案:",
        ]
        for mid, member in self.members.items():
            parts.append(
                f"  [{member.role.value[:4]}] {member.name}: "
                f"准确率={member.historical_accuracy:.0%} "
                f"权重={member.decision_weight:.1f} "
                f"参与={member.participation_count}"
            )
        
        pending = len([a for a in self.agenda if a.status == "pending"])
        if pending > 0:
            parts.extend([
                "",
                f"待处理议程: {pending} 项",
            ])
        
        return "\n".join(parts)

    def status(self) -> dict:
        return {
            "members": len(self.members),
            "total_deliberations": self._total_deliberations,
            "consensus_rate": round(self._consensus_rate, 3),
            "agenda_pending": len([a for a in self.agenda if a.status == "pending"]),
            "recent": [d.to_dict() for d in self.deliberations[-3:]],
        }

# 导入可视化扩展类
try:
    from .parliament_visualizer import ParliamentWithVisualization
    __all__ = ['Parliament', 'MemberRole', 'Opinion', 'Deliberation', 
               'MemberProfile', 'AgendaItem', 'ParliamentWithVisualization']
except ImportError:
    __all__ = ['Parliament', 'MemberRole', 'Opinion', 'Deliberation', 
               'MemberProfile', 'AgendaItem']
