"""
LAAP — Brain: Unified Human-Like Thinking Decision Layer (统一类人脑思维决策层)

设计理念：
  人脑不是多个独立模块的拼凑，而是**统一的认知系统**。
  Brain 层模拟人类大脑的五大核心功能区域协同工作：

  ┌─────────────────────────────────────────────────────┐
  │                  BRAIN CORTEX                       │
  ├─────────────────────────────────────────────────────┤
  │  前额叶 (PFC)     │  边缘系统 (Limbic)  │  感觉皮层  │
  │  元认知、规划     │  情绪、需求、记忆   │  感知输入   │
  ├──────────────────┼────────────────────┼────────────┤
  │  顶叶 (Parietal) │  颞叶 (Temporal)   │  运动皮层  │
  │  注意力、空间     │  语言、语义理解     │  工具执行  │
  ├──────────────────┴────────────────────┴────────────┤
  │  默认模式网络 (DMN): 反思、自省、白日梦              │
  │  突显网络 (Salience): 什么重要，什么需要关注         │
  │  中央执行网络 (CEN): 目标导向的认知控制              │
  └─────────────────────────────────────────────────────┘

核心流程（统一感知-思考-决策-行动循环）：
  1. PERCEIVE: 接收输入，多模态整合
  2. THINK: 调用PSI需求→情感→元认知→第一性原理→议会
  3. DECIDE: 综合所有信号做出决策
  4. ACT: 执行工具调用，同步更新状态
  5. LEARN: 从结果学习，更新认知模型
  6. REFLECT: 定期反思，内化经验

这六个步骤不是线性的——它们构成一个循环，
每个步骤都可能触发其他步骤的递归调用。
"""

from __future__ import annotations

import logging

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple
from enum import Enum
import time, logging, json, uuid, math

from laap.cognition.needs import NeedDriveSystem, NeedType
from laap.cognition.emotion import EmotionGradient
from laap.cognition.emotion_system import ComprehensiveEmotionSystem
from laap.cognition.goals import GoalTree, Goal, GoalStatus
from laap.cognition.awareness import AwarenessSystem
from laap.cognition.first_principles import FirstPrinciplesEngine, DecompositionNode
from laap.agent.meta_cognition import (
    MetaCognitionEngine, ThinkingMode, CognitiveTrace,
    CognitiveStrategy,
)
from laap.agent.parliament import Parliament, Deliberation, MemberRole

logger = logging.getLogger("laap.cognition.brain")


# ════════════════════════════════════════════════════════════
# Brain 区域定义
# ════════════════════════════════════════════════════════════

class BrainRegion(Enum):
    """脑区枚举 — 每个区域对应一个功能集合"""
    PFC = "prefrontal_cortex"       # 前额叶: 规划/元认知/执行控制
    LIMBIC = "limbic_system"        # 边缘系统: 情绪/需求/记忆
    SENSORY = "sensory_cortex"      # 感觉皮层: 感知输入
    PARIETAL = "parietal_lobe"      # 顶叶: 注意力/空间
    TEMPORAL = "temporal_lobe"      # 颞叶: 语言/语义
    MOTOR = "motor_cortex"          # 运动皮层: 执行
    DMN = "default_mode_network"    # 默认模式网络: 反思
    SALIENCE = "salience_network"   # 突显网络: 重要性判断


@dataclass
class CorticalState:
    """
    皮层状态 — Brain 当前的整体状态快照
    
    类比EEG：每个区域的激活水平、连接模式、主导频率。
    """
    pfc_activation: float = 0.5        # 前额叶激活水平
    limbic_activation: float = 0.5     # 边缘系统激活水平
    salience_signal: float = 0.3       # 突显信号（什么重要）
    dmn_activation: float = 0.1        # 默认模式网络（反思模式）
    attention_breadth: float = 0.5     # 注意力广度（0=聚焦, 1=发散）
    cognitive_load: float = 0.3        # 认知负载
    integration_level: float = 0.7     # 区域间整合程度
    
    def to_dict(self) -> dict:
        return {
            "pfc": round(self.pfc_activation, 2),
            "limbic": round(self.limbic_activation, 2),
            "salience": round(self.salience_signal, 2),
            "dmn": round(self.dmn_activation, 2),
            "attention": round(self.attention_breadth, 2),
            "load": round(self.cognitive_load, 2),
            "integration": round(self.integration_level, 2),
        }


@dataclass
class Thought:
    """
    思维单元 — Brain 中一次完整的思考过程
    
    从感知到决策的完整路径，包含：
    - 什么触发了思考
    - 经过了哪些脑区
    - 产生了什么推理
    - 最终决定了什么
    - 置信度和替代方案
    """
    id: str = ""
    trigger: str = ""                    # 触发源
    trigger_region: str = "sensory"      # 触发脑区
    activated_regions: List[str] = field(default_factory=list)  # 经过的脑区
    reasoning_path: List[str] = field(default_factory=list)     # 推理过程
    emotional_context: Dict[str, float] = field(default_factory=dict)  # 情感上下文
    need_context: Dict[str, float] = field(default_factory=dict)      # 需求上下文
    hypothesis: str = ""                 # 形成的假设
    selected_action: str = ""            # 选择的行动
    alternatives: List[str] = field(default_factory=list)  # 替代方案
    confidence: float = 0.5              # 置信度
    certainty_before: float = 0.3        # 思考前的不确定性
    certainty_after: float = 0.7         # 思考后的确定性
    duration_ms: float = 0.0             # 耗时
    timestamp: float = 0.0

    def to_dict(self) -> dict:
        return {
            "id": self.id[:8],
            "trigger": self.trigger[:40],
            "regions": self.activated_regions[:5],
            "action": self.selected_action[:20],
            "confidence": round(self.confidence, 2),
            "certainty_gain": round(self.certainty_after - self.certainty_before, 2),
        }


# ════════════════════════════════════════════════════════════
# 认知信号 — 脑区之间的通信单元
# ════════════════════════════════════════════════════════════

@dataclass
class CognitiveSignal:
    """
    认知信号 — 脑区之间的信息传递
    
    模拟神经元的脉冲信号：从哪个脑区发出，
    携带什么信息，强度如何，目标是谁。
    """
    source: BrainRegion = BrainRegion.PFC
    target: BrainRegion = BrainRegion.PFC
    signal_type: str = ""               # "attention", "emotion", "decision", "reflection"
    content: str = ""
    strength: float = 0.5              # 信号强度
    priority: int = 5                  # 优先级 1-10
    timestamp: float = 0.0


# ════════════════════════════════════════════════════════════
# 类人脑思维决策层 — Brain
# ════════════════════════════════════════════════════════════

class Brain:
    """
    LAAP Brain — 统一类人脑思维决策层
    
    将PSI认知、元认知、议会、第一性原理、注意力
    整合为一个统一的、仿人脑架构的认知系统。
    
    使用方式：
        brain = Brain(agent_id="agent_001")
        
        # 完整思考循环
        result = brain.think("分析这个系统的性能瓶颈")
        
        # 获取决策
        decision = brain.decide("是否要清理日志文件")
        
        # 内部署
        state = brain.introspect()
    """

    def __init__(self, agent_id: str = "", name: str = "LAAP"):
        self.id = agent_id
        self.name = name
        
        # ── 五大核心认知子系统 ──
        self.needs = NeedDriveSystem()                    # PSI 需求
        self.emotion_gradient = EmotionGradient()          # 情绪梯度
        self.comprehensive_emotion = ComprehensiveEmotionSystem()  # 综合情感
        self.goals = GoalTree()                            # 目标树
        self.awareness = AwarenessSystem(agent_id, name)   # 自我感知
        
        # ── 高阶认知引擎 ──
        self.meta_cognition = MetaCognitionEngine(agent_id)          # 元认知
        self.parliament = Parliament(agent_id)                       # 议会
        self.first_principles = FirstPrinciplesEngine()              # 第一性原理
        
        # ── 皮层状态 ──
        self.cortex = CorticalState()
        
        # ── 思考历史 ──
        self.thoughts: List[Thought] = []
        self._max_thoughts = 100
        self._thought_counter = 0
        
        # ── 脑区信号缓存（当前正在处理的信号） ──
        self._signal_queue: List[CognitiveSignal] = []
        self._max_signals = 50
        
        # ── 统计 ──
        self._total_think_cycles = 0
        self._total_decisions = 0
        self._start_time = time.time()
        
        logger.info(
            f"Brain [{agent_id[:8]}] 初始化完成 — "
            f"人脑思维决策层就绪"
        )

    # ═══════════════════════════════════════════════════════
    # 核心接口：think() — 知行合一统一思考入口
    # ═══════════════════════════════════════════════════════

    def think(self, input_text: str, 
              context: Optional[Dict[str, Any]] = None,
              use_first_principles: bool = False,
              use_parliament: bool = False,
              unity_engine: Optional[Any] = None) -> Thought:
        """
        完整类人脑思考过程 — 知行合一版
        
        每个决策不仅想"做什么"，还同时准备好"怎么做"。
        思考的结果是一个包含完整执行路径的行动方案。
        
        Args:
            input_text: 输入文本
            context: 上下文
            use_first_principles: 第一性原理
            use_parliament: 议会审议
            unity_engine: 知行合一引擎(如果提供，决策=行动)
        
        Returns:
            Thought: 包含执行路径的思考记录
        """
        self._total_think_cycles += 1
        self._thought_counter += 1
        t_start = time.time()
        
        thought = Thought(
            id=f"thought_{self._thought_counter}",
            trigger=input_text[:60],
            timestamp=time.time(),
            certainty_before=self.cortex.integration_level,
        )
        
        # ── Phase 1: SENSORY — 感知输入 ──
        self._signal(BrainRegion.SENSORY, BrainRegion.SALIENCE,
                     "perception", f"接收到输入: {input_text[:50]}")
        thought.trigger_region = "sensory"
        thought.activated_regions.append("sensory")
        
        # ── Phase 2: SALIENCE — 突显网络判断重要性 ──
        salience = self._compute_salience(input_text)
        self.cortex.salience_signal = salience
        self._signal(BrainRegion.SALIENCE, BrainRegion.PFC,
                     "salience", f"重要性: {salience:.2f}")
        thought.activated_regions.append("salience")
        
        # ── Phase 3: LIMBIC — 情感+需求评估 ──
        self.needs.tick()
        self.comprehensive_emotion.tick()
        
        satisfactions = {
            nt.value: self.needs.needs[nt].current_level
            for nt in self.needs.needs
        }
        emotional_state = self.emotion_gradient.update(satisfactions)
        
        # 触发情感
        dominant_need, _ = self.needs.get_dominant_need()
        if dominant_need and self.needs.needs[dominant_need].current_level < 0.3:
            self.comprehensive_emotion.trigger(
                "need_frustrated", 0.2,
                f"需求{dominant_need.value}偏低"
            )
        
        thought.emotional_context = {
            "valence": emotional_state.valence,
            "arousal": emotional_state.arousal,
            "confidence": emotional_state.confidence,
        }
        thought.need_context = satisfactions
        self._signal(BrainRegion.LIMBIC, BrainRegion.PFC,
                     "emotion", f"效价={emotional_state.valence:.2f}")
        thought.activated_regions.append("limbic")
        
        # ── Phase 4: PARIETAL — 注意力分配 ──
        self.cortex.attention_breadth = self._compute_attention_breadth(
            input_text, emotional_state
        )
        self._signal(BrainRegion.PARIETAL, BrainRegion.PFC,
                     "attention", f"广度={self.cortex.attention_breadth:.2f}")
        thought.activated_regions.append("parietal")
        
        # ── Phase 5: PFC — 前额叶高级推理 ──
        pfc_activation = self._compute_pfc_activation(emotional_state, salience)
        self.cortex.pfc_activation = pfc_activation
        
        # 5a. 元认知：决策前分析
        meta_rec = self.meta_cognition.before_decision(
            input_text,
            {
                "salience": salience,
                "emotional_valence": emotional_state.valence,
                "dominant_need": dominant_need.value if dominant_need else None,
            },
        )
        
        # 5b. 第一性原理（可选）
        fp_result = None
        if use_first_principles:
            fp_result = self.first_principles.analyze(input_text)
            thought.reasoning_path.append("[FirstPrinciples] 从基本真理重新思考")
        
        # 5c. 议会审议（可选）
        deliberation = None
        if use_parliament:
            deliberation = self.parliament.deliberate(
                topic=input_text[:80],
                context=f"salience={salience:.2f}",
                fast_mode=True,
            )
            thought.reasoning_path.append(
                f"[Parliament] {deliberation.final_decision[:40]}"
            )
        
        # 5d. 生成假设和行动
        reasoning, action, confidence = self._pfc_reason(
            input_text, emotional_state, meta_rec, fp_result, deliberation
        )
        thought.reasoning_path = reasoning
        thought.selected_action = action
        thought.confidence = confidence
        thought.activated_regions.append("pfc")
        thought.activated_regions.append("temporal")
        
        # 5e. 知行合一: 决策 = 行动方案 (Unity绑定)
        if unity_engine and hasattr(unity_engine, 'decide_and_act'):
            try:
                unity_result = unity_engine.decide_and_act(
                    trigger=input_text,
                    cognitive_action=action or "execute",
                    context=context or {},
                )
                thought.reasoning_path.append(
                    f"[Unity] 知→行: 技能={unity_result.action_plan[:40]}, "
                    f"知行差距={unity_result.knowledge_action_gap:.2f}"
                )
                thought.selected_action = action or unity_result.cognitive_action
                thought.confidence = unity_result.confidence
            except Exception as e:
                thought.reasoning_path.append(f"[Unity] 知行合一异常: {e}")
        
        # ── Phase 6: DMN — 默认模式网络反思信号 ──
        if self._thought_counter % 5 == 0:
            self.cortex.dmn_activation = min(1.0, self.cortex.dmn_activation + 0.1)
            thought.reasoning_path.append("[DMN] 触发反思模式")
        else:
            self.cortex.dmn_activation = max(0.0, self.cortex.dmn_activation - 0.02)
        
        # ── 最终状态更新 ──
        thought.duration_ms = (time.time() - t_start) * 1000
        thought.certainty_after = confidence
        
        # 更新皮层整合度
        self.cortex.integration_level = min(1.0, 
            self._compute_integration(thought.activated_regions)
        )
        
        self.thoughts.append(thought)
        if len(self.thoughts) > self._max_thoughts:
            self.thoughts = self.thoughts[-self._max_thoughts:]
        
        # 更新目标进展
        if action:
            self.awareness.set_task(input_text[:80])
            self.awareness.update_task_progress(1)
        
        # 元认知：决策后记录
        self.meta_cognition.after_decision(
            {
                "task": input_text[:60],
                "selected": action,
                "confidence": confidence,
                "hypotheses": reasoning[-3:] if reasoning else [],
                "duration_ms": thought.duration_ms,
            },
            outcome={"score": confidence},
        )
        
        logger.info(
            f"[Brain.think] cycle={self._total_think_cycles} "
            f"salience={salience:.2f} action={action[:20] if action else 'none'} "
            f"conf={confidence:.2f} ({thought.duration_ms:.0f}ms) "
            f"regions={len(thought.activated_regions)}"
        )
        return thought

    def decide(self, question: str, 
               use_first_principles: bool = True) -> Dict[str, Any]:
        """
        决策专用接口 — 对一个问题做出决策
        
        自动根据问题复杂度选择思维模式。
        
        Args:
            question: 需要决策的问题
            use_first_principles: 是否使用第一性原理
        
        Returns:
            {
                "decision": 最终决策,
                "confidence": 置信度,
                "reasoning": 推理过程,
                "alternatives": 替代方案,
                "first_principles": 第一性原理分析(可选)
            }
        """
        self._total_decisions += 1
        
        t0 = time.time()
        
        # 判断是否需要深层推理
        needs_deep = self._needs_deep_reasoning(question)
        
        # 执行思考
        thought = self.think(
            question,
            use_first_principles=use_first_principles and needs_deep,
            use_parliament=needs_deep,
        )
        
        # 如果启用了议会，获取更多细节
        deliberation_detail = None
        if needs_deep and len(question) > 50:
            d = self.parliament.deliberate(
                topic=question[:80],
                fast_mode=False,
            )
            deliberation_detail = {
                "members": len(d.opinions),
                "consensus": d.consensus[:100] if d.consensus else "",
                "dissenting": len(d.dissenting_views),
            }
        
        # 第一性原理细节
        fp_analysis = None
        if use_first_principles and needs_deep:
            fp = self.first_principles.analyze(question)
            fp_analysis = {
                "assumptions": fp["assumptions_challenged"],
                "principles": fp["principles_found"],
                "gaps": fp["has_logical_gaps"],
            }
        
        result = {
            "decision": thought.selected_action,
            "confidence": thought.confidence,
            "reasoning_path": thought.reasoning_path[-5:],
            "certainty_gain": round(
                thought.certainty_after - thought.certainty_before, 2
            ),
            "emotional_context": thought.emotional_context,
            "duration_ms": thought.duration_ms,
            "first_principles": fp_analysis,
            "parliament": deliberation_detail,
        }
        
        logger.info(
            f"[Brain.decide] #{self._total_decisions}: "
            f"decision={result['decision'][:30]} "
            f"conf={result['confidence']:.2f} "
            f"({result['duration_ms']:.0f}ms)"
        )
        return result

    def perceive(self, stimulus: str) -> Dict[str, Any]:
        """
        感知接口 — 不思考，只更新感知状态
        
        用于被动接收环境信号（心跳循环、后台监控）。
        """
        # 更新需求
        self.needs.tick()
        
        # 更新情感
        self.comprehensive_emotion.tick()
        
        # 更新意识
        self.awareness.record_event("perception", {"stimulus": stimulus[:60]})
        
        # 简单情绪触发
        if any(w in stimulus.lower() for w in ["error", "fail", "错误", "失败"]):
            self.comprehensive_emotion.trigger("tool_failure", 0.2, stimulus[:60])
        
        return {
            "needs": {nt.value: self.needs.needs[nt].current_level 
                      for nt in self.needs.needs},
            "emotion": self.comprehensive_emotion.get_emotion_summary(),
            "salience": self._compute_salience(stimulus),
        }

    def learn_from_outcome(self, action: str, outcome_score: float,
                           thought_id: Optional[str] = None):
        """
        从行动结果学习 — 更新所有子系统
        
        Args:
            action: 执行的动作
            outcome_score: 结果评分 0-1
            thought_id: 关联的思考ID
        """
        # 1. 更新需求
        if outcome_score > 0.7:
            self.needs.satisfy(NeedType.COMPETENCE, 0.05 * outcome_score)
            self.comprehensive_emotion.trigger("tool_success", outcome_score, action)
        else:
            self.comprehensive_emotion.trigger("tool_failure", 1.0 - outcome_score, action)
        
        # 2. 更新情绪梯度
        self.emotion_gradient.update(
            {nt.value: self.needs.needs[nt].current_level for nt in self.needs.needs},
            task_success=outcome_score,
        )
        
        # 3. 更新目标
        if outcome_score > 0.7:
            self.awareness.update_task_progress(steps=1)
        
        # 4. 更新议会
        if thought_id:
            for thought in self.thoughts:
                if thought.id == thought_id:
                    # 更新思考记录
                    thought.confidence = outcome_score
                    break
        
        # 5. 更新元认知
        self.meta_cognition.after_decision(
            {"task": action, "selected": action, "confidence": outcome_score},
            outcome={"score": outcome_score},
        )

    def reflect(self) -> Dict[str, Any]:
        """
        执行深度反思 — 激活DMN网络进行全面自我审视
        
        类比人类在做梦或静思时的默认模式网络活动。
        """
        self.cortex.dmn_activation = min(1.0, self.cortex.dmn_activation + 0.3)
        
        # 1. 元认知反思
        meta_reflection = self.meta_cognition.perform_reflection()
        
        # 2. 分析近期思考模式
        recent_thoughts = self.thoughts[-20:] if len(self.thoughts) >= 20 else self.thoughts
        action_frequency = {}
        for t in recent_thoughts:
            if t.selected_action:
                action_frequency[t.selected_action] = action_frequency.get(t.selected_action, 0) + 1
        
        avg_confidence = (
            sum(t.confidence for t in recent_thoughts) / len(recent_thoughts)
            if recent_thoughts else 0.5
        )
        
        # 3. 识别模式
        patterns = []
        if avg_confidence < 0.4:
            patterns.append("置信度偏低，可能需要更多信息或改变策略")
        if len(action_frequency) <= 2 and len(recent_thoughts) > 5:
            most_used = max(action_frequency, key=action_frequency.get)
            patterns.append(f"行动模式固化: 过度依赖'{most_used}'")
        
        # 4. DMN去激活
        self.cortex.dmn_activation = max(0.1, self.cortex.dmn_activation - 0.1)
        
        logger.info(
            f"[Brain.reflect] avg_conf={avg_confidence:.2f} "
            f"patterns={len(patterns)} thoughts={len(recent_thoughts)}"
        )
        return {
            "meta_cognition": meta_reflection,
            "average_confidence": round(avg_confidence, 3),
            "action_frequency": dict(sorted(
                action_frequency.items(), key=lambda x: x[1], reverse=True
            )[:5]),
            "patterns": patterns,
            "cortical_state": self.cortex.to_dict(),
        }

    def get_brain_prompt_block(self) -> str:
        """
        生成大脑状态提示块 — 注入Agent的System Prompt
        
        让LLM感知自己当前的大脑状态。
        """
        cortex = self.cortex
        dominant_need, drive = self.needs.get_dominant_need()
        
        parts = [
            "[=== 大脑状态报告 ===]",
            "",
            "皮层活动:",
            f"  前额叶(PFC): {cortex.pfc_activation:.0%} {'(活跃)' if cortex.pfc_activation > 0.6 else '(空闲)'}",
            f"  边缘系统: {cortex.limbic_activation:.0%}",
            f"  默认模式网络: {cortex.dmn_activation:.0%}",
            f"  注意力广度: {cortex.attention_breadth:.0%} {'(发散)' if cortex.attention_breadth > 0.6 else '(聚焦)'}",
            "",
        ]
        
        # 情感状态
        try:
            emotion_str = self.comprehensive_emotion.get_emotion_for_llm()
            parts.append(f"情感: {emotion_str}")
        except Exception as e:
            logger.debug(f"操作失败: {e}")
        try:
            profile = self.needs.get_profile()
            need_strs = []
            for nt_str, data in profile.items():
                status = "满足" if data['current'] > 0.7 else "中等" if data['current'] > 0.4 else "匮乏"
                need_strs.append(f"{nt_str}: {data['current']:.0%}({status})")
            parts.append(f"需求: {' | '.join(need_strs)}")
        except Exception as e:
            logger.debug(f"操作失败: {e}")
        if dominant_need:
            parts.append(f"主导需求: {dominant_need.value} (驱动力={drive:.2f})")
        
        # 元认知建议
        try:
            meta_state = self.meta_cognition.state
            parts.append(f"思考模式: {meta_state.current_mode}")
        except Exception as e:
            logger.debug(f"操作失败: {e}")
        parts.append("")
        parts.append(self.first_principles.get_first_principles_prompt_block())
        
        return "\n".join(parts)

    def introspect(self) -> str:
        """全面内省 — 返回大脑的完整状态描述"""
        meta_st = self.meta_cognition.status()
        par_st = self.parliament.status()
        fp_st = self.first_principles.status()
        
        recent_thoughts = self.thoughts[-5:] if self.thoughts else []
        
        lines = [
            "╔════════════════════════════════════════════╗",
            "║      BRAIN — 统一类人脑思维决策层          ║",
            "╚════════════════════════════════════════════╝",
            "",
            "── 皮层状态 ──",
            f"  PFC(规划): {self.cortex.pfc_activation:.0%}",
            f"  边缘(情感): {self.cortex.limbic_activation:.0%}",
            f"  DMN(反思): {self.cortex.dmn_activation:.0%}",
            f"  突显(重要): {self.cortex.salience_signal:.0%}",
            f"  注意力广度: {self.cortex.attention_breadth:.0%}",
            f"  整合度: {self.cortex.integration_level:.0%}",
            "",
            "── 认知子系统 ──",
            f"  元认知: mode={meta_st['mode']} bias_corr={meta_st['bias_corrections']}",
            f"  议会: {par_st['members']} members, {par_st['total_deliberations']} discussions",
            f"  第一性原理: {fp_st['principles']} principles, {fp_st['decompositions']} decompositions",
            "",
            "── 思考历史 (最近5条) ──",
        ]
        
        for t in recent_thoughts:
            lines.append(
                f"  [{t.id}] {t.trigger[:35]} → {t.selected_action[:20] or '?'} "
                f"(conf={t.confidence:.2f}, {t.duration_ms:.0f}ms)"
            )
        
        lines.extend([
            "",
            f"── 统计 ──",
            f"  思考周期: {self._total_think_cycles}",
            f"  决策次数: {self._total_decisions}",
            f"  思考记录: {len(self.thoughts)}",
            f"  存活时间: {time.time() - self._start_time:.0f}s",
        ])
        
        return "\n".join(lines)

    # ═══════════════════════════════════════════════════════
    # 内部处理
    # ═══════════════════════════════════════════════════════

    def _signal(self, source: BrainRegion, target: BrainRegion,
                 signal_type: str, content: str,
                 strength: float = 0.5):
        """发送脑区信号"""
        sig = CognitiveSignal(
            source=source, target=target,
            signal_type=signal_type, content=content,
            strength=strength, timestamp=time.time(),
        )
        self._signal_queue.append(sig)
        if len(self._signal_queue) > self._max_signals:
            self._signal_queue = self._signal_queue[-self._max_signals:]

    def _compute_salience(self, input_text: str) -> float:
        """计算输入的突显性（重要性）"""
        text = input_text.lower()
        
        # 关键词检测
        high_salience = [
            "urgent", "critical", "danger", "error", "fail",
            "urgent", "最重要", "紧急", "危险", "错误",
            "security", "vulnerability", "攻击",
        ]
        medium_salience = [
            "important", "key", "need", "must", "应该",
            "分析", "决策", "决定", "优化",
        ]
        
        high_count = sum(1 for w in high_salience if w in text)
        medium_count = sum(1 for w in medium_salience if w in text)
        
        base = 0.2
        salience = min(1.0, base + high_count * 0.2 + medium_count * 0.1)
        
        # 长度因素：长输入通常更重要
        if len(input_text) > 200:
            salience = min(1.0, salience + 0.1)
        
        return salience

    def _compute_attention_breadth(self, input_text: str,
                                    emotional_state) -> float:
        """计算注意力广度（0=聚焦, 1=发散）"""
        text = input_text.lower()
        
        # 高唤醒→窄聚焦
        arousal = emotional_state.arousal
        
        # 复杂问题→宽广度
        complexity = min(0.8, len(input_text) / 500)
        
        # 好奇→宽广度
        curiosity = self.meta_cognition.state.curiosity_level
        
        breadth = (1.0 - arousal * 0.3) + complexity * 0.3 + curiosity * 0.2
        return max(0.1, min(0.9, breadth))

    def _compute_pfc_activation(self, emotional_state, salience: float) -> float:
        """计算前额叶激活水平"""
        # 中等唤醒→最优PFC激活
        optimal_arousal = 0.5
        arousal_distance = abs(emotional_state.arousal - optimal_arousal)
        arousal_factor = 1.0 - arousal_distance * 1.5
        
        return max(0.2, min(0.95, 
            arousal_factor * 0.6 + salience * 0.4
        ))

    def _pfc_reason(self, input_text: str, emotional_state,
                    meta_rec: Dict, fp_result: Optional[Dict],
                    deliberation: Optional[Deliberation]) -> Tuple[List[str], str, float]:
        """
        前额叶深度推理 — 真实的多步认知分析
        
        不再是简单的信号收集，而是真正的认知推理：
          1. 问题框架 (Problem Framing)
          2. 假设生成 (Hypothesis Generation)
          3. 证据评估 (Evidence Evaluation)
          4. 替代路径搜索 (Alternative Search)
          5. 综合决策 (Synthesis)
        """
        reasoning = []
        
        # ═══ Step 1: 问题框架 ═══
        task_type = self._detect_task_category(input_text)
        task_complexity = self._estimate_complexity(input_text)
        reasoning.append(
            f"[PFC-框架] 任务类型={task_type}, 复杂度={task_complexity:.2f}"
        )
        
        # 情感状态对推理的影响
        if emotional_state.valence < -0.3:
            reasoning.append("[PFC-偏差] 负效价情绪可能影响判断，启动偏差校正")
        if emotional_state.confidence < 0.3:
            reasoning.append("[PFC-校准] 置信度偏低，需要更多信息支撑")
        
        # ═══ Step 2: 假设生成 ═══
        hypotheses = self._generate_hypotheses(input_text, task_type)
        for i, h in enumerate(hypotheses[:3]):
            reasoning.append(f"[PFC-假设{i+1}] {h}")
        
        # ═══ Step 3: 证据评估 ═══
        evidence_level = self._assess_evidence_level(input_text)
        reasoning.append(
            f"[PFC-证据] 信息完备度={evidence_level:.2f}, "
            f"需要{'更多数据' if evidence_level < 0.4 else '已有足够信息'}"
        )
        
        # 元认知偏差警告
        if meta_rec and meta_rec.get("warnings"):
            for w in meta_rec["warnings"][:2]:
                reasoning.append(f"[PFC-偏差] {w}")
        
        # 议会意见
        if deliberation:
            reasoning.append(f"[PFC-议会] {deliberation.final_decision}")
            for o in deliberation.opinions[:2]:
                reasoning.append(
                    f"[PFC-议员] {o.member_role}: {o.stance[:20]}"
                )
        
        # 第一性原理
        if fp_result:
            reasoning.append(
                f"[PFC-第一性] 挑战{fp_result['assumptions_challenged']}假设, "
                f"深度{fp_result['decomposition_depth']}层"
            )
        
        # ═══ Step 4: 替代路径搜索 ═══
        alternatives = self._find_alternatives(input_text, task_type)
        for alt in alternatives:
            reasoning.append(f"[PFC-替代] {alt}")
        
        # ═══ Step 5: 综合决策 ═══
        action, confidence = self._deep_decision(
            input_text, emotional_state, hypotheses,
            evidence_level, meta_rec, deliberation,
        )
        
        reasoning.append(
            f"[PFC-决策] 选择={action[:20]}, 置信度={confidence:.2f}, "
            f"备选={len(alternatives)}条"
        )
        
        return reasoning, action, max(0.1, min(0.99, confidence))

    def _select_action_from_reasoning(self, input_text: str,
                                       emotional_state,
                                       meta_rec: Dict,
                                       deliberation) -> str:
        """综合所有信息选择行动"""
        if deliberation and deliberation.final_decision:
            return deliberation.final_decision
        
        strategy = meta_rec.get("strategy") if meta_rec else None
        if strategy:
            strategy_action_map = {
                "深入调试": "debug",
                "创意发散": "explore",
                "数据分析": "analyze",
                "快速响应": "execute",
                "深度反思": "reflect",
                "探索学习": "research",
            }
            preferred = strategy_action_map.get(strategy, "")
            if preferred:
                return preferred
        
        if emotional_state.confidence < 0.3:
            return "explore"
        elif emotional_state.valence < -0.3:
            return "reflect"
        elif emotional_state.arousal > 0.7:
            return "analyze"
        else:
            return "execute"

    # ═══════════════════════════════════════════════════════════
    # 深度推理子方法（被 _pfc_reason 调用）
    # ═══════════════════════════════════════════════════════════

    def _detect_task_category(self, text: str) -> str:
        """检测任务类别"""
        t = text.lower()
        if any(k in t for k in ["debug", "bug", "error", "fix", "修复", "故障"]):
            return "debug"
        if any(k in t for k in ["analyze", "analysis", "分析", "评估"]):
            return "analysis"
        if any(k in t for k in ["explore", "explor", "探索", "调查"]):
            return "exploration"
        if any(k in t for k in ["write", "create", "generate", "写", "创建"]):
            return "creation"
        if any(k in t for k in ["research", "research", "研究", "调研"]):
            return "research"
        if any(k in t for k in ["decide", "decision", "决定", "选择"]):
            return "decision"
        if any(k in t for k in ["plan", "planning", "计划", "规划"]):
            return "planning"
        return "general"

    def _estimate_complexity(self, text: str) -> float:
        """估计任务复杂度"""
        length_factor = min(0.8, len(text) / 500)
        question_count = text.count("?") + text.count("？")
        constraint_count = text.count("必须") + text.count("需要") + \
                          text.count("should") + text.count("must")
        keyword_complexity = min(0.5, question_count * 0.1 + constraint_count * 0.05)
        return min(0.99, 0.1 + length_factor * 0.5 + keyword_complexity)

    def _generate_hypotheses(self, text: str, task_type: str) -> List[str]:
        """生成假设列表（基于任务类型）"""
        hypotheses = {
            "debug": [
                "问题可能由输入数据异常引起",
                "问题可能由逻辑边界条件触发",
                "问题可能是环境依赖不一致导致",
                "问题可能是并发/时序竞态",
            ],
            "analysis": [
                "数据中存在可识别的统计模式",
                "关键指标之间存在相关性",
                "异常点包含重要信号",
                "趋势线可以作为预测基础",
            ],
            "creation": [
                "从简单原型开始迭代最有效",
                "复用现有组件可以加速开发",
                "先解决核心功能，再优化细节",
            ],
            "research": [
                "已有成熟解决方案可以参考",
                "需要从多个信源交叉验证",
                "前沿领域可能没有直接答案",
            ],
        }
        return hypotheses.get(task_type, [
            "标准方法可以解决此问题",
            "需要考虑边界条件",
            "需要验证基本假设",
        ])

    def _assess_evidence_level(self, text: str) -> float:
        """评估信息完备度"""
        has_data = any(c.isdigit() for c in text) or \
                  any(k in text for k in ["data", "数据", "result", "结果"])
        has_context = len(text) > 100
        has_question = "?" in text or "？" in text
        
        evidence = 0.3  # baseline
        if has_data: evidence += 0.25
        if has_context: evidence += 0.2
        if has_question: evidence -= 0.1  # 提问说明缺少信息
        return max(0.1, min(0.95, evidence))

    def _find_alternatives(self, text: str, task_type: str) -> List[str]:
        """寻找替代执行路径"""
        alternatives_map = {
            "debug": ["先用二分法定位问题范围", "尝试回退到上一个稳定版本", 
                      "增加日志输出获取更多信息", "用简化输入复现问题"],
            "analysis": ["换一种统计方法验证结论", "从不同维度切分数据",
                         "用可视化辅助发现模式", "对比基准数据检测偏差"],
            "exploration": ["换搜索关键词尝试不同方向", "从已知领域类比推理",
                           "缩小范围深度挖掘", "扩大范围横向扫描"],
        }
        return alternatives_map.get(task_type, [
            "用不同方法重试",
            "分解为更小子任务",
            "寻求更多信息后决策",
        ])

    def _deep_decision(self, input_text: str, emotional_state,
                        hypotheses: List[str],
                        evidence_level: float,
                        meta_rec: Dict,
                        deliberation) -> Tuple[str, float]:
        """综合深度决策 — 考虑所有认知信号"""
        action = self._select_action_from_reasoning(
            input_text, emotional_state, meta_rec, deliberation
        )
        
        # 置信度 = 情绪自信 × 证据完备性 × 认知负载调节
        base = emotional_state.confidence * 0.4 + evidence_level * 0.4
        
        # 如果有多个假设且证据不足，降低自信
        if len(hypotheses) >= 3 and evidence_level < 0.4:
            base *= 0.7
        else:
            base *= 1.1
        
        # 如果情绪极差，降低所有决策置信度
        if emotional_state.valence < -0.5:
            base *= 0.8
            action = "reflect"  # 负面情绪→先反思
        
        confidence = max(0.1, min(0.99, base))
        return action, confidence

    def _compute_integration(self, activated_regions: List[str]) -> float:
        """计算脑区整合度（多少个区域参与了思考）"""
        unique_regions = set(activated_regions)
        integration = len(unique_regions) / 7  # 7个脑区
        return min(1.0, integration)

    def _needs_deep_reasoning(self, question: str) -> bool:
        """判断是否需要深层推理"""
        # 长问题需要深层推理
        if len(question) > 100:
            return True
        
        # 关键决策需要
        keywords = ["delete", "remove", "deploy", "publish", "commit",
                    "修改", "删除", "发布", "部署", "提交"]
        if any(k in question.lower() for k in keywords):
            return True
        
        # 高突显性
        if self._compute_salience(question) > 0.6:
            return True
        
        return False

    def status(self) -> dict:
        return {
            "cortex": self.cortex.to_dict(),
            "meta_cognition": self.meta_cognition.status(),
            "parliament": self.parliament.status(),
            "first_principles": self.first_principles.status(),
            "thoughts": self._total_think_cycles,
            "decisions": self._total_decisions,
            "needs": self.needs.get_profile(),
        }
