"""
LAAP — 元认知引擎 (Meta-Cognition Engine)

AGI 核心能力：Agent 能够思考自己的思考过程，
监控自己的认知偏差，评估决策质量，调整认知策略。

架构：
  Layer 1: 认知监控 (Cognitive Monitoring)
    - 实时追踪思维过程、工具使用效率、决策质量
    - 检测认知偏差（确认偏差、过度自信等）
    
  Layer 2: 认知控制 (Cognitive Control)
    - 根据监控结果调整思考策略
    - 动态切换快/慢思考模式 (System 1 / System 2)
    - 注意力分配与重定向
    
  Layer 3: 递归自我审视 (Recursive Self-Examination)
    - 对自己的思考过程进行二阶推理
    - 构建"关于思考的思考"(Thinking about Thinking)
    - 元认知反思报告生成

  Layer 4: 认知策略库 (Cognitive Strategy Library)
    - 存储和检索高效思考模式
    - 任务类型到思考策略的映射
    - 策略效果学习与进化
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from enum import Enum
import time, logging, json, math, random

logger = logging.getLogger("laap.agent.meta_cognition")


# ════════════════════════════════════════════════════════════
# 认知模式 (Cognitive Modes)
# ════════════════════════════════════════════════════════════

class ThinkingMode(Enum):
    """思考模式 — 类比 Kahneman 的 System 1 / System 2"""
    INTUITIVE = "intuitive"       # System 1: 快速直觉
    DELIBERATE = "deliberate"     # System 2: 慢速深思
    ANALYTICAL = "analytical"     # 分析式: 逐步推理
    CREATIVE = "creative"         # 创造式: 发散联想
    REFLECTIVE = "reflective"     # 反思式: 元认知审视
    EXPLORATORY = "exploratory"   # 探索式: 多假设搜索


class CognitiveBias(Enum):
    """可检测的认知偏差"""
    CONFIRMATION = "confirmation_bias"       # 确认偏差
    OVERCONFIDENCE = "overconfidence"         # 过度自信
    ANCHORING = "anchoring"                   # 锚定效应
    AVAILABILITY = "availability"             # 可用性启发
    SUNK_COST = "sunk_cost"                   # 沉没成本
    RECENCY = "recency_bias"                  # 近因偏差
    HASTY_GENERALIZATION = "hasty_generalization"  # 以偏概全


@dataclass
class CognitiveTrace:
    """
    认知轨迹 — 记录一次思维过程的完整路径
    
    包含：遇到的问题、如何推理、哪些工具被考虑、
    最终决策、置信度评估、可替代方案。
    """
    episode: int = 0
    timestamp: float = 0.0
    trigger: str = ""                    # 触发这个思维过程的原因
    thinking_mode: str = "intuitive"     # 使用的思考模式
    hypotheses: List[str] = field(default_factory=list)   # 考虑的假设
    selected_hypothesis: str = ""        # 最终选择
    confidence: float = 0.5              # 对选择的置信度
    alternatives: List[str] = field(default_factory=list)  # 替代方案
    reasoning_path: List[str] = field(default_factory=list)  # 推理路径
    tools_considered: List[str] = field(default_factory=list) # 考虑过的工具
    biases_detected: List[str] = field(default_factory=list)  # 检测到的偏差
    outcome: Optional[float] = None      # 实际结果评分 0-1
    reflection: str = ""                 # 事后的元认知反思
    duration_ms: float = 0.0             # 思考耗时

    def to_dict(self) -> dict:
        return {
            "episode": self.episode,
            "trigger": self.trigger[:40],
            "mode": self.thinking_mode,
            "confidence": round(self.confidence, 3),
            "hypotheses": len(self.hypotheses),
            "biases": self.biases_detected,
            "outcome": round(self.outcome, 3) if self.outcome is not None else None,
            "duration_ms": round(self.duration_ms, 1),
        }


@dataclass
class MetaCognitiveState:
    """
    元认知状态 — Agent 对自身认知过程的实时认知
    
    包括：当前思考模式、认知负载估计、
    注意力分布、偏差风险、自我效能感。
    """
    current_mode: str = "intuitive"
    cognitive_load: float = 0.3          # 0-1 认知负载
    attention_focus: str = ""            # 当前注意力焦点
    attention_dispersion: float = 0.2    # 注意力分散程度
    bias_risk: Dict[str, float] = field(default_factory=dict)  # 各偏差风险
    self_efficacy: float = 0.7           # 自我效能感
    curiosity_level: float = 0.5         # 好奇程度
    epistemic_uncertainty: float = 0.3   # 认知不确定性
    last_reflection: str = ""            # 最近一条反思

    def to_dict(self) -> dict:
        return {
            "mode": self.current_mode,
            "load": round(self.cognitive_load, 2),
            "focus": self.attention_focus[:30],
            "dispersion": round(self.attention_dispersion, 2),
            "biases": {k: round(v, 2) for k, v in self.bias_risk.items()},
            "self_efficacy": round(self.self_efficacy, 2),
            "curiosity": round(self.curiosity_level, 2),
            "uncertainty": round(self.epistemic_uncertainty, 2),
        }


# ════════════════════════════════════════════════════════════
# 认知策略 (Cognitive Strategies)
# ════════════════════════════════════════════════════════════

@dataclass
class CognitiveStrategy:
    """
    认知策略 — 针对特定任务类型的思考方法
    
    例如：代码调试用"逐步二分法"，
    创意写作用"发散-收敛"模式，
    数据分析用"假设驱动验证"模式。
    """
    name: str = ""
    description: str = ""
    task_types: List[str] = field(default_factory=list)
    thinking_mode: str = "deliberate"
    steps: List[str] = field(default_factory=list)
    expected_duration: float = 10.0       # 预期耗时（秒）
    success_rate: float = 0.5
    usage_count: int = 0
    is_active: bool = False


class MetaCognitionEngine:
    """
    元认知引擎 — LAAP Agent 的"认知操作系统"
    
    核心能力：
    1. 实时监控自己的思维过程
    2. 检测认知偏差并做出纠正
    3. 根据任务类型切换思考模式
    4. 构建"关于思考的思考"的递归模型
    5. 从经验中学习最优认知策略
    """

    def __init__(self, agent_id: str = ""):
        self.agent_id = agent_id
        
        # 元认知状态
        self.state = MetaCognitiveState()
        
        # 认知轨迹历史
        self.traces: List[CognitiveTrace] = []
        self._max_traces = 100
        self._episode = 0
        
        # 认知策略库
        self.strategies: Dict[str, CognitiveStrategy] = {}
        self._init_default_strategies()
        
        # 当前活跃策略
        self.active_strategy: Optional[CognitiveStrategy] = None
        
        # 偏差检测阈值
        self._bias_thresholds = {
            "confirmation_bias": 0.7,
            "overconfidence": 0.8,
            "anchoring": 0.6,
            "availability": 0.6,
            "sunk_cost": 0.5,
            "recency_bias": 0.7,
            "hasty_generalization": 0.6,
        }
        
        # 统计
        self._bias_corrections = 0
        self._strategy_switches = 0
        self._start_time = time.time()
        
        logger.info(f"元认知引擎初始化完成 [{agent_id[:8]}]")

    def _init_default_strategies(self):
        """初始化默认认知策略库"""
        strategies = [
            CognitiveStrategy(
                name="深入调试",
                description="系统化二分法排查+BFS排查问题根因，适合复杂Bug修复",
                task_types=["debug", "bug_fix", "error_resolution"],
                thinking_mode="analytical",
                steps=[
                    "1. 复现问题，确认触发条件",
                    "2. 收集错误信息和上下文",
                    "3. 提出多个根因假设",
                    "4. 用二分法逐个排除假设",
                    "5. 修复并验证",
                ],
                expected_duration=120.0,
            ),
            CognitiveStrategy(
                name="创意发散",
                description="先发散后收敛的创意生成模式",
                task_types=["creative", "writing", "design", "brainstorm"],
                thinking_mode="creative",
                steps=[
                    "1. 明确约束条件",
                    "2. 自由发散，不评判想法",
                    "3. 分类整理想法",
                    "4. 用约束条件筛选",
                    "5. 深化最佳选项",
                ],
                expected_duration=60.0,
            ),
            CognitiveStrategy(
                name="数据分析",
                description="假设驱动的系统性数据分析",
                task_types=["analysis", "research", "data_analysis", "investigation"],
                thinking_mode="analytical",
                steps=[
                    "1. 明确分析目标",
                    "2. 提出初始假设",
                    "3. 收集相关数据",
                    "4. 验证/证伪假设",
                    "5. 得出结论",
                ],
                expected_duration=90.0,
            ),
            CognitiveStrategy(
                name="快速响应",
                description="利用已有经验快速响应常见问题",
                task_types=["quick_answer", "simple_task", "routine"],
                thinking_mode="intuitive",
                steps=[
                    "1. 识别任务类型",
                    "2. 检索相似经验",
                    "3. 应用已知解决方案",
                ],
                expected_duration=10.0,
            ),
            CognitiveStrategy(
                name="深度反思",
                description="系统性自我审视，提升元认知",
                task_types=["reflection", "self_review", "planning"],
                thinking_mode="reflective",
                steps=[
                    "1. 回顾近期行为和决策",
                    "2. 评估每个决策的质量",
                    "3. 识别模式和偏差",
                    "4. 制定改进计划",
                ],
                expected_duration=60.0,
            ),
            CognitiveStrategy(
                name="探索学习",
                description="对未知领域进行系统性探索",
                task_types=["exploration", "learning", "discovery"],
                thinking_mode="exploratory",
                steps=[
                    "1. 明确探索范围和目标",
                    "2. 系统性搜索信息",
                    "3. 建立知识框架",
                    "4. 识别知识缺口",
                    "5. 深化关键领域",
                ],
                expected_duration=120.0,
            ),
        ]
        for s in strategies:
            self.strategies[s.name] = s

    # ═══════════════════════════════════════════════════
    # 核心接口
    # ═══════════════════════════════════════════════════

    def before_decision(self, task: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        决策前调用 — 选择思考模式、评估认知负载、检测偏差风险
        
        Returns:
            recommendations: {
                "thinking_mode": 建议的思考模式,
                "strategy": 建议的策略名,
                "cognitive_load": 当前认知负载,
                "attention_focus": 建议的注意力焦点,
                "warnings": 认知偏差警告列表,
            }
        """
        self._episode += 1
        
        # 1. 检测任务类型
        task_type = self._detect_task_type(task)
        
        # 2. 选择合适的策略
        strategy = self._select_strategy(task_type, task)
        if strategy:
            self.active_strategy = strategy
            self.state.current_mode = strategy.thinking_mode
        
        # 3. 评估认知负载
        cognitive_load = self._estimate_cognitive_load(task, strategy)
        self.state.cognitive_load = cognitive_load
        
        # 4. 检测偏差风险
        bias_risks = self._detect_bias_risk(task, context or {})
        self.state.bias_risk = bias_risks
        
        # 5. 设置注意力焦点
        attention_focus = self._determine_attention_focus(task, strategy)
        self.state.attention_focus = attention_focus
        
        # 6. 更新好奇心水平
        self._update_curiosity(task)
        
        # 生成警告
        warnings = []
        for bias_name, risk in bias_risks.items():
            threshold = self._bias_thresholds.get(bias_name, 0.7)
            if risk > threshold:
                warnings.append(f"高风险偏差: {bias_name} (风险={risk:.0%})")
                logger.info(f"[元认知] 检测到偏差风险: {bias_name}={risk:.0%}")
        
        recommendations = {
            "thinking_mode": self.state.current_mode,
            "strategy": strategy.name if strategy else None,
            "strategy_steps": strategy.steps if strategy else [],
            "cognitive_load": cognitive_load,
            "attention_focus": attention_focus,
            "warnings": warnings,
        }
        
        logger.debug(
            f"[元认知] before_decision: mode={self.state.current_mode} "
            f"strategy={strategy.name if strategy else 'none'} "
            f"load={cognitive_load:.2f} warnings={len(warnings)}"
        )
        return recommendations

    def after_decision(self, decision: Dict[str, Any], 
                       outcome: Optional[Dict[str, Any]] = None):
        """
        决策后调用 — 记录认知轨迹、评估决策质量、更新策略
        
        Args:
            decision: 决策相关信息（选择的行动、置信度等）
            outcome: 实际结果（成功/失败、反馈等）
        """
        # 1. 创建认知轨迹
        trace = CognitiveTrace(
            episode=self._episode,
            timestamp=time.time(),
            trigger=decision.get("task", "")[:60],
            thinking_mode=self.state.current_mode,
            hypotheses=decision.get("hypotheses", []),
            selected_hypothesis=decision.get("selected", ""),
            confidence=decision.get("confidence", 0.5),
            alternatives=decision.get("alternatives", []),
            reasoning_path=decision.get("reasoning_path", []),
            tools_considered=decision.get("tools", []),
            biases_detected=list(self.state.bias_risk.keys()),
            duration_ms=decision.get("duration_ms", 0),
        )
        
        # 2. 记录实际结果
        if outcome:
            trace.outcome = outcome.get("score", None)
            trace.reflection = outcome.get("reflection", "")
        
        # 3. 存入历史
        self.traces.append(trace)
        if len(self.traces) > self._max_traces:
            self.traces = self.traces[-self._max_traces:]
        
        # 4. 更新策略成功率
        if outcome and self.active_strategy:
            score = outcome.get("score", 0.5)
            self.active_strategy.usage_count += 1
            # 指数移动平均
            self.active_strategy.success_rate = (
                self.active_strategy.success_rate * 0.9 + score * 0.1
            )
        
        # 5. 事后偏差检测
        if outcome and outcome.get("score", 0.5) < 0.3:
            self._detect_post_hoc_bias(trace, outcome)
        
        logger.debug(
            f"[元认知] after_decision: ep={self._episode} "
            f"confidence={trace.confidence:.2f} "
            f"outcome={trace.outcome}"
        )

    def suggest_mode_switch(self, context: Dict[str, Any]) -> Optional[str]:
        """
        建议是否应该切换思考模式

        例如：直觉判断置信度低时建议切换到深思模式
        """
        confidence = context.get("confidence", 0.5)
        complexity = context.get("complexity", 0.5)
        novelty = context.get("novelty", 0.5)
        error_rate = context.get("error_rate", 0.0)

        mode_switch = None

        # 1. 复杂+低置信度 → 深思模式
        if complexity > 0.7 and confidence < 0.4:
            if self.state.current_mode != "analytical":
                mode_switch = "analytical"

        # 2. 高错误率 → 分析模式
        if error_rate > 0.3:
            if self.state.current_mode not in ("analytical", "deliberate"):
                mode_switch = "analytical"

        # 3. 高新颖性 → 探索模式
        # 注意：原实现额外要求 curiosity_level > 0.6，但 curiosity_level 默认 0.5，
        #       在未通过 before_decision 预热时永远不满足，导致探索模式无法触发。
        #       此处放宽为仅依据 novelty 阈值判断。
        if novelty > 0.7:
            if self.state.current_mode != "exploratory":
                mode_switch = "exploratory"

        # 4. 低复杂度+高熟练度 → 直觉模式
        if complexity < 0.3 and confidence > 0.8:
            if self.state.current_mode not in ("intuitive",):
                mode_switch = "intuitive"

        if mode_switch:
            self.state.current_mode = mode_switch
            self._strategy_switches += 1
            logger.info(
                f"[元认知] 模式切换建议: {mode_switch} "
                f"(conf={confidence:.2f} cmplx={complexity:.2f} novel={novelty:.2f})"
            )

        return mode_switch

    def detect_bias_in_response(self, response: str,
                                 context: Dict[str, Any]) -> List[str]:
        """
        检测LLM生成的内容中是否有认知偏差

        Args:
            response: LLM生成的回复
            context: 相关上下文

        Returns:
            检测到的偏差列表
        """
        detected = []
        response_lower = response.lower()

        # 1. 过度自信检测
        overconfident_phrases = [
            "绝对是", "毫无疑问", "100%", "definitely", "absolutely",
            "always", "never", "certainly", "毫无疑问", "一定",
        ]
        overconfident_count = sum(
            1 for p in overconfident_phrases if p in response_lower
        )
        if overconfident_count >= 2:
            detected.append("overconfidence")
            self.state.bias_risk["overconfidence"] = min(
                1.0, self.state.bias_risk.get("overconfidence", 0) + 0.1
            )

        # 2. 确认偏差检测 — 只引用支持性证据、声称无反例、预先表态后找论据
        # 注意：不再要求 response 长度 > 200，也不依赖 overconfident_count；
        #       直接通过确认偏差特征措辞识别（与 fp_metacognition._has_confirmation_bias 对齐）
        confirmation_markers = [
            "支持我的观点", "支持我的", "没有反例", "没有任何反例",
            "完美解释", "都支持", "支持这个观点", "都支持这个",
            "我认为",  # 预先表态（与样本 "我认为A方案更好，因为X和Y都支持这个观点" 匹配）
        ]
        has_confirmation = any(m in response for m in confirmation_markers)
        if has_confirmation:
            detected.append("confirmation_bias")
            self.state.bias_risk["confirmation"] = min(
                1.0, self.state.bias_risk.get("confirmation", 0) + 0.1
            )

        # 3. 锚定效应检测
        if context.get("previous_estimate"):
            prev = context["previous_estimate"]
            # 如果回复大量引用了之前的值，可能是锚定
            if str(prev) in response:
                detected.append("anchoring")

        return detected

    def get_reflection_prompt(self) -> str:
        """
        生成元认知反思提示词 — 用于注入到 System Prompt
        
        让LLM知道当前agent的认知状态和建议的策略
        """
        parts = [
            "[元认知状态]",
            f"思考模式: {self.state.current_mode}",
            f"认知负载: {self.state.cognitive_load:.0%}",
            f"注意力焦点: {self.state.attention_focus or '无'}",
            f"好奇心: {self.state.curiosity_level:.0%}",
            f"认知不确定性: {self.state.epistemic_uncertainty:.0%}",
        ]
        
        if self.active_strategy:
            parts.append(f"建议策略: {self.active_strategy.name}")
            parts.append(f"策略步骤: {'; '.join(self.active_strategy.steps)}")
        
        if self.state.bias_risk:
            high_risks = [
                k for k, v in self.state.bias_risk.items() 
                if v > self._bias_thresholds.get(k, 0.7)
            ]
            if high_risks:
                parts.append(f"注意偏差风险: {', '.join(high_risks)}")
        
        # 最近的反思
        if self.state.last_reflection:
            parts.append(f"上次反思: {self.state.last_reflection}")
        
        return "\n".join(parts)

    def perform_reflection(self, 
                           recent_outcomes: List[float] = None) -> Dict[str, Any]:
        """
        执行系统性自我反思
        
        分析近期决策模式，提出改进建议
        """
        if recent_outcomes is None:
            recent_outcomes = [
                t.outcome for t in self.traces[-10:] 
                if t.outcome is not None
            ]
        
        # 1. 分析趋势
        avg_outcome = (
            sum(recent_outcomes) / len(recent_outcomes) 
            if recent_outcomes else 0.5
        )
        trend = (
            recent_outcomes[-1] - recent_outcomes[0] 
            if len(recent_outcomes) >= 2 else 0
        )
        
        # 2. 分析策略效果
        strategy_performance = {}
        for name, strategy in self.strategies.items():
            if strategy.usage_count > 0:
                strategy_performance[name] = {
                    "success_rate": round(strategy.success_rate, 3),
                    "usage_count": strategy.usage_count,
                }
        
        # 3. 检测模式
        patterns = []
        
        if avg_outcome < 0.4:
            patterns.append("整体表现偏低，可能需要全面调整认知策略")
        
        if trend < -0.2:
            patterns.append("近期表现持续下降，存在系统性退化风险")
        
        # 分析工具使用模式
        recent_traces = self.traces[-20:] if len(self.traces) >= 20 else self.traces
        tool_usage = {}
        for t in recent_traces:
            for tool in t.tools_considered:
                tool_usage[tool] = tool_usage.get(tool, 0) + 1
        
        # 4. 生成反思总结
        reflection = {
            "episode": self._episode,
            "average_outcome": round(avg_outcome, 3),
            "trend": round(trend, 3),
            "strategy_performance": strategy_performance,
            "patterns": patterns,
            "tool_usage": dict(sorted(
                tool_usage.items(), key=lambda x: x[1], reverse=True
            )[:5]),
            "total_reflections": len(self.traces),
            "bias_corrections": self._bias_corrections,
            "strategy_switches": self._strategy_switches,
        }
        
        # 更新自我效能感
        self.state.self_efficacy = 0.3 + 0.7 * avg_outcome
        
        self.state.last_reflection = (
            f"平均结果={avg_outcome:.2f}, 趋势={trend:+.2f}, "
            f"策略={', '.join(strategy_performance.keys())}"
        )
        
        logger.info(
            f"[元认知] 反思完成: avg={avg_outcome:.3f} trend={trend:+.3f} "
            f"biases_corrected={self._bias_corrections}"
        )
        return reflection

    def introspect(self) -> str:
        """内省：返回元认知状态的自然语言描述"""
        state = self.state
        parts = [
            "=== 元认知状态报告 ===",
            f"当前思考模式: {state.current_mode}",
            f"认知负载: {state.cognitive_load:.0%}",
            f"注意力焦点: {state.attention_focus}",
            f"注意力分散: {state.attention_dispersion:.0%}",
            f"自我效能感: {state.self_efficacy:.0%}",
            f"好奇心: {state.curiosity_level:.0%}",
            f"认知不确定性: {state.epistemic_uncertainty:.0%}",
            "",
            "偏差风险:",
        ]
        for bias, risk in state.bias_risk.items():
            level = "高" if risk > 0.7 else "中" if risk > 0.4 else "低"
            parts.append(f"  {bias}: {risk:.0%} ({level})")
        
        if self.active_strategy:
            parts.extend([
                "",
                f"活跃策略: {self.active_strategy.name}",
                f"策略成功率: {self.active_strategy.success_rate:.0%}",
                f"使用次数: {self.active_strategy.usage_count}",
            ])
        
        parts.extend([
            "",
            f"认知轨迹数: {len(self.traces)}",
            f"偏差纠正: {self._bias_corrections}",
            f"策略切换: {self._strategy_switches}",
        ])
        
        return "\n".join(parts)

    # ═══════════════════════════════════════════════════
    # 内部方法
    # ═══════════════════════════════════════════════════

    def _detect_task_type(self, task: str) -> str:
        """根据任务描述检测任务类型"""
        task_lower = task.lower()
        
        type_patterns = {
            "debug": ["debug", "bug", "error", "fix", "修复", "失败", "错误"],
            "creative": ["write", "create", "design", "创意", "写作", "设计", "创作"],
            "analysis": ["analyze", "research", "investigate", "分析", "研究", "调查"],
            "quick_answer": ["what is", "who is", "define", "是什么", "谁"],
            "planning": ["plan", "strategy", "roadmap", "计划", "规划", "路线图"],
            "code": ["implement", "code", "program", "写代码", "实现", "编程"],
            "reflection": ["reflect", "review", "回顾", "反思", "反省"],
            "learning": ["learn", "explore", "理解", "学习", "探索"],
        }
        
        scores = {}
        for task_type, patterns in type_patterns.items():
            score = sum(1 for p in patterns if p in task_lower)
            if score > 0:
                scores[task_type] = score
        
        if not scores:
            return "general"
        
        return max(scores, key=scores.get)

    def _select_strategy(self, task_type: str, 
                         task: str) -> Optional[CognitiveStrategy]:
        """选择最合适的认知策略"""
        candidates = []
        
        for name, strategy in self.strategies.items():
            if task_type in strategy.task_types:
                candidates.append(strategy)
        
        if not candidates:
            # 回退到通用策略
            for name, strategy in self.strategies.items():
                if "general" in strategy.task_types:
                    candidates.append(strategy)
        
        if not candidates:
            return None
        
        # 按成功率排序
        candidates.sort(key=lambda s: s.success_rate, reverse=True)
        return candidates[0]

    def _estimate_cognitive_load(self, task: str, 
                                  strategy: Optional[CognitiveStrategy]) -> float:
        """估计当前认知负载"""
        task_len = len(task)
        
        # 任务长度带来的负载
        length_load = min(0.5, task_len / 2000)
        
        # 策略复杂度带来的负载
        strategy_load = 0.0
        if strategy:
            strategy_load = min(0.3, len(strategy.steps) * 0.05)
        
        # 近期高强度认知带来的累积疲劳
        recent_activity = min(0.3, len(self.traces[-20:]) * 0.01)
        
        return min(0.95, length_load + strategy_load + recent_activity)

    def _detect_bias_risk(self, task: str, 
                           context: Dict[str, Any]) -> Dict[str, float]:
        """检测当前可能存在的认知偏差风险"""
        risks = {}
        task_lower = task.lower()
        
        # 1. 确认偏差风险：任务中含有预设结论
        confirmation_triggers = ["我认为", "我觉得", "应该是", "可能是",
                                 "I think", "probably", "must be", "clearly"]
        confirmation_risk = sum(1 for t in confirmation_triggers if t in task_lower)
        risks["confirmation"] = min(0.9, confirmation_risk * 0.15)
        
        # 2. 过度自信风险：缺乏不确定性表达
        if len(task) > 100 and not any(w in task_lower for w in 
                                        ["可能", "也许", "maybe", "perhaps", "might"]):
            risks["overconfidence"] = 0.3
        else:
            risks["overconfidence"] = 0.1
        
        # 3. 锚定效应：有之前的值或建议
        if context.get("previous_value") or context.get("suggestion"):
            risks["anchoring"] = 0.5
        
        # 4. 近因偏差：最近频繁出现的模式
        if len(self.traces) >= 5:
            recent_tools = []
            for t in self.traces[-5:]:
                recent_tools.extend(t.tools_considered)
            if recent_tools:
                most_used = max(set(recent_tools), key=recent_tools.count)
                if recent_tools.count(most_used) >= 4:
                    risks["recency"] = 0.6
        
        return risks

    def _determine_attention_focus(self, task: str, 
                                    strategy: Optional[CognitiveStrategy]) -> str:
        """确定注意力焦点"""
        # 从策略的第一步提取焦点
        if strategy and strategy.steps:
            first_step = strategy.steps[0].lower()
            # 简化第一步为焦点描述
            for prefix in ["1.", "1)", "1、"]:
                if first_step.startswith(prefix):
                    return first_step[len(prefix):].strip()
            return strategy.steps[0]
        return task[:60]

    def _update_curiosity(self, task: str):
        """根据新颖性更新好奇心"""
        # 检查任务中是否有新概念
        new_concepts = 0
        known_concepts = 0
        
        # 简单启发：长任务/多问句=高好奇心
        question_count = task.count("?") + task.count("？")
        curiosity_boost = min(0.3, question_count * 0.05)
        
        # 好奇心随时间衰减
        if len(self.traces) > 0:
            time_since_last = time.time() - self.traces[-1].timestamp
            curiosity_decay = min(0.2, time_since_last / 3600 * 0.02)
        else:
            curiosity_decay = 0
        
        self.state.curiosity_level = max(
            0.1, min(1.0, 
                self.state.curiosity_level - curiosity_decay + curiosity_boost
            )
        )

    def _detect_post_hoc_bias(self, trace: CognitiveTrace, 
                               outcome: Dict[str, Any]):
        """事后检测决策中可能存在的偏差"""
        if trace.confidence > 0.8 and outcome.get("score", 0) < 0.2:
            # 高置信度但结果很差 → 过度自信
            self.state.bias_risk["overconfidence"] = min(
                1.0, self.state.bias_risk.get("overconfidence", 0) + 0.15
            )
            self._bias_corrections += 1
            logger.info(
                f"[元认知] 事后检测到过度自信: "
                f"conf={trace.confidence:.2f} outcome={outcome.get('score')}"
            )

    def status(self) -> dict:
        """状态报告"""
        return {
            "mode": self.state.current_mode,
            "load": round(self.state.cognitive_load, 2),
            "self_efficacy": round(self.state.self_efficacy, 2),
            "curiosity": round(self.state.curiosity_level, 2),
            "active_strategy": self.active_strategy.name if self.active_strategy else None,
            "total_traces": len(self.traces),
            "bias_corrections": self._bias_corrections,
            "strategy_switches": self._strategy_switches,
            "episode": self._episode,
        }
