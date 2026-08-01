"""
LAAP — LifelikeAgent v2.0：AGI 级类生命意识 Agent

DEPRECATED — 本模块已废弃
=========================
废弃原因：Agent 对外入口已统一至 laap.agent_core.agent.Agent(mode="agi")；
         LifelikeAgent 的功能将逐步迁移到 agent_core/ 下的统一实现。
替代实现：from laap.agent_core.agent import Agent; Agent(mode="agi")
废弃时间：2026-07-11
登记位置：legacy/INDEX.md

代码保留目的：保持向后兼容，历史导入与类名继续可用；
             新功能开发请使用 agent_core/agent.py 的统一 Agent 入口。

融合 PSI 认知架构的"有意识"Agent：
  - 内在需求驱动行为
  - 情绪从需求满足中涌现
  - 自我感知与环境感知
  - LLM 作为"思考皮层"
  - RSI 作为"进化引擎"
  - **元认知**作为"自我意识"（新增v2.0）
  - **议会系统**作为"内部对话"（新增v2.0）
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import logging, numpy as np, time

from laap.agent.base import Agent, AgentConfig
from laap.cognition.needs import NeedDriveSystem, NeedType
from laap.cognition.emotion import EmotionGradient
from laap.cognition.emotion_system import ComprehensiveEmotionSystem
from laap.cognition.goals import GoalTree, Goal, GoalStatus
from laap.evolution.rsi import RSIEngine, ImprovementProposal
from laap.evaluation.fitness import FitnessEvaluator
from laap.agent.meta_cognition import MetaCognitionEngine, ThinkingMode
from laap.agent.parliament import Parliament

logger = logging.getLogger("laap.agent.lifelike")


@dataclass
class LifelikeConfig(AgentConfig):
    need_config: Optional[Dict[str, dict]] = None
    rsi_enabled: bool = True
    rsi_interval: int = 20
    reflection_interval: int = 10
    # v2.0 增强
    enable_comprehensive_emotion: bool = True  # 使用综合情感系统
    emotion_sync_interval: int = 3            # 情感同步到元认知的间隔


class LifelikeAgent(Agent):
    """具有 PSI 认知架构的 AGI 级类生命 Agent v2.0"""

    def __init__(self, config: Optional[LifelikeConfig] = None,
                 llm_factory=None, show_banner: Optional[bool] = None):
        super().__init__(config or LifelikeConfig(), llm_factory,
                         show_banner=show_banner)
        self.config: LifelikeConfig = self.config  # type hint

        # ── PSI 子系统 ──
        self.needs = NeedDriveSystem(self.config.need_config)
        self.emotion_gradient = EmotionGradient()
        self.goals = GoalTree()

        # ── 综合情感系统（v2.0） ──
        self.comprehensive_emotion = ComprehensiveEmotionSystem()
        self._emotion_sync_counter = 0

        # ── RSI 引擎 ──
        self.rsi = RSIEngine(
            proposal_interval=self.config.rsi_interval,
        ) if self.config.rsi_enabled else None

        # ── 评估器 ──
        self.evaluator = FitnessEvaluator()

        # ── 内部状态 ──
        self.current_action: Optional[str] = None
        self._action_history: List[str] = []
        self._reward_history: List[float] = []
        self._need_history: List[Dict[str, float]] = []

        # ── 注册类生命默认动作 ──
        self._register_life_actions()

        logger.info(
            f"LifelikeAgent v2.0 [{self.id[:8]}] "
            f"PSI 认知引擎 + 元认知 + 议会 已启动"
        )

    def _register_life_actions(self):
        """注册类生命的本能动作（v2.0增强版）"""
        self.register_tool("explore", self._act_explore, "探索环境，发现新信息")
        self.register_tool("analyze", self._act_analyze, "分析已有信息，提取模式")
        self.register_tool("reflect", self._act_reflect, "反思自身，提升元认知")
        self.register_tool("rest", self._act_rest, "休息，恢复能量")
        # v2.0 新增高级认知动作
        self.register_tool("deliberate", self._act_deliberate, 
                          "启动议会审议，多视角决策")
        self.register_tool("meta_reflect", self._act_meta_reflect,
                          "元认知反思，分析自己的思考过程")
        self.register_tool("learn_skill", self._act_learn_skill,
                          "从经验中学习新的认知策略")

    def _act_explore(self, target: str = "") -> str:
        self.needs.satisfy(NeedType.CERTAINTY, 0.05)
        self._trigger_emotion("novelty", 0.4, f"探索 {target}")
        return f"探索 {target or '环境'}，收集到新信号"

    def _act_analyze(self, data: str = "") -> str:
        self.needs.satisfy(NeedType.CERTAINTY, 0.08)
        self.needs.satisfy(NeedType.COMPETENCE, 0.06)
        self._trigger_emotion("need_satisfied", 0.3, "分析完成")
        return f"分析完成: {data or '数据'}中存在结构模式"

    def _act_reflect(self, topic: str = "") -> str:
        self.needs.satisfy(NeedType.AUTONOMY, 0.05)
        self.needs.satisfy(NeedType.COMPETENCE, 0.04)
        self._trigger_emotion("reflection", 0.3, f"反思 {topic}")
        return f"关于 {topic or '自我'}的反思: 理解了新的关联"

    def _act_rest(self, duration: int = 1) -> str:
        self.needs.satisfy(NeedType.ENERGY, 0.1)
        return f"休息 {duration} 回合，能量恢复"

    def _act_deliberate(self, topic: str = "") -> str:
        """启动议会审议"""
        if not self.config.enable_parliament:
            return "议会系统未启用"
        deliberation = self.parliament.deliberate(
            topic=topic or "当前决策",
            context=f"step={self.step_count}",
        )
        result = f"议会审议完成: {deliberation.final_decision} (置信度={deliberation.decision_confidence:.2f})"
        self._trigger_emotion("need_satisfied", 0.3, "议会审议")
        return result

    def _act_meta_reflect(self, topic: str = "") -> str:
        """元认知反思"""
        if not self.config.enable_meta_cognition:
            return "元认知系统未启用"
        reflection = self.meta_cognition.perform_reflection()
        insight = reflection.get("patterns", ["无显著模式"])
        return f"元认知反思: 平均结果={reflection['average_outcome']:.2f}, 模式={insight[:3]}"

    def _act_learn_skill(self, skill_name: str = "", 
                         description: str = "") -> str:
        """从经验中学习新策略"""
        from laap.agent.meta_cognition import CognitiveStrategy
        if not skill_name:
            return "请提供技能名称"
        strategy = CognitiveStrategy(
            name=skill_name,
            description=description or f"从经验习得的策略: {skill_name}",
            task_types=["custom"],
            thinking_mode="deliberate",
        )
        self.meta_cognition.strategies[skill_name] = strategy
        return f"已学习新认知策略: {skill_name}"

    def _trigger_emotion(self, event_type: str, intensity: float,
                         context: str = ""):
        """触发综合情感系统"""
        try:
            self.comprehensive_emotion.trigger(event_type, intensity, context)
        except Exception:
            pass

    # ═══════════════════════════════════════════════════════
    # 核心认知循环 (v2.0 增强版)
    # ═══════════════════════════════════════════════════════

    def step(self, observation: str, task_success: Optional[float] = None,
             tags: Optional[List[str]] = None) -> dict:
        """执行一步完整的认知循环：感知 -> 评估 -> 行动 -> 元认知 -> 学习 -> 反思"""
        if not self.alive:
            return {"status": "dead", "step": self.step_count}

        self.step_count += 1
        t_start = time.time()

        # ── 1. 感知 ──
        self.memory.perceive(observation, tags, importance=0.5)
        self.memory.remember(observation, tags, importance=0.3)

        # ── 2. 需求评估与情绪更新 ──
        drives = self.needs.tick()
        self._need_history.append(
            {nt.value: self.needs.needs[nt].current_level 
             for nt in self.needs.needs}
        )

        deltas = {}
        if len(self._need_history) >= 2:
            for nt in self.needs.needs:
                k = nt.value
                deltas[k] = self._need_history[-1][k] - self._need_history[-2][k]

        satisfactions = {
            nt.value: self.needs.needs[nt].current_level 
            for nt in self.needs.needs
        }

        # ── 2b. 综合情感更新 ──
        self._emotion_sync_counter += 1
        if self._emotion_sync_counter >= self.config.emotion_sync_interval:
            self.comprehensive_emotion.tick()
            self._emotion_sync_counter = 0

        # 需求触发情感
        dominant_need, drive_str = self.needs.get_dominant_need()
        if dominant_need and self.needs.needs[dominant_need].current_level < 0.3:
            self._trigger_emotion("need_frustrated", 0.3,
                                  f"需求{dominant_need.value}匮乏")

        # ── 3. 情绪计算（梯度 + 综合） ──
        emotional_state = self.emotion_gradient.update(
            satisfactions, task_success=task_success
        )
        intrinsic_reward = self.emotion_gradient.compute_intrinsic_reward()
        self._reward_history.append(intrinsic_reward)

        # ── 4. 元认知：决策前分析 ──
        if self.config.enable_meta_cognition:
            meta_rec = self.meta_cognition.before_decision(
                observation,
                {
                    "step": self.step_count,
                    "dominant_need": dominant_need.value if dominant_need else None,
                    "reward": intrinsic_reward,
                },
            )
        else:
            meta_rec = {}

        # ── 5. 行动选择（需求驱动 + 元认知引导） ──
        action_selection = self._select_action(
            meta_strategy=meta_rec.get("strategy") if meta_rec else None,
        )
        if action_selection:
            if isinstance(action_selection, tuple):
                action, action_kwargs = action_selection
            else:
                action, action_kwargs = action_selection, {}
            logger.info(
                f"[LifelikeAgent] step: selected action={action} "
                f"kwargs={list(action_kwargs.keys())} step={self.step_count}"
            )
            result = self.execute_action(action, **action_kwargs)
            self.current_action = action
            self._action_history.append(action)
        else:
            result = None
            action = None

        # ── 6. 学习（满足需求） ──
        self._satisfy_needs_from_action(action, task_success)

        # ── 7. 元认知：决策后记录 ──
        if self.config.enable_meta_cognition and action:
            self.meta_cognition.after_decision(
                {
                    "task": observation[:60],
                    "selected": action,
                    "confidence": 0.6,
                    "duration_ms": (time.time() - t_start) * 1000,
                },
                outcome={
                    "score": intrinsic_reward if intrinsic_reward else 0.5,
                },
            )

        # ── 8. (可选) 自我反思 ──
        reflection = None
        if self.step_count % self.config.reflection_interval == 0:
            reflection = self._self_reflect()
            # 元认知反思
            if self.config.enable_meta_cognition:
                self.meta_cognition.perform_reflection()

        # ── 9. (可选) RSI 自我改进 ──
        rsi_result = None
        if self.rsi and self.step_count % 5 == 0:
            rsi_result = self.rsi.step(self, force=(self.step_count % 20 == 0))

        # ── 10. 综合情感状态更新 ──
        emotion_summary = self.comprehensive_emotion.get_emotion_summary() if \
            self.config.enable_comprehensive_emotion else None

        return {
            "step": self.step_count,
            "action": action,
            "action_result": str(result)[:100] if result else None,
            "emotional_state": emotional_state.to_dict(),
            "emotion_summary": emotion_summary,
            "dominant_need": dominant_need.value if dominant_need else None,
            "intrinsic_reward": round(intrinsic_reward, 4),
            "total_reward": round(sum(self._reward_history), 3),
            "reflection": reflection.to_dict() if reflection else None,
            "rsi": rsi_result.to_dict() if rsi_result else None,
            "duration_ms": round((time.time() - t_start) * 1000, 1),
        }

    def _select_action(self, meta_strategy: Optional[str] = None) -> Optional[Any]:
        """需求驱动的行动选择 — v2.0 元认知增强版"""
        internal_tools = {"run_python", "apply_modification"}
        available = [
            a for a in self.tool_registry._tools.keys() 
            if a not in internal_tools
        ]
        if not available:
            return None

        import numpy as np

        # 元认知策略引导
        strategy_bias = {}
        if meta_strategy:
            strategy_action_map = {
                "深入调试": ["analyze", "explore"],
                "创意发散": ["explore", "meta_reflect"],
                "数据分析": ["analyze", "deliberate"],
                "快速响应": list(available),  # 所有工具
                "深度反思": ["reflect", "meta_reflect"],
                "探索学习": ["explore", "learn_skill"],
            }
            preferred = strategy_action_map.get(meta_strategy, [])
            for a in preferred:
                if a in available:
                    strategy_bias[a] = 0.3

        # 探索 vs 利用
        if np.random.random() < (getattr(self.config, 'exploration_rate', 0.2)):
            action = np.random.choice(available)
            return (action, self._infer_default_args(action))

        dominant, _ = self.needs.get_dominant_need()
        confidence = self.emotion_gradient.state.confidence

        scores = {}
        for action in available:
            skill = self.memory.skills.get(action)
            prof = skill.proficiency if skill else 0.5
            conf_mod = 1.0 + (1.0 - confidence) * prof
            strategy_mod = strategy_bias.get(action, 0.0)
            scores[action] = prof * conf_mod + strategy_mod + np.random.normal(0, 0.05)

        best_action = max(scores, key=scores.get)
        return (best_action, self._infer_default_args(best_action))

    def _infer_default_args(self, action: str) -> dict:
        """根据工具签名推断默认参数"""
        try:
            tool = self.tool_registry._tools.get(action)
            if not tool or not tool.handler:
                return {}
            import inspect
            sig = inspect.signature(tool.handler)
            defaults: dict = {}
            for name, param in sig.parameters.items():
                if name == "self":
                    continue
                if param.default is inspect.Parameter.empty:
                    pname = name.lower()
                    if "url" in pname:
                        defaults[name] = "https://example.com"
                    elif "path" in pname or "file" in pname:
                        defaults[name] = "README.md"
                    elif "command" in pname or "cmd" in pname:
                        defaults[name] = "echo hello"
                    elif "code" in pname or "script" in pname:
                        defaults[name] = "print('hello')"
                    elif "query" in pname or "text" in pname or "content" in pname:
                        defaults[name] = "hello"
                    else:
                        defaults[name] = "x"
            return defaults
        except Exception as e:
            logger.warning(f"_infer_default_args failed for {action}: {e}")
            return {}

    def execute_action(self, action: str, **kwargs) -> Any:
        """执行动作并更新记忆"""
        result = self.call_tool(action, **kwargs)
        self.memory.record_skill_result(action, result is not None)
        return result

    def _satisfy_needs_from_action(self, action: Optional[str], 
                                   task_success: Optional[float]):
        """根据行动结果满足需求"""
        if action == "explore":
            self.needs.satisfy(NeedType.CERTAINTY, 0.05)
            self.needs.satisfy(NeedType.COMPETENCE, 0.03)
        elif action == "analyze":
            self.needs.satisfy(NeedType.CERTAINTY, 0.08)
            self.needs.satisfy(NeedType.COMPETENCE, 0.06)
        elif action == "reflect":
            self.needs.satisfy(NeedType.AUTONOMY, 0.05)
            self.needs.satisfy(NeedType.COMPETENCE, 0.04)
        elif action == "rest":
            self.needs.satisfy(NeedType.ENERGY, 0.1)
        elif action == "deliberate":
            self.needs.satisfy(NeedType.CERTAINTY, 0.1)
            self.needs.satisfy(NeedType.COMPETENCE, 0.08)
        elif action == "meta_reflect":
            self.needs.satisfy(NeedType.AUTONOMY, 0.08)
            self.needs.satisfy(NeedType.COMPETENCE, 0.07)

        if task_success is not None and task_success > 0.7:
            self.needs.satisfy(NeedType.COMPETENCE, 0.05 * task_success)

    def _self_reflect(self) -> Any:
        """自我反思 — v2.0 增强版（含综合情感）"""
        from laap.memory.hierarchical import Reflection
        recent = self._reward_history[-5:] if self._reward_history else [0]
        trend = recent[-1] - recent[0] if len(recent) >= 2 else 0
        vol = float(np.std(recent)) if len(recent) >= 2 else 0

        # 综合情感状态
        try:
            emotion_summary = self.comprehensive_emotion.get_emotion_summary()
            dominant_emo, intensity, cn = self.comprehensive_emotion.get_dominant_emotion()
        except Exception:
            emotion_summary = ""
            dominant_emo, intensity = "平静", 0.0

        if trend < -0.2:
            obs, hyp = "奖励下降", "需要新策略满足需求"
        elif vol > 0.3:
            obs, hyp = "波动过大", "需要增加确定性需求"
        elif self.emotion_gradient.state.confidence < 0.3:
            obs, hyp = "置信度低", "需要更多数据"
        elif intensity > 0.5 and dominant_emo in ("sadness", "anger", "fear"):
            obs, hyp = f"负面情绪({cn})", "需要调整行动以改善情绪"
        else:
            obs, hyp = "运行平稳", "可以尝试提升效率"

        ref = Reflection(
            episode=self.step_count,
            observation=obs,
            hypothesis=hyp,
            outcome=f"trend={trend:.3f}, vol={vol:.3f}, emotion={dominant_emo}",
            reward_delta=trend,
        )
        self.memory.add_reflection(ref)
        return ref

    def apply_modification(self, modification: Dict[str, Any]) -> bool:
        """扩展基类以支持需求调整和元认知配置"""
        mod_type = modification.get("type")
        params = modification.get("params", {})
        try:
            if mod_type == "adjust_needs":
                for need_str, adjustments in params.items():
                    try:
                        nt = NeedType(need_str)
                    except ValueError:
                        continue
                    if nt in self.needs.needs:
                        for k, v in adjustments.items():
                            if hasattr(self.needs.needs[nt], k):
                                setattr(self.needs.needs[nt], k, v)
                self._self_modifications += 1
                return True
            elif mod_type == "adjust_meta_cognition":
                if hasattr(self, 'meta_cognition') and self.config.enable_meta_cognition:
                    if "curiosity" in params:
                        self.meta_cognition.state.curiosity_level = max(
                            0.0, min(1.0, params["curiosity"])
                        )
                    if "self_efficacy" in params:
                        self.meta_cognition.state.self_efficacy = max(
                            0.0, min(1.0, params["self_efficacy"])
                        )
                self._self_modifications += 1
                return True
            else:
                return super().apply_modification(modification)
        except Exception as e:
            logger.error(f"Modification failed: {e}")
            return False

    def chat(self, message: str, system_prompt: str = "",
             tools: Optional[List[Any]] = None,
             max_rounds: Optional[int] = None,
             handler: Optional[Any] = None) -> str:
        """
        重写 chat() — 注入 PSI 状态到系统提示
        
        增强：注入需求状态、情感状态到 System Prompt
        """
        # 1. 更新需求
        self.needs.tick()

        # 2. 构建 PSI 状态提示
        psi_parts = ["[PSI 认知状态]"]
        for nt in self.needs.needs:
            need = self.needs.needs[nt]
            status = "满足" if need.current_level > 0.7 else "中等" if need.current_level > 0.4 else "匮乏"
            psi_parts.append(f"  {nt.value}: {need.current_level:.0%} ({status})")

        dominant, drive = self.needs.get_dominant_need()
        if dominant:
            psi_parts.append(f"主导需求: {dominant.value} (驱动力={drive:.2f})")

        # 情感状态
        try:
            emotion_block = self.comprehensive_emotion.get_emotion_prompt_block()
            psi_parts.append(emotion_block)
        except Exception:
            pass

        psi_prompt = "\n".join(psi_parts)

        # 3. 合并提示
        full_prompt = f"{psi_prompt}\n\n{system_prompt}" if system_prompt else psi_prompt

        # 4. 执行 chat
        result = super().chat(
            message=message,
            system_prompt=full_prompt,
            tools=tools,
            max_rounds=max_rounds,
            handler=handler,
        )

        # 5. 根据结果触发情感
        if result and len(result) > 10:
            self._trigger_emotion("tool_success", 0.2, "chat响应成功")
        else:
            self._trigger_emotion("tool_failure", 0.1, "chat响应为空")

        return result

    def complete_status(self) -> dict:
        """完整状态报告 — v2.0 增加元认知/议会/综合情感"""
        s = super().status()
        s.update({
            "needs": self.needs.get_profile(),
            "emotional_state": self.emotion_gradient.state.to_dict(),
            "comprehensive_emotion": {
                "dominant": self.comprehensive_emotion.dominant,
                "intensity": round(self.comprehensive_emotion.dominant_intensity, 3),
            } if self.config.enable_comprehensive_emotion else None,
            "mean_reward": round(self.emotion_gradient.mean_reward, 4),
            "reward_volatility": round(self.emotion_gradient.reward_volatility, 4),
            "dominant_need": self.needs.get_dominant_need()[0].value if 
                self.needs.get_dominant_need()[0] else None,
            "goals": self.goals.to_dict(),
            "rsi": self.rsi.status() if self.rsi else None,
            "fitness": self.evaluator.report(self) if self.evaluator else None,
            "meta_cognition": self.meta_cognition.status() if 
                self.config.enable_meta_cognition else None,
            "parliament": self.parliament.status() if 
                self.config.enable_parliament else None,
        })
        return s

    @property
    def total_reward(self) -> float:
        return round(sum(self._reward_history), 2)
