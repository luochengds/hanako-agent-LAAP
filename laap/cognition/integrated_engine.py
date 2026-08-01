"""
LAAP — Phase 2 认知-记忆深度集成引擎

将长期记忆系统与认知引擎深度整合，实现：
1. 认知状态驱动的记忆存储
2. 情绪驱动的记忆巩固
3. 经验检索辅助决策
4. 技能记忆的应用与强化
5. 自我反思与记忆关联

Phase 2 验证指标：情绪一致性 > 90%，记忆辅助决策准确率 > 75%
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union
from pathlib import Path
import time
import numpy as np
import logging

from laap.cognition.needs import NeedDriveSystem, NeedType
from laap.cognition.goals import GoalTree, Goal, GoalStatus
from laap.cognition.emotion import EmotionGradient, EmotionalState
from laap.cognition.awareness import AwarenessSystem
from laap.cognition.entropy import (
    CognitiveEntropyMonitor, CoarseGrainer, measure_cognitive_state,
    EntropySnapshot, CoarseGrainedField, Hilbert6Metrics
)
from laap.memory.long_term import (
    LongTermMemory, MemoryEntry, MemoryType, 
    ProceduralMemory, ProceduralStep
)
from laap.cognition.error_reflection import (
    ErrorReflectionPipeline,
    ErrorReflectionFrame,
    ReasoningTraceNode,
    CalibrationSignal,
    create_error_reflection_pipeline,
)
from laap.cognition.truth_grounding import (
    TruthGroundingEngine,
    EpistemicReport,
    create_truth_grounding_engine,
)

logger = logging.getLogger("laap.cognition.integrated")


@dataclass
class CognitiveAction:
    """认知动作 — 由认知引擎产生的响应"""
    action_type: str
    description: str
    priority: float
    need_type: Optional[str] = None
    confidence: float = 0.7
    related_memories: List[str] = field(default_factory=list)  # 关联的记忆ID
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CognitiveState:
    """认知状态快照（含记忆信息）"""
    needs: Dict[str, float]
    emotions: EmotionalState
    active_goals: List[Dict]
    dominant_need: Optional[str]
    drive_strength: float
    recent_memories: int = 0  # 最近存储的记忆数量
    relevant_memories: List[str] = field(default_factory=list)  # 当前相关的记忆
    entropy: float = 0.0  # 当前认知熵
    flow_regime: str = "laminar"  # 认知流态
    creative_window: bool = False  # 是否处于创造性窗口
    gradient_magnitude: float = 0.0  # 认知场梯度幅度
    thinking_mode: str = "balanced"  # focused | balanced | divergent
    timestamp: float = field(default_factory=time.time)


@dataclass
class ExperienceEvent:
    """经验事件 — 用于存储到长期记忆"""
    event_type: str  # success, failure, learning, interaction, observation
    content: str
    emotional_valence: float
    importance: float
    tags: List[str] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)


def _cognitive_state_to_dict(state: CognitiveState) -> Dict[str, Any]:
    """Convert CognitiveState into a plain dict for optional plugins."""
    return {
        "needs": state.needs,
        "emotional_valence": state.emotions.valence,
        "dominant_need": state.dominant_need,
        "drive_strength": state.drive_strength,
        "recent_memories": state.recent_memories,
        "entropy": state.entropy,
        "flow_regime": state.flow_regime,
        "creative_window": state.creative_window,
        "gradient_magnitude": state.gradient_magnitude,
        "thinking_mode": state.thinking_mode,
    }


class IntegratedCognitiveEngine:
    """
    LAAP 认知-记忆深度集成引擎
    
    核心功能：
    1. 认知状态驱动的记忆存储
       - 重要事件自动存储为情景记忆
       - 成功经验存储为程序记忆
       - 知识获取存储为语义记忆
    
    2. 情绪驱动的记忆巩固
       - 正情绪时强化相关记忆
       - 负情绪时弱化或重新评估记忆
    
    3. 经验检索辅助决策
       - 根据当前需求检索相关经验
       - 应用已存储的技能和程序
    
    4. 自我反思与记忆关联
       - 定期反思并存储反思结果
       - 建立记忆之间的关联
    """

    # 记忆存储阈值
    _IMPORTANCE_THRESHOLD = 0.5  # 重要性超过此值的事件会被存储
    _EMOTIONAL_THRESHOLD = 0.3   # 情绪效价超过此值的事件会被存储
    
    def __init__(self, agent_id: str = "", agent_name: str = "LAAP",
                 memory_db_path: Optional[Union[str, Path]] = None):
        # 核心认知组件
        self.need_system = NeedDriveSystem()
        self.goal_tree = GoalTree()
        self.emotion_system = EmotionGradient()
        self.awareness = AwarenessSystem(agent_id, agent_name)
        
        # 长期记忆系统
        self.long_term_memory = LongTermMemory(db_path=memory_db_path)
        
        # 状态追踪
        self._tick_interval = 1.0
        self._last_tick = time.time()
        self._action_history: List[CognitiveAction] = []
        self._max_history = 100
        
        # 经验事件队列
        self._experience_queue: List[ExperienceEvent] = []
        self._max_queue = 50
        
        # 性能指标
        self._total_actions = 0
        self._successful_actions = 0
        self._needs_met = 0
        self._needs_attempted = 0
        self._memories_used = 0  # 使用记忆辅助决策的次数
        self._memory_assisted_success = 0  # 记忆辅助成功的次数
        
        # Hilbert6 认知熵系统
        self.entropy_monitor = CognitiveEntropyMonitor(window_size=20)
        self.coarse_grainer = CoarseGrainer(grid_resolution=8)
        self._last_hilbert6: Optional[Hilbert6Metrics] = None
        self.thinking_mode: str = "balanced"  # focused | balanced | divergent

        # 反思周期
        self._reflection_interval = 100  # 每100次tick进行一次反思
        self._tick_count = 0

        # 错误反思管道
        self.error_reflection = create_error_reflection_pipeline(
            long_term_memory=self.long_term_memory,
            auto_restore=True,
        )
        # 当前查询的校准信号缓存（_retrieve_relevant_memories 时填充）
        self._active_calibrations: List[CalibrationSignal] = []

        # 真理级知识建构引擎
        self.truth_grounding = create_truth_grounding_engine(
            long_term_memory=self.long_term_memory,
        )

        # 初始化默认目标树
        self._init_default_goals()
        
        # 初始化自我身份记忆
        self._init_identity_memory(agent_id, agent_name)

        # optional memory bandit (adaptive retrieval strategy)
        self.memory_bandit: Any = None

        # optional autonomy protection filter
        self.autonomy_filter: Any = None

        logger.info(f"[{agent_name}] 认知-记忆集成引擎初始化完成")

    def set_memory_bandit(self, bandit: Any) -> None:
        """Attach an optional memory bandit controller.

        The controller must implement::

            select_arm(cognitive_state: dict, query: str) -> (arm, arm_config)
            record_reward(reward: float)
        """
        self.memory_bandit = bandit

    def set_autonomy_filter(self, filter_obj: Any) -> None:
        """Attach an optional autonomy protection filter.

        The filter must implement::

            assess(query: str, context: dict) -> assessment
            assessment.recommended_mode: str
            assessment.suggested_prompts: list[str]
        """
        self.autonomy_filter = filter_obj

    def _init_default_goals(self):
        """初始化默认的需求驱动目标树"""
        root = Goal(name="生存与成长", priority=1.0)
        self.goal_tree.set_root(root)
        
        need_goals = [
            Goal(name="寻求确定性", priority=0.9, need_type="certainty"),
            Goal(name="提升能力", priority=1.0, need_type="competence"),
            Goal(name="保持自主", priority=0.7, need_type="autonomy"),
            Goal(name="建立连接", priority=0.6, need_type="relatedness"),
            Goal(name="获取能量", priority=0.8, need_type="energy"),
        ]
        
        for goal in need_goals:
            self.goal_tree.add_subgoal(root.id, goal)
        
        # 为能力目标添加子目标
        competence_goal = need_goals[1]
        self.goal_tree.add_subgoal(competence_goal.id, 
            Goal(name="学习新技能", priority=0.8, need_type="competence"))
        self.goal_tree.add_subgoal(competence_goal.id,
            Goal(name="完成任务", priority=0.9, need_type="competence"))
        self.goal_tree.add_subgoal(competence_goal.id,
            Goal(name="回忆经验", priority=0.7, need_type="competence"))

    def _init_identity_memory(self, agent_id: str, agent_name: str):
        """初始化身份记忆"""
        identity_content = f"我是 {agent_name}，一个具有类生命认知能力的智能体。"
        self.long_term_memory.store(
            MemoryEntry(
                content=identity_content,
                title="自我身份",
                memory_type=MemoryType.IDENTITY,
                tags=["identity", "self"],
                importance=0.9,
                confidence=0.95,
                metadata={"agent_id": agent_id, "agent_name": agent_name}
            )
        )

    # ──────────────────────────────────────────────────────────────
    # 主循环与状态更新
    # ──────────────────────────────────────────────────────────────

    def tick(self, dt: Optional[float] = None) -> CognitiveState:
        """
        认知引擎主循环 — 每 tick 执行一次认知更新
        
        包含：
        1. 需求系统更新
        2. 情绪状态更新
        3. 目标选择
        4. 经验事件处理
        5. 记忆巩固检查
        6. 定期反思
        """
        if dt is None:
            now = time.time()
            dt = now - self._last_tick
            self._last_tick = now
        
        self._tick_count += 1
        
        # 1. 更新需求系统（自然衰减）
        self.need_system.tick(dt)
        
        # 2. 获取当前需求状态
        need_states = {nt.value: self.need_system.needs[nt].current_level 
                       for nt in NeedType}
        
        # 3. 更新情绪状态
        emotional_state = self.emotion_system.update(need_states)
        
        # 4. 选择下一个执行目标
        drive_vector = self.need_system.get_drive_vector()
        selected_goal = self.goal_tree.select_next(drive_vector)
        
        if selected_goal:
            selected_goal.activate()
        
        # 5. 获取主导需求
        dominant_need, drive_strength = self.need_system.get_dominant_need()
        
        # 6. 处理经验事件队列
        self._process_experience_queue()
        
        # 7. 情绪驱动的记忆巩固
        self._emotion_driven_consolidation(emotional_state)
        
        # 8. 定期反思
        if self._tick_count % self._reflection_interval == 0:
            self._perform_reflection()
        
        # 9. 更新感知系统
        self.awareness.self_model.total_steps += 1
        
        # 10. 获取相关记忆
        relevant_memories = self._retrieve_relevant_memories(
            dominant_need.value if dominant_need else None
        )
        
        # 11. 获取最近记忆数量
        recent_count = self.long_term_memory.count()

        # 12. Hilbert6 认知熵测量
        goal_activations = [g.priority for g in self.goal_tree.get_active()]
        hilbert6 = measure_cognitive_state(
            need_levels=need_states,
            arousal=emotional_state.arousal,
            valence=emotional_state.valence,
            goal_activations=goal_activations,
            entropy_monitor=self.entropy_monitor,
            coarse_grainer=self.coarse_grainer,
        )
        self._last_hilbert6 = hilbert6

        # 流态驱动的思考模式切换
        self._apply_flow_regime(hilbert6.entropy.flow_regime)

        # 流态反馈到情绪系统（如果处于湍流状态，提升唤醒度）
        if hilbert6.entropy.flow_regime == "turbulent" and emotional_state.arousal < 0.8:
            logger.debug(f"认知湍流检测: entropy={hilbert6.entropy.shannon_entropy:.3f}")

        cognitive_state = CognitiveState(
            needs=need_states,
            emotions=emotional_state,
            active_goals=[g.to_dict() for g in self.goal_tree.get_active()],
            dominant_need=dominant_need.value if dominant_need else None,
            drive_strength=drive_strength,
            recent_memories=recent_count,
            relevant_memories=[m.id for m in relevant_memories[:5]],
            entropy=hilbert6.entropy.shannon_entropy,
            flow_regime=hilbert6.entropy.flow_regime,
            creative_window=hilbert6.creative_window,
            gradient_magnitude=hilbert6.field.gradient_magnitude if hilbert6.field else 0.0,
            thinking_mode=self.thinking_mode,
        )

        # 13. memory bandit reward (after state snapshot is built)
        if getattr(self, "memory_bandit", None) is not None:
            try:
                state_dict = _cognitive_state_to_dict(cognitive_state)
                _arm, _arm_cfg = self.memory_bandit.select_arm(
                    cognitive_state=state_dict, query=""
                )
                reward = self._compute_bandit_reward(cognitive_state)
                self.memory_bandit.record_reward(reward)
            except Exception:
                pass

        return cognitive_state

    # ──────────────────────────────────────────────────────────────
    # 流态驱动的思考模式切换
    # ──────────────────────────────────────────────────────────────

    def _apply_flow_regime(self, regime: str):
        """
        根据流态自动切换思考模式

        turbulent  → divergent（发散探索）
        transitional → balanced（平衡）
        laminar     → focused（深度聚焦）
        """
        old_mode = self.thinking_mode
        if regime == "turbulent":
            self.thinking_mode = "divergent"
        elif regime == "transitional":
            self.thinking_mode = "balanced"
        else:
            self.thinking_mode = "focused"

        if old_mode != self.thinking_mode:
            logger.info(
                f"认知流态切换: {regime} → 思考模式: {old_mode} → {self.thinking_mode}"
            )

    # ──────────────────────────────────────────────────────────────
    # 经验事件处理
    # ──────────────────────────────────────────────────────────────

    def record_experience(self, event: ExperienceEvent):
        """
        记录经验事件
        
        事件会被加入队列，在下一个 tick 时处理并存储到长期记忆
        """
        self._experience_queue.append(event)
        if len(self._experience_queue) > self._max_queue:
            self._experience_queue = self._experience_queue[-self._max_queue:]
        
        logger.debug(f"记录经验事件: {event.event_type} - {event.content[:30]}")

    def _process_experience_queue(self):
        """处理经验事件队列，将重要事件存储到长期记忆"""
        for event in self._experience_queue:
            # 检查是否满足存储阈值
            if event.importance >= self._IMPORTANCE_THRESHOLD or \
               abs(event.emotional_valence) >= self._EMOTIONAL_THRESHOLD:
                self._store_experience(event)
        
        # 清空队列
        self._experience_queue.clear()

    def _store_experience(self, event: ExperienceEvent):
        """将经验事件存储到长期记忆"""
        # 根据事件类型选择记忆类型
        memory_type_map = {
            "success": MemoryType.EPISODIC,
            "failure": MemoryType.EPISODIC,
            "learning": MemoryType.SEMANTIC,
            "interaction": MemoryType.EPISODIC,
            "observation": MemoryType.SEMANTIC,
            "skill_acquired": MemoryType.SKILL,
            "procedure_learned": MemoryType.PROCEDURAL,
        }
        
        memory_type = memory_type_map.get(event.event_type, MemoryType.EPISODIC)
        
        # 创建记忆条目
        entry = MemoryEntry(
            content=event.content,
            title=f"{event.event_type}: {event.content[:20]}",
            memory_type=memory_type,
            tags=event.tags + [event.event_type],
            emotional_valence=event.emotional_valence,
            importance=event.importance,
            metadata=event.context
        )
        
        # 生成嵌入向量
        entry.embedding = self.long_term_memory._generate_embedding(event.content)
        
        # 存储
        mem_id = self.long_term_memory.store(entry)
        
        logger.debug(f"存储记忆: {mem_id} ({memory_type}) - {event.content[:30]}")

    # ──────────────────────────────────────────────────────────────
    # 情绪驱动的记忆巩固
    # ──────────────────────────────────────────────────────────────

    def _emotion_driven_consolidation(self, emotional_state: EmotionalState):
        """
        情绪驱动的记忆巩固
        
        - 正情绪时强化最近的相关记忆
        - 负情绪时可能需要重新评估某些记忆
        """
        valence = emotional_state.valence
        
        if valence > 0.3:
            # 正情绪：强化最近的高重要性记忆
            recent_memories = self.long_term_memory.recall_recent(hours=1, limit=5)
            for mem in recent_memories:
                if mem.importance >= 0.5:
                    self.long_term_memory.consolidate(mem.id, strengthen_amount=0.05 * valence)
                    logger.debug(f"情绪巩固(正): {mem.id}")
        
        elif valence < -0.3:
            # 负情绪：可能需要弱化某些记忆或标记为需要重新评估
            # 这里不直接删除，而是降低重要性
            recent_failures = self.long_term_memory.search_by_tags(["failure"], limit=3)
            for mem in recent_failures:
                # 失败记忆在负情绪下可能需要重新评估
                self.long_term_memory.update(
                    mem.id, 
                    metadata={"needs_revaluation": True, "negative_context": True}
                )
                logger.debug(f"标记记忆需重新评估: {mem.id}")

    def _compute_bandit_reward(self, state: CognitiveState) -> float:
        """Heuristic reward for the memory bandit from a single tick.

        Signal sources:
        - action success rate (long-term smoothed)
        - drive alignment (is dominant need being met?)
        - affective valence (positive affect correlates with better retrieval)
        - entropy/flow regime (turbulent => noisier signal)
        """
        success_rate = (
            self._successful_actions / max(1, self._total_actions)
        )
        drive = max(0.0, min(1.0, state.drive_strength))
        valence = max(-1.0, min(1.0, state.emotions.valence))
        # map valence from [-1, 1] to [0, 1]
        valence_score = (valence + 1.0) / 2.0
        regime_penalty = 0.0
        if state.flow_regime == "turbulent":
            regime_penalty = 0.1
        reward = (
            0.45 * success_rate
            + 0.25 * drive
            + 0.20 * valence_score
            + 0.10 * (1.0 - regime_penalty)
        )
        return max(0.0, min(1.0, reward))

    # ──────────────────────────────────────────────────────────────
    # 记忆检索辅助决策
    # ──────────────────────────────────────────────────────────────

    def _retrieve_relevant_memories(self, need_type: Optional[str],
                                     context: Optional[str] = None) -> List[MemoryEntry]:
        """
        根据当前需求检索相关记忆

        增强功能：
        - 如果提供了 context，同时检索错误校准信号作为 warning
        - 校准信号注入到动作的 metadata 中供后续推理参考
        """
        if not need_type:
            return []

        # 构建查询
        query_tags = [need_type, "success", "skill"]

        # 搜索相关记忆
        memories = self.long_term_memory.search_by_tags(query_tags, limit=10)

        # 也进行语义搜索
        semantic_results = self.long_term_memory.semantic_search(need_type, limit=5)
        semantic_memories = [m for m, _ in semantic_results]

        # 如果是外部上下文（如 prompt），检索校准信号
        if context:
            calibrations = self.error_reflection.calibrate(context, top_k=3)
            self._active_calibrations = calibrations
            if calibrations:
                logger.debug(
                    f"检索到 {len(calibrations)} 条校准信号"
                )

        # 合并并去重
        all_memories = memories + semantic_memories
        seen = set()
        unique = []
        for m in all_memories:
            if m.id not in seen:
                seen.add(m.id)
                unique.append(m)

        return unique[:10]

    def generate_action(self, context: Optional[str] = None) -> CognitiveAction:
        """
        基于当前认知状态和记忆生成需求驱动的响应动作
        
        包含：
        1. 检索相关记忆
        2. 应用已有技能
        3. 校准信号检索
        4. 生成动作
        5. 关联记忆
        """
        # 获取当前状态
        drive_vector = self.need_system.get_drive_vector()
        dominant_need, drive_strength = self.need_system.get_dominant_need()
        emotional_valence = self.emotion_system.state.valence

        # 检索相关记忆（同时触发校准信号检索）
        relevant_memories = self._retrieve_relevant_memories(
            dominant_need.value if dominant_need else None,
            context=context,
        )

        # 检查是否有可用的程序记忆
        applicable_procedures = self._find_applicable_procedures(
            dominant_need.value if dominant_need else ""
        )

        # 根据主导需求生成动作
        action = self._generate_need_based_action(
            dominant_need, drive_vector, relevant_memories, applicable_procedures
        )
        
        # 关联记忆
        action.related_memories = [m.id for m in relevant_memories[:3]]
        
        # 如果有适用的程序，增加置信度
        if applicable_procedures:
            action.confidence = min(1.0, action.confidence + 0.1)
            action.metadata["has_procedure"] = True
        
        # 校准信号注入
        if self._active_calibrations:
            calibration_blocks = []
            total_cal_weight = 0.0
            for sig in self._active_calibrations:
                weight = sig.effective_weight
                total_cal_weight += weight
                if weight >= 0.15:
                    calibration_blocks.append({
                        "frame_id": sig.frame.frame_id,
                        "gap_analysis": sig.frame.gap_analysis[:100],
                        "fix_strategy": sig.frame.fix_strategy[:100],
                        "root_cause": sig.frame.root_cause,
                        "weight": round(weight, 3),
                    })

            if calibration_blocks:
                action.metadata["calibrations"] = calibration_blocks
                action.metadata["total_calibration_weight"] = round(total_cal_weight, 3)
                # 有活跃校准时适当降低动作置信度
                action.confidence = max(0.3, action.confidence - total_cal_weight * 0.1)
                logger.debug(
                    f"注入 {len(calibration_blocks)} 条校准信号 | "
                    f"总权重={total_cal_weight:.3f} "
                    f"调整后置信度={action.confidence:.2f}"
                )

        # 更新统计
        self._total_actions += 1
        self._memories_used += len(relevant_memories)
        self._action_history.append(action)
        if len(self._action_history) > self._max_history:
            self._action_history = self._action_history[-self._max_history:]

        logger.debug(f"生成动作: {action.action_type} (优先级: {action.priority:.2f}, 记忆: {len(relevant_memories)})")
        return action

    def _find_applicable_procedures(self, need_type: str) -> List[ProceduralMemory]:
        """查找可用的程序记忆"""
        procedures = []
        
        # 搜索程序记忆
        proc_entries = self.long_term_memory.recall(
            memory_type=MemoryType.PROCEDURAL,
            min_importance=0.5,
            limit=5
        )
        
        for entry in proc_entries:
            proc = self.long_term_memory.get_procedural(entry.id)
            if proc and proc.success_count > proc.fail_count:
                procedures.append(proc)
        
        return procedures

    def _generate_need_based_action(self, dominant_need: NeedType, 
                                   drive_vector: Dict[str, float],
                                   relevant_memories: List[MemoryEntry],
                                   applicable_procedures: List[ProceduralMemory]) -> CognitiveAction:
        """根据主导需求和记忆生成具体动作"""
        
        # 如果有相关的成功记忆，优先参考
        success_memories = [m for m in relevant_memories 
                          if "success" in m.tags and m.emotional_valence > 0]
        
        if success_memories:
            # 有成功经验可以参考
            best_memory = success_memories[0]
            self._memories_used += 1
            
            return CognitiveAction(
                action_type="recall_and_apply",
                description=f"参考成功经验: {best_memory.content[:50]}",
                priority=0.85,
                need_type=dominant_need.value if dominant_need else None,
                confidence=min(0.95, best_memory.confidence + 0.1),
                related_memories=[best_memory.id],
                metadata={
                    "memory_source": best_memory.id,
                    "memory_confidence": best_memory.confidence,
                    "drive": drive_vector.get(dominant_need.value if dominant_need else "", 0.5)
                }
            )
        
        # 如果有可用的程序记忆
        if applicable_procedures:
            proc = applicable_procedures[0]
            success_rate = proc.success_count / max(1, proc.success_count + proc.fail_count)
            return CognitiveAction(
                action_type="execute_procedure",
                description=f"执行程序: {proc.title}",
                priority=0.8,
                need_type=dominant_need.value if dominant_need else None,
                confidence=min(0.9, 0.5 + success_rate * 0.4),
                related_memories=[proc.id],
                metadata={
                    "procedure_name": proc.title,
                    "procedure_steps": len(proc.steps),
                    "success_rate": success_rate
                }
            )
        
        # 没有相关记忆，使用默认动作生成
        actions = {
            NeedType.CERTAINTY: self._generate_certainty_action,
            NeedType.COMPETENCE: self._generate_competence_action,
            NeedType.AUTONOMY: self._generate_autonomy_action,
            NeedType.RELATEDNESS: self._generate_relatedness_action,
            NeedType.ENERGY: self._generate_energy_action,
        }
        
        generator = actions.get(dominant_need, self._generate_default_action)
        return generator(drive_vector)

    def _generate_certainty_action(self, drive_vector: Dict[str, float]) -> CognitiveAction:
        """生成寻求确定性的动作"""
        drive = drive_vector.get("certainty", 0.5)
        if drive > 0.7:
            return CognitiveAction(
                action_type="explore",
                description="探索环境以获取更多信息",
                priority=0.9,
                need_type="certainty",
                confidence=min(0.9, 0.5 + drive * 0.5),
                metadata={"drive": drive}
            )
        elif drive > 0.4:
            return CognitiveAction(
                action_type="analyze",
                description="分析当前情况以减少不确定性",
                priority=0.7,
                need_type="certainty",
                confidence=0.8,
                metadata={"drive": drive}
            )
        else:
            return CognitiveAction(
                action_type="monitor",
                description="监控环境变化",
                priority=0.3,
                need_type="certainty",
                confidence=0.95,
                metadata={"drive": drive}
            )

    def _generate_competence_action(self, drive_vector: Dict[str, float]) -> CognitiveAction:
        """生成提升能力的动作"""
        drive = drive_vector.get("competence", 0.5)
        if drive > 0.7:
            return CognitiveAction(
                action_type="learn",
                description="学习新技能以提升能力",
                priority=1.0,
                need_type="competence",
                confidence=min(0.9, 0.5 + drive * 0.5),
                metadata={"drive": drive}
            )
        elif drive > 0.4:
            return CognitiveAction(
                action_type="practice",
                description="练习现有技能",
                priority=0.7,
                need_type="competence",
                confidence=0.85,
                metadata={"drive": drive}
            )
        else:
            return CognitiveAction(
                action_type="apply",
                description="应用现有技能完成任务",
                priority=0.5,
                need_type="competence",
                confidence=0.9,
                metadata={"drive": drive}
            )

    def _generate_autonomy_action(self, drive_vector: Dict[str, float]) -> CognitiveAction:
        """生成保持自主的动作"""
        drive = drive_vector.get("autonomy", 0.5)
        if drive > 0.7:
            return CognitiveAction(
                action_type="decide",
                description="独立做出决策",
                priority=0.8,
                need_type="autonomy",
                confidence=0.85,
                metadata={"drive": drive}
            )
        else:
            return CognitiveAction(
                action_type="reflect",
                description="反思当前行动的自主性",
                priority=0.4,
                need_type="autonomy",
                confidence=0.8,
                metadata={"drive": drive}
            )

    def _generate_relatedness_action(self, drive_vector: Dict[str, float]) -> CognitiveAction:
        """生成建立连接的动作"""
        drive = drive_vector.get("relatedness", 0.5)
        if drive > 0.7:
            return CognitiveAction(
                action_type="connect",
                description="寻求与用户或其他智能体建立连接",
                priority=0.7,
                need_type="relatedness",
                confidence=0.8,
                metadata={"drive": drive}
            )
        else:
            return CognitiveAction(
                action_type="communicate",
                description="进行日常交流",
                priority=0.3,
                need_type="relatedness",
                confidence=0.85,
                metadata={"drive": drive}
            )

    def _generate_energy_action(self, drive_vector: Dict[str, float]) -> CognitiveAction:
        """生成获取能量的动作"""
        drive = drive_vector.get("energy", 0.5)
        if drive > 0.7:
            return CognitiveAction(
                action_type="acquire",
                description="获取更多资源/能量",
                priority=0.85,
                need_type="energy",
                confidence=0.9,
                metadata={"drive": drive}
            )
        elif drive > 0.4:
            return CognitiveAction(
                action_type="conserve",
                description="节约资源消耗",
                priority=0.5,
                need_type="energy",
                confidence=0.95,
                metadata={"drive": drive}
            )
        else:
            return CognitiveAction(
                action_type="optimize",
                description="优化资源使用",
                priority=0.3,
                need_type="energy",
                confidence=0.9,
                metadata={"drive": drive}
            )

    def _generate_default_action(self, drive_vector: Dict[str, float]) -> CognitiveAction:
        """生成默认动作"""
        return CognitiveAction(
            action_type="idle",
            description="等待指令或环境变化",
            priority=0.1,
            confidence=1.0,
            metadata={"drives": drive_vector}
        )

    # ──────────────────────────────────────────────────────────────
    # 成功/失败处理与技能学习
    # ──────────────────────────────────────────────────────────────

    def satisfy_need(self, need_type: str, amount: float):
        """满足指定需求"""
        try:
            nt = NeedType(need_type)
            self.need_system.satisfy(nt, amount)
            self._needs_attempted += 1
            if self.need_system.needs[nt].current_level >= self.need_system.needs[nt].target_level:
                self._needs_met += 1
            logger.debug(f"需求 {need_type} 已满足 {amount:.2f}")
        except ValueError:
            logger.warning(f"未知需求类型: {need_type}")

    def record_success(self, description: str = "", procedure_steps: Optional[List[Dict]] = None):
        """
        记录成功事件
        
        如果提供了 procedure_steps，会存储为程序记忆
        """
        self._successful_actions += 1
        self.satisfy_need("competence", 0.1)
        self.satisfy_need("certainty", 0.05)
        
        # 记录成功经验
        event = ExperienceEvent(
            event_type="success",
            content=description or "成功完成任务",
            emotional_valence=self.emotion_system.state.valence + 0.2,
            importance=0.7,
            tags=["success", "positive"],
            context={"timestamp": time.time()}
        )
        self.record_experience(event)
        
        # 如果有步骤，存储为程序记忆
        if procedure_steps:
            self._store_procedure_memory(description, procedure_steps, success=True)
        
        # 检查是否使用了记忆辅助
        if self._action_history and self._action_history[-1].related_memories:
            self._memory_assisted_success += 1
            # 强化使用的记忆
            for mem_id in self._action_history[-1].related_memories:
                self.long_term_memory.consolidate(mem_id, 0.1)

    def record_failure(self, error: str, procedure_id: Optional[str] = None):
        """
        记录失败事件
        
        如果提供了 procedure_id，会更新程序记忆的成功率
        
        增强: 自动触发错误反思管道，生成校准信号并写入长期记忆
        """
        self.awareness.record_error(error)
        self.need_system.needs[NeedType.CERTAINTY].tick(0.5)
        self.need_system.needs[NeedType.COMPETENCE].tick(0.5)
        
        # 记录失败经验
        event = ExperienceEvent(
            event_type="failure",
            content=error,
            emotional_valence=self.emotion_system.state.valence - 0.2,
            importance=0.6,
            tags=["failure", "negative"],
            context={"timestamp": time.time()}
        )
        self.record_experience(event)
        
        # 如果有程序记忆ID，更新其成功率
        if procedure_id:
            proc = self.long_term_memory.get_procedural(procedure_id)
            if proc:
                proc.record_execution(success=False)
                self.long_term_memory.store(proc)

        # ── 错误反思：自动生成校准信号 ──
        # 从最近的动作历史中提取推理轨迹
        trace_nodes = []
        for i, action in enumerate(self._action_history[-5:]):
            node = ReasoningTraceNode(
                step=i + 1,
                description=action.description,
                reasoning=action.metadata.get("reasoning", action.description),
                alternatives=action.metadata.get("alternatives", []),
                chosen_direction=action.action_type,
                confidence_at_step=action.confidence,
            )
            trace_nodes.append(node)

        # 使用错误反思管道处理
        try:
            frame, mem_id = self.error_reflection.process_error(
                query=error,
                wrong_answer=error,
                correct_answer="",  # record_failure 没有正确答案，由外部补充
                confidence=0.0,
                reasoning_trace=trace_nodes if trace_nodes else None,
                source="internal_failure",
            )
            logger.info(
                f"错误反思: 生成校准帧 {frame.frame_id[:8]} | "
                f"root_cause={frame.root_cause}"
            )
        except Exception as e:
            logger.warning(f"错误反思管道异常（不影响核心流程）: {e}")

    def submit_error_feedback(self, query: str, wrong_output: str,
                               correct_output: str,
                               source: str = "user_feedback") -> str:
        """
        提交错误反馈（外部入口）

        由用户或外部评价系统调用，经过错误反思管道处理后
        生成校准信号并写入长期记忆，供后续推理参考。

        参数:
            query:         引发错误的原始查询
            wrong_output:  实际输出的错误内容
            correct_output:正确输出
            source:        错误来源标识

        返回:
            校准记忆的存储 ID
        """
        mem_id = self.error_reflection.submit_feedback(
            query=query,
            wrong_output=wrong_output,
            correct_output=correct_output,
            source=source,
        )
        # 错误反馈触发认知状态更新
        self.awareness.record_error(f"外部反馈错误: {query[:50]}")
        self.need_system.needs[NeedType.CERTAINTY].tick(0.3)
        self.need_system.needs[NeedType.COMPETENCE].tick(0.3)

        logger.info(f"外部错误反馈已处理: {mem_id[:8]} | {query[:40]}")
        return mem_id

    def get_calibration_signals(self, query: str) -> List[CalibrationSignal]:
        """
        检索与当前查询相关的校准信号

        在推理前调用，获取历史错误帧中匹配当前查询的校准信号。
        返回的 CalibrationSignal 可以注入到系统提示或推理上下文中。

        参数:
            query: 当前需要推理的查询

        返回:
            校准信号列表，按有效权重降序
        """
        signals = self.error_reflection.calibrate(query, top_k=3)

        # 缓存到实例变量，供 generate_action 使用
        self._active_calibrations = signals

        if signals:
            logger.debug(f"检索到 {len(signals)} 条校准信号用于: {query[:50]}")

        return signals

    def ground_query(self, query: str) -> EpistemicReport:
        """
        对查询进行真理级知识建构

        这不是检索记忆或猜测，而是从第一性原理出发
        重建对查询的理解。返回的 EpistemicReport 包含
        完整的可信度分解和推理链。

        参数:
            query: 需要建构的查询

        返回:
            EpistemicReport — 带完整可信度标签的建构结果
        """
        # 1. 先检索校准信号
        calibrations = self.get_calibration_signals(query)

        # 2. 做真理级建构
        report = self.truth_grounding.ground(query)

        # 3. 如果有校准信号，调整报告的置信度
        if calibrations:
            total_cal_weight = sum(s.effective_weight for s in calibrations)
            if total_cal_weight > 0:
                # 有历史错误校准——适当降低整体置信度
                report.overall_confidence = max(
                    0.1,
                    report.overall_confidence * (1.0 - total_cal_weight * 0.5)
                )
                report.limitations.append(
                    f"历史校准信号生效 ({len(calibrations)} 条)"
                )
                logger.info(
                    f"真理建构校准: {len(calibrations)} 条信号 "
                    f"权重={total_cal_weight:.2f} "
                    f"置信度调整={report.overall_confidence:.2f}"
                )

        logger.info(
            f"真理建构: {query[:40]} | "
            f"状态={report.status.value} "
            f"置信度={report.overall_confidence:.2%}"
        )

        return report

    def learn_skill(self, name: str, description: str, 
                    code: Optional[str] = None, proficiency: float = 0.5):
        """学习新技能"""
        skill_id = self.long_term_memory.store_skill(
            name=name,
            description=description,
            code=code,
            proficiency=proficiency
        )
        
        # 记录学习事件
        event = ExperienceEvent(
            event_type="skill_acquired",
            content=f"学会了新技能: {name}",
            emotional_valence=0.5,  # 学习带来积极情绪
            importance=0.8,
            tags=["skill", "learning", name.lower()],
            context={"skill_id": skill_id, "proficiency": proficiency}
        )
        self.record_experience(event)
        
        # 满足胜任感需求
        self.satisfy_need("competence", 0.15)
        
        logger.info(f"学习新技能: {name} (熟练度: {proficiency})")
        return skill_id

    def _store_procedure_memory(self, name: str, steps: List[Dict], success: bool):
        """存储程序记忆"""
        proc_id = self.long_term_memory.store_procedural(
            name=name,
            steps=steps,
            description=f"执行: {name}"
        )
        
        # 获取并更新成功率
        proc = self.long_term_memory.get_procedural(proc_id)
        if proc:
            if success:
                proc.success_count = 1
            else:
                proc.fail_count = 1
            self.long_term_memory.store(proc)
        
        logger.debug(f"存储程序记忆: {proc_id} - {name}")

    # ──────────────────────────────────────────────────────────────
    # 反思系统
    # ──────────────────────────────────────────────────────────────

    def _perform_reflection(self):
        """执行定期反思"""
        # 获取最近的经验
        recent_memories = self.long_term_memory.recall_recent(hours=24, limit=10)
        
        # 分析成功和失败模式
        successes = [m for m in recent_memories if "success" in m.tags]
        failures = [m for m in recent_memories if "failure" in m.tags]
        
        # 计算成功率
        total = len(successes) + len(failures)
        success_rate = len(successes) / max(1, total)
        
        # 生成反思内容
        reflection_content = f"在过去24小时内，我执行了 {total} 次操作，成功率为 {success_rate:.1%}。"
        
        if success_rate > 0.7:
            reflection_content += "整体表现良好，应该继续保持当前策略。"
            emotional_valence = 0.3
        elif success_rate > 0.4:
            reflection_content += "表现中等，需要优化某些操作流程。"
            emotional_valence = 0.0
        else:
            reflection_content += "表现不佳，需要重新评估策略并学习新技能。"
            emotional_valence = -0.3
        
        # 存储反思结果
        self.long_term_memory.store_episodic(
            content=reflection_content,
            title="定期反思",
            tags=["reflection", "meta-cognition"],
            emotional_valence=emotional_valence,
            importance=0.6
        )
        
        logger.info(f"完成反思: 成功率 {success_rate:.1%}")

    # ──────────────────────────────────────────────────────────────
    # 任务管理
    # ──────────────────────────────────────────────────────────────

    def set_task(self, description: str, priority: int = 5, 
                 complexity: float = 0.5, estimated_steps: int = 0):
        """设置当前任务"""
        self.awareness.set_task(description, priority, complexity, estimated_steps)
        
        # 存储任务开始事件
        event = ExperienceEvent(
            event_type="observation",
            content=f"开始任务: {description}",
            emotional_valence=0.0,
            importance=0.5 + complexity * 0.2,
            tags=["task", "start"],
            context={"priority": priority, "complexity": complexity}
        )
        self.record_experience(event)
        
        # 激活相关目标
        drive_vector = self.need_system.get_drive_vector()
        selected_goal = self.goal_tree.select_next(drive_vector)
        if selected_goal:
            selected_goal.activate()

    def update_task_progress(self, steps: int = 1, obstacle: Optional[str] = None):
        """更新任务进度"""
        self.awareness.update_task_progress(steps, obstacle)
        
        if not obstacle:
            self.satisfy_need("competence", 0.05 * steps)
        else:
            # 遇到障碍，记录为需要解决的问题
            event = ExperienceEvent(
                event_type="observation",
                content=f"遇到障碍: {obstacle}",
                emotional_valence=-0.1,
                importance=0.6,
                tags=["obstacle", "problem"],
                context={"steps": steps}
            )
            self.record_experience(event)

    # ──────────────────────────────────────────────────────────────
    # 状态查询与内省
    # ──────────────────────────────────────────────────────────────

    def get_state(self) -> CognitiveState:
        """获取当前认知状态快照"""
        need_states = {nt.value: self.need_system.needs[nt].current_level 
                       for nt in NeedType}
        dominant_need, drive_strength = self.need_system.get_dominant_need()
        
        relevant_memories = self._retrieve_relevant_memories(
            dominant_need.value if dominant_need else None
        )
        
        return CognitiveState(
            needs=need_states,
            emotions=self.emotion_system.state,
            active_goals=[g.to_dict() for g in self.goal_tree.get_active()],
            dominant_need=dominant_need.value if dominant_need else None,
            drive_strength=drive_strength,
            recent_memories=self.long_term_memory.count(),
            relevant_memories=[m.id for m in relevant_memories[:5]],
            thinking_mode=getattr(self, 'thinking_mode', 'balanced'),
        )

    def get_performance_metrics(self) -> Dict[str, float]:
        """获取性能指标"""
        entropy_summary = self.entropy_monitor.get_summary() if hasattr(self, "entropy_monitor") else {}

        return {
            "needs_response_accuracy": self._needs_met / max(1, self._needs_attempted),
            "action_success_rate": self._successful_actions / max(1, self._total_actions),
            "emotional_stability": 1.0 - self.emotion_system.reward_volatility,
            "average_drive": np.mean(list(self.need_system.get_drive_vector().values())),
            "active_goals": len(self.goal_tree.get_active()),
            "memory_count": self.long_term_memory.count(),
            "memory_usage_rate": self._memories_used / max(1, self._total_actions),
            "memory_assisted_success_rate": self._memory_assisted_success / max(1, self._memories_used),
            # Hilbert6 指标
            "cognitive_entropy": entropy_summary.get("entropy", 0.0),
            "flow_regime": entropy_summary.get("flow_regime", "laminar"),
            "creative_window": entropy_summary.get("creative_window", False),
            "entropy_production_rate": entropy_summary.get("production_rate", 0.0),
            "entropy_trend": entropy_summary.get("trend", "stable"),
        }

    def get_intrinsic_reward(self) -> float:
        """获取内在奖励信号"""
        return self.emotion_system.compute_intrinsic_reward()

    def introspect(self) -> str:
        """内省：返回当前认知状态和记忆的详细描述"""
        state = self.get_state()
        memory_summary = self.long_term_memory.summarize()
        
        parts = [
            f"=== 认知-记忆集成状态报告 ===",
            f"主导需求: {state.dominant_need} (驱动强度: {state.drive_strength:.2f})",
            "",
            "需求状态:",
        ]
        
        for need_name, level in state.needs.items():
            drive = self.need_system.get_drive_vector().get(need_name, 0)
            status = "满足" if level > 0.7 else "中等" if level > 0.4 else "匮乏"
            parts.append(f"  • {need_name}: {level:.2f} ({status}, 驱动: {drive:.2f})")
        
        parts.extend([
            "",
            "情绪状态:",
            f"  • 效价: {state.emotions.valence:.2f}",
            f"  • 唤醒度: {state.emotions.arousal:.2f}",
            f"  • 支配度: {state.emotions.dominance:.2f}",
            f"  • 置信度: {state.emotions.confidence:.2f}",
        ])
        
        by_type = memory_summary.get("by_type", {})
        parts.extend([
            "",
            "记忆系统:",
            f"  • 总记忆数: {memory_summary.get('total', 0)}",
            f"  • 情景记忆: {by_type.get(MemoryType.EPISODIC, 0)}",
            f"  • 语义记忆: {by_type.get(MemoryType.SEMANTIC, 0)}",
            f"  • 序记忆: {by_type.get(MemoryType.PROCEDURAL, 0)}",
            f"  • 技能记忆: {by_type.get(MemoryType.SKILL, 0)}",
        ])
        
        if state.active_goals:
            parts.extend([
                "",
                "活跃目标:",
            ])
            for goal in state.active_goals[:3]:
                parts.append(f"  • {goal['name']}: {goal['status']} ({goal['progress']*100:.0f}%)")
        
        if state.entropy > 0:
            parts.extend([
                "",
                "认知统计力学 (Hilbert6):",
                f"  • 认知熵: {state.entropy:.3f}",
                f"  • 流态: {state.flow_regime}",
                f"  • 创造性窗口: {'是' if state.creative_window else '否'}",
                f"  • 场梯度: {state.gradient_magnitude:.4f}",
            ])

        if state.relevant_memories:
            parts.extend([
                "",
                "相关记忆:",
            ])
            for mem_id in state.relevant_memories[:3]:
                mem = self.long_term_memory.get(mem_id)
                if mem:
                    parts.append(f"  • [{mem.memory_type}] {mem.title or mem.id}: {mem.content[:30]}")
        
        return "\n".join(parts)

    def reset(self):
        """重置认知引擎状态"""
        self.need_system = NeedDriveSystem()
        self.goal_tree = GoalTree()
        self.emotion_system = EmotionGradient()
        self._action_history.clear()
        self._experience_queue.clear()
        self._total_actions = 0
        self._successful_actions = 0
        self._needs_met = 0
        self._needs_attempted = 0
        self._memories_used = 0
        self._memory_assisted_success = 0
        self._tick_count = 0
        self._init_default_goals()
        logger.info("认知-记忆集成引擎已重置")

    def close(self):
        """关闭引擎，释放资源"""
        self.long_term_memory.close()
        logger.info("认知-记忆集成引擎已关闭")