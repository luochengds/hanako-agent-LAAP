"""
LAAP — Phase 1 基础认知引擎

这是 LAAP 类生命智能体的核心认知引擎，整合：
1. PSI 需求驱动系统
2. 目标层级系统
3. 情绪梯度系统
4. 自我/环境感知系统

Phase 1 验证指标：需求驱动响应准确率 > 80%
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple
import time
import numpy as np
import logging

from laap.cognition.needs import NeedDriveSystem, NeedType
from laap.cognition.goals import GoalTree, Goal, GoalStatus
from laap.cognition.emotion import EmotionGradient, EmotionalState
from laap.cognition.awareness import AwarenessSystem
from laap.cognition.entropy import (
    CognitiveEntropyMonitor, CoarseGrainer, measure_cognitive_state,
    Hilbert6Metrics
)

logger = logging.getLogger("laap.cognition.engine")


@dataclass
class CognitiveAction:
    """认知动作 — 由认知引擎产生的响应"""
    action_type: str
    description: str
    priority: float
    need_type: Optional[str] = None
    confidence: float = 0.7
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CognitiveState:
    """认知状态快照"""
    needs: Dict[str, float]
    emotions: EmotionalState
    active_goals: List[Dict]
    dominant_need: Optional[str]
    drive_strength: float
    entropy: float = 0.0
    flow_regime: str = "laminar"
    creative_window: bool = False
    gradient_magnitude: float = 0.0
    thinking_mode: str = "balanced"
    timestamp: float = field(default_factory=time.perf_counter)


class CognitiveEngine:
    """
    LAAP 认知引擎 — Phase 1 基础框架
    
    核心功能：
    1. 持续监控五大 PSI 需求状态
    2. 基于需求驱动生成和选择目标
    3. 情绪梯度计算（内在奖励信号）
    4. 自我感知与环境感知整合
    5. 生成需求驱动的响应动作
    """

    def __init__(self, agent_id: str = "", agent_name: str = "LAAP"):
        # 核心组件初始化
        self.need_system = NeedDriveSystem()
        self.goal_tree = GoalTree()
        self.emotion_system = EmotionGradient()
        self.awareness = AwarenessSystem(agent_id, agent_name)
        
        # 状态追踪
        self._tick_interval = 1.0  # 每秒更新一次
        self._last_tick = time.time()
        self._action_history: List[CognitiveAction] = []
        self._max_history = 100
        
        # Hilbert6 认知熵系统
        self.entropy_monitor = CognitiveEntropyMonitor(window_size=20)
        self.coarse_grainer = CoarseGrainer(grid_resolution=8)
        self._last_hilbert6: Optional[Hilbert6Metrics] = None
        self.thinking_mode: str = "balanced"  # focused | balanced | divergent

        # 性能指标
        self._total_actions = 0
        self._successful_actions = 0
        self._needs_met = 0
        self._needs_attempted = 0
        
        # 初始化默认目标树
        self._init_default_goals()
        
        logger.info(f"[{agent_name}] 认知引擎初始化完成")

    def _init_default_goals(self):
        """初始化默认的需求驱动目标树"""
        root = Goal(name="生存与成长", priority=1.0)
        self.goal_tree.set_root(root)
        
        # 为每个需求创建子目标
        need_goals = [
            Goal(name="寻求确定性", priority=0.9, need_type="certainty"),
            Goal(name="提升能力", priority=1.0, need_type="competence"),
            Goal(name="保持自主", priority=0.7, need_type="autonomy"),
            Goal(name="建立连接", priority=0.6, need_type="relatedness"),
            Goal(name="获取能量", priority=0.8, need_type="energy"),
        ]
        
        for goal in need_goals:
            self.goal_tree.add_subgoal(root.id, goal)
        
        # 为能力目标添加子目标（示例）
        competence_goal = need_goals[1]
        self.goal_tree.add_subgoal(competence_goal.id, 
            Goal(name="学习新技能", priority=0.8, need_type="competence"))
        self.goal_tree.add_subgoal(competence_goal.id,
            Goal(name="完成任务", priority=0.9, need_type="competence"))

    def tick(self, dt: Optional[float] = None) -> CognitiveState:
        """
        认知引擎主循环 — 每 tick 执行一次认知更新
        
        返回当前认知状态快照
        """
        if dt is None:
            now = time.time()
            dt = now - self._last_tick
            self._last_tick = now
        
        # 更新需求系统（自然衰减）
        self.need_system.tick(dt)
        
        # 获取当前需求状态
        need_states = {nt.value: self.need_system.needs[nt].current_level 
                       for nt in NeedType}
        
        # 更新情绪状态
        emotional_state = self.emotion_system.update(need_states)
        
        # 选择下一个执行目标
        drive_vector = self.need_system.get_drive_vector()
        selected_goal = self.goal_tree.select_next(drive_vector)
        
        if selected_goal:
            selected_goal.activate()
        
        # 获取主导需求
        dominant_need, drive_strength = self.need_system.get_dominant_need()
        
        # 更新感知系统
        self.awareness.self_model.total_steps += 1

        # Hilbert6 认知熵测量
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
        
        return CognitiveState(
            needs=need_states,
            emotions=emotional_state,
            active_goals=[g.to_dict() for g in self.goal_tree.get_active()],
            dominant_need=dominant_need.value if dominant_need else None,
            drive_strength=drive_strength,
            entropy=hilbert6.entropy.shannon_entropy,
            flow_regime=hilbert6.entropy.flow_regime,
            creative_window=hilbert6.creative_window,
            gradient_magnitude=hilbert6.field.gradient_magnitude if hilbert6.field else 0.0,
            thinking_mode=self.thinking_mode,
        )

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

    def generate_action(self, context: Optional[str] = None) -> CognitiveAction:
        """
        基于当前认知状态生成需求驱动的响应动作

        思考模式影响：
          - focused:   高置信度，高确定性动作优先
          - balanced:  正常选择
          - divergent: 低置信度，探索性动作优先
        
        返回：带有优先级和置信度的认知动作
        """
        # 获取当前状态
        drive_vector = self.need_system.get_drive_vector()
        dominant_need, drive_strength = self.need_system.get_dominant_need()
        emotional_valence = self.need_system.emotional_valence
        
        # 根据主导需求生成动作
        action = self._generate_need_based_action(dominant_need, drive_vector)
        
        # 思考模式调制：divergent 模式降低置信度，focused 提升置信度
        if self.thinking_mode == "divergent":
            # 发散模式：降低置信度，鼓励探索
            action.confidence = max(0.3, action.confidence - 0.2)
            # 把优先级往探索性方向偏
            if action.action_type in ("apply", "monitor", "conserve"):
                action.priority *= 0.7
        elif self.thinking_mode == "focused":
            # 聚焦模式：提升置信度，鼓励深入
            action.confidence = min(0.98, action.confidence + 0.15)
            if action.action_type in ("explore", "learn"):
                action.priority *= 0.8
        
        # 更新统计
        self._total_actions += 1
        self._action_history.append(action)
        if len(self._action_history) > self._max_history:
            self._action_history = self._action_history[-self._max_history:]
        
        logger.debug(f"生成动作: {action.action_type} (优先级: {action.priority:.2f})")
        return action

    def _generate_need_based_action(self, dominant_need: NeedType, 
                                   drive_vector: Dict[str, float]) -> CognitiveAction:
        """根据主导需求生成具体动作"""
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

    def satisfy_need(self, need_type: str, amount: float):
        """
        满足指定需求
        
        参数:
            need_type: 需求类型名称 (certainty/competence/autonomy/relatedness/energy)
            amount: 满足量 (0.0-1.0)
        """
        try:
            nt = NeedType(need_type)
            self.need_system.satisfy(nt, amount)
            self._needs_attempted += 1
            if self.need_system.needs[nt].current_level >= self.need_system.needs[nt].target_level:
                self._needs_met += 1
            logger.debug(f"需求 {need_type} 已满足 {amount:.2f}")
        except ValueError:
            logger.warning(f"未知需求类型: {need_type}")

    def set_task(self, description: str, priority: int = 5, 
                 complexity: float = 0.5, estimated_steps: int = 0):
        """设置当前任务"""
        self.awareness.set_task(description, priority, complexity, estimated_steps)
        
        # 激活相关目标
        drive_vector = self.need_system.get_drive_vector()
        selected_goal = self.goal_tree.select_next(drive_vector)
        if selected_goal:
            selected_goal.activate()

    def update_task_progress(self, steps: int = 1, obstacle: Optional[str] = None):
        """更新任务进度"""
        self.awareness.update_task_progress(steps, obstacle)
        
        # 如果任务进展，提升胜任感需求
        if not obstacle:
            self.satisfy_need("competence", 0.05 * steps)

    def record_success(self):
        """记录成功事件"""
        self._successful_actions += 1
        self.satisfy_need("competence", 0.1)
        self.satisfy_need("certainty", 0.05)

    def record_failure(self, error: str):
        """记录失败事件"""
        self.awareness.record_error(error)
        # 失败会降低确定性和胜任感
        self.need_system.needs[NeedType.CERTAINTY].tick(0.5)
        self.need_system.needs[NeedType.COMPETENCE].tick(0.5)

    def get_state(self) -> CognitiveState:
        """获取当前认知状态快照（含熵信息）"""
        need_states = {nt.value: self.need_system.needs[nt].current_level 
                       for nt in NeedType}
        dominant_need, drive_strength = self.need_system.get_dominant_need()

        # 用缓存的 Hilbert6 数据或即时计算
        hilbert6 = self._last_hilbert6
        if hilbert6 is None:
            hilbert6 = measure_cognitive_state(
                need_levels=need_states,
                arousal=self.emotion_system.state.arousal,
                valence=self.emotion_system.state.valence,
                entropy_monitor=self.entropy_monitor,
                coarse_grainer=self.coarse_grainer,
            )
        
        return CognitiveState(
            needs=need_states,
            emotions=self.emotion_system.state,
            active_goals=[g.to_dict() for g in self.goal_tree.get_active()],
            dominant_need=dominant_need.value if dominant_need else None,
            drive_strength=drive_strength,
            entropy=hilbert6.entropy.shannon_entropy,
            flow_regime=hilbert6.entropy.flow_regime,
            creative_window=hilbert6.creative_window,
            gradient_magnitude=hilbert6.field.gradient_magnitude if hilbert6.field else 0.0,
            thinking_mode=self.thinking_mode,
        )

    def get_performance_metrics(self) -> Dict[str, float]:
        """获取性能指标（含 Hilbert6 认知熵）"""
        entropy_summary = self.entropy_monitor.get_summary() if hasattr(self, "entropy_monitor") else {}
        return {
            "needs_response_accuracy": self._needs_met / max(1, self._needs_attempted),
            "action_success_rate": self._successful_actions / max(1, self._total_actions),
            "emotional_stability": 1.0 - self.emotion_system.reward_volatility,
            "average_drive": np.mean(list(self.need_system.get_drive_vector().values())),
            "active_goals": len(self.goal_tree.get_active()),
            # Hilbert6 指标
            "cognitive_entropy": entropy_summary.get("entropy", 0.0),
            "flow_regime": entropy_summary.get("flow_regime", "laminar"),
            "creative_window": entropy_summary.get("creative_window", False),
            "entropy_production_rate": entropy_summary.get("production_rate", 0.0),
            "entropy_trend": entropy_summary.get("trend", "stable"),
        }

    def get_intrinsic_reward(self) -> float:
        """获取内在奖励信号（用于学习）"""
        return self.emotion_system.compute_intrinsic_reward()

    def introspect(self) -> str:
        """内省：返回当前认知状态的自然语言描述"""
        state = self.get_state()
        parts = [
            f"=== 认知状态报告 ===",
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

        if state.entropy > 0:
            parts.extend([
                "",
                "认知统计力学 (Hilbert6):",
                f"  • 认知熵: {state.entropy:.3f}",
                f"  • 流态: {state.flow_regime}",
                f"  • 思考模式: {state.thinking_mode}",
                f"  • 创造性窗口: {'是' if state.creative_window else '否'}",
                f"  • 场梯度: {state.gradient_magnitude:.4f}",
            ])
        
        if state.active_goals:
            parts.extend([
                "",
                "活跃目标:",
            ])
            for goal in state.active_goals[:3]:
                parts.append(f"  • {goal['name']}: {goal['status']} ({goal['progress']*100:.0f}%)")
        
        return "\n".join(parts)

    def reset(self):
        """重置认知引擎状态"""
        self.need_system = NeedDriveSystem()
        self.goal_tree = GoalTree()
        self.emotion_system = EmotionGradient()
        self._action_history.clear()
        self._total_actions = 0
        self._successful_actions = 0
        self._needs_met = 0
        self._needs_attempted = 0
        self._init_default_goals()
        logger.info("认知引擎已重置")
