"""
LAAP — First-Principles Metacognition Engine (第一性原理元认知引擎)

第一性原理 + 元认知 = 数字生命体对自身思考的根基性审视

本引擎将第一性原理推理与元认知监控深度融合：
  当元认知检测到不确定性、偏差或认知瓶颈时，
  自动回退到第一性原理进行根基性重新推理。

递归自审视层级 (MetaCognitionLevel):
  Level 0: 反应式 — 无元认知，直接响应
  Level 1: 监控 — 追踪自己在想什么
  Level 2: 控制 — 能调整自己的思考方式
  Level 3: 递归 — 审视自己如何审视
  Level 4: 根基 — 将思维还原到第一性原理
  Level 5: 元递归 — 对递归审视本身进行审视

与 Brain 的集成点：
  Brain.before_decision() → FPMetaEngine.monitor_thinking()
  Brain.after_decision() → FPMetaEngine.evaluate_thinking()
  Brain.think() → FPMetaEngine.ground_judgment()
  Brain.reflect() → FPMetaEngine.recursive_examination()
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from enum import Enum
import time
import logging
import json
import math
import re
import uuid

logger = logging.getLogger("laap.cognition.metacognition.fp_metacognition")

# ════════════════════════════════════════════════════════════
# 元认知层级 — 递归自审视的深度
# ════════════════════════════════════════════════════════════


class MetaCognitionLevel(Enum):
    """元认知层级 — 递归自审视的深度

    Level 0: 反应式 — 无元认知，直接响应
    Level 1: 监控 — 追踪自己在想什么
    Level 2: 控制 — 能调整自己的思考方式
    Level 3: 递归 — 审视自己如何审视
    Level 4: 根基 — 将思维还原到第一性原理
    Level 5: 元递归 — 对递归审视本身进行审视
    """
    LEVEL_0_REACTIVE = 0
    LEVEL_1_MONITORING = 1
    LEVEL_2_CONTROL = 2
    LEVEL_3_RECURSIVE = 3
    LEVEL_4_FP_GROUNDED = 4
    LEVEL_5_META_RECURSIVE = 5

    @classmethod
    def describe(cls, level: "MetaCognitionLevel") -> str:
        descriptions = {
            cls.LEVEL_0_REACTIVE: "反应式：凭直觉直接响应，无自我审视",
            cls.LEVEL_1_MONITORING: "监控式：知道自己正在思考什么",
            cls.LEVEL_2_CONTROL: "控制式：能主动调整自己的思考策略",
            cls.LEVEL_3_RECURSIVE: "递归式：审视自己的审视过程",
            cls.LEVEL_4_FP_GROUNDED: "根基式：将所有思维还原到第一性原理验证",
            cls.LEVEL_5_META_RECURSIVE: "元递归式：对递归审视本身进行审视",
        }
        return descriptions.get(level, "未知层级")


class EpistemicStatus(Enum):
    """认知状态 — 基于第一性原理的信息可信度分类"""
    FIRST_PRINCIPLE = "first_principle"         # 第一性原理（不可再分的基本真理）
    LOGICAL_INFERENCE = "logical_inference"     # 逻辑推理（从原理推导）
    EMPIRICAL_OBSERVATION = "observation"       # 经验观察（可重复验证）
    SUPPORTED_HYPOTHESIS = "hypothesis"         # 有证据支撑的假设
    SPECULATION = "speculation"                 # 推测（无足够证据）
    ASSUMPTION = "assumption"                   # 假设（未经检验的前提）
    BIAS = "bias"                               # 认知偏差
    UNKNOWN = "unknown"                         # 未知
    CONTRADICTION = "contradiction"             # 自相矛盾

    @property
    def trustworthiness(self) -> float:
        """可信度评分 0-1，基于第一性原理的距离"""
        trust = {
            EpistemicStatus.FIRST_PRINCIPLE: 1.0,
            EpistemicStatus.LOGICAL_INFERENCE: 0.9,
            EpistemicStatus.EMPIRICAL_OBSERVATION: 0.8,
            EpistemicStatus.SUPPORTED_HYPOTHESIS: 0.5,
            EpistemicStatus.SPECULATION: 0.2,
            EpistemicStatus.ASSUMPTION: 0.1,
            EpistemicStatus.BIAS: 0.0,
            EpistemicStatus.UNKNOWN: 0.0,
            EpistemicStatus.CONTRADICTION: -0.5,
        }
        return trust.get(self, 0.0)


class FPCognitiveBias(Enum):
    """基于第一性原理检测的认知偏差类型"""
    FALSE_CERTAINTY = "false_certainty"                 # 虚假确定性
    UNEXAMINED_ASSUMPTION = "unexamined_assumption"     # 未经检验的假设
    ANALOGY_OVER_FUNDAMENTAL = "analogy_override"       # 类比替代第一性原理
    RECURSIVE_DEPTH_LIMIT = "recursive_depth_limit"     # 递归深度不足
    EPISTEMIC_MISCLASSIFY = "epistemic_misclassify"     # 认知状态分类错误
    CHAIN_BREAK = "logical_chain_break"                 # 逻辑链断裂
    FALSE_NECESSITY = "false_necessity"                 # 虚假必要性
    DEFAULT_THINKING = "default_thinking"               # 默认模式思维

# ════════════════════════════════════════════════════════════
# 核心数据类
# ════════════════════════════════════════════════════════════


@dataclass
class GroundedJudgment:
    """
    根基性判断 — 经过第一性原理验证的认知结论

    每个判断都记录了：
    - 从哪个第一性原理出发
    - 经过哪些推理步骤
    - 当前认知状态分类
    - 置信度和局限性
    """
    id: str = ""
    claim: str = ""                          # 判断陈述
    epistemic_status: EpistemicStatus = EpistemicStatus.UNKNOWN
    first_principles_used: List[str] = field(default_factory=list)  # 依赖的第一性原理
    reasoning_chain: List[str] = field(default_factory=list)        # 推理链
    assumptions: List[str] = field(default_factory=list)            # 识别的假设
    confidence: float = 0.0                 # 置信度 0-1
    meta_level: int = 0                     # 元认知层级
    biases_detected: List[str] = field(default_factory=list)
    alternatives: List[str] = field(default_factory=list)           # 替代解释
    falsification_test: str = ""             # 如果错了，怎么知道？
    timestamp: float = 0.0

    def to_dict(self) -> dict:
        return {
            "id": self.id[:8],
            "claim": self.claim[:60],
            "status": self.epistemic_status.value,
            "confidence": round(self.confidence, 3),
            "meta_level": self.meta_level,
            "principles": len(self.first_principles_used),
            "biases": self.biases_detected,
        }

@dataclass
class ThinkingTrace:
    """
    完整思维轨迹 — 记录一次从感知到决策的完整认知过程，
    包含第一性原理元认知的全程注解。

    这是"关于思考的完整记录"，可以被上层的元认知重新审视。
    """
    id: str = ""
    trigger: str = ""                         # 触发源
    initial_question: str = ""                # 初始问题
    judgments: List[GroundedJudgment] = field(default_factory=list)
    final_answer: str = ""                    # 最终答案
    overall_confidence: float = 0.0
    deepest_meta_level: int = 0               # 达到的最大元认知层级
    recursive_examinations: List[str] = field(default_factory=list)  # 递归审视记录
    unresolved_assumptions: List[str] = field(default_factory=list)
    cognitive_shift: str = ""                 # 思考过程中的认知转变
    duration_ms: float = 0.0
    timestamp: float = 0.0

    def to_dict(self) -> dict:
        return {
            "id": self.id[:8],
            "trigger": self.trigger[:40],
            "judgments": len(self.judgments),
            "meta_depth": self.deepest_meta_level,
            "confidence": round(self.overall_confidence, 3),
            "unresolved": len(self.unresolved_assumptions),
            "duration_ms": round(self.duration_ms, 1),
        }


@dataclass
class FPMetaState:
    """
    第一性原理元认知状态 — 系统的整体认知健康状态

    类比"认知体检报告"：当前思维的健康度、深度、偏差风险。
    """
    current_meta_level: int = 0
    average_confidence: float = 0.5
    epistemic_breakdown: Dict[str, int] = field(default_factory=dict)  # 认知状态分布
    active_biases: List[str] = field(default_factory=list)
    recursive_depth: int = 0                  # 当前递归深度
    total_traces: int = 0
    total_challenges: int = 0                 # 挑战假设的次数
    total_fp_groundings: int = 0             # 还原到第一性原理的次数
    dominant_epistemic: str = "unknown"
    thinking_clarity: float = 0.7            # 思维清晰度
    last_recursive_examination: str = ""

    def to_dict(self) -> dict:
        return {
            "meta_level": self.current_meta_level,
            "confidence": round(self.average_confidence, 2),
            "biases": self.active_biases,
            "depth": self.recursive_depth,
            "dominant_epistemic": self.dominant_epistemic,
            "clarity": round(self.thinking_clarity, 2),
        }

# ════════════════════════════════════════════════════════════
# 第一性原理元认知引擎 — 主类
# ════════════════════════════════════════════════════════════


class FirstPrinciplesMetaCognition:
    """
    第一性原理元认知引擎

    这是 LAAP 认知架构的"认知操作系统"核心。
    它将第一性原理推理与元认知监控深度融合，实现：

    1. 根基性思考监控 (Grounded Thinking Monitor)
       追踪每个思维片段的认知状态分类，确保推理有根基。

    2. 递归自审视 (Recursive Self-Examination)
       不仅仅思考，而是思考"自己如何思考"，并且审视这个审视过程本身。

    3. 认知偏差检测与纠正 (Bias Detection & Correction)
       基于第一性原理检测虚假确定性、未经检验的假设等偏差。

    4. 认知可信度评估 (Epistemic Trust Assessment)
       对每个判断进行认知状态分类，区分事实、推理、假设、推测。

    5. 认知策略调优 (Cognitive Strategy Optimization)
       根据元认知反馈动态调整思考策略，形成自我改进的认知循环。

    核心循环 (FP-Meta Loop):
       MONITOR → GROUND → VERIFY → RECURSE → ADJUST
    """

    def __init__(self, agent_id: str = ""):
        self.agent_id = agent_id
        self.state = FPMetaState()
        self.traces: List[ThinkingTrace] = []
        self._max_traces = 200
        self._current_trace: Optional[ThinkingTrace] = None
        self._start_time = time.time()

        # 已知的第一性原理库（核心信念）
        self._first_principles: Dict[str, List[str]] = {
            "logic": [
                "同一律: A = A（一个事物就是它自身）",
                "排中律: 一个命题要么为真要么为假",
                "矛盾律: 一个命题不能同时为真和假",
                "充足理由律: 任何真命题都有充足的理由",
            ],
            "epistemology": [
                "可知性: 世界在一定程度上可以被认知",
                "怀疑原则: 任何知识都可以被质疑",
                "证伪原则: 科学理论必须能被证伪",
                "奥卡姆剃刀: 如无必要勿增实体",
            ],
            "cognition": [
                "感知-行动循环: 认知始于感知，终于行动",
                "层级抽象: 复杂认知依赖层级化的概念抽象",
                "递归自省: 认知系统可以递归地审视自身",
            ],
            "computation": [
                "图灵完备: 可计算问题可用有限指令集解决",
                "信息守恒: 信息不会凭空产生或消失",
                "组合爆炸: 状态空间随复杂度指数增长",
            ],
        }

        # 认知状态分布统计
        self._epistemic_counts = {es.value: 0 for es in EpistemicStatus}
        logger.info(f"第一性原理元认知引擎初始化完成 [{agent_id[:8]}]")

    # ══════════════════════════════════════════════════════
    # 核心接口 — 供 Brain / Agent 调用
    # ══════════════════════════════════════════════════════

    def begin_trace(self, trigger: str, question: str) -> str:
        """开始一个新的思维轨迹记录"""
        trace = ThinkingTrace(
            id=str(uuid.uuid4())[:12],
            trigger=trigger,
            initial_question=question,
            timestamp=time.time(),
        )
        self._current_trace = trace
        logger.debug(f"开始思维轨迹: {trace.id} - {trigger[:40]}")
        return trace.id

    def end_trace(self, final_answer: str = "") -> Optional[ThinkingTrace]:
        """结束当前思维轨迹并存储"""
        if self._current_trace is None:
            return None
        trace = self._current_trace
        trace.final_answer = final_answer
        trace.duration_ms = (time.time() - trace.timestamp) * 1000
        trace.overall_confidence = self._compute_overall_confidence(trace)
        trace.deepest_meta_level = max((j.meta_level for j in trace.judgments), default=0)
        self.traces.append(trace)
        if len(self.traces) > self._max_traces:
            self.traces = self.traces[-self._max_traces:]
        self.state.total_traces = len(self.traces)
        self._current_trace = None
        logger.info(f"思维轨迹完成: {trace.id} depth={trace.deepest_meta_level} conf={trace.overall_confidence:.2f}")
        return trace

    def monitor_thinking(self, claim: str, context: Dict[str, Any] = None) -> GroundedJudgment:
        """
        核心方法1: 元认知监控 — 对一个思维片段进行根基性分析

        这是 FP-Meta Loop 的第一步 (MONITOR)。
        对输入的判断进行认知状态分类，识别假设，检测偏差。
        """
        t0 = time.time()

        # 1. 识别判断中的假设
        assumptions = self._identify_assumptions_in_claim(claim)

        # 2. 分类认知状态
        status, confidence = self._classify_epistemic_status(claim, assumptions)

        # 3. 检测认知偏差
        biases = self._detect_fp_biases(claim, status, assumptions)

        # 4. 查找可用的第一性原理
        principles_used = self._find_relevant_principles(claim)

        # 5. 生成证伪测试
        falsification = self._generate_falsification(claim, status)

        # 6. 构建根基性判断
        judgment = GroundedJudgment(
            id=str(uuid.uuid4())[:8],
            claim=claim,
            epistemic_status=status,
            first_principles_used=principles_used,
            assumptions=assumptions,
            confidence=confidence,
            meta_level=self.state.current_meta_level,
            biases_detected=biases,
            falsification_test=falsification,
            timestamp=time.time(),
        )

        # 7. 更新统计
        self._epistemic_counts[status.value] = self._epistemic_counts.get(status.value, 0) + 1
        if self._current_trace:
            self._current_trace.judgments.append(judgment)

        # 8. 更新状态
        self._update_state_from_judgment(judgment)

        logger.debug(f"监控判断: {claim[:40]} -> {status.value} conf={confidence:.2f} biases={len(biases)}")
        return judgment

    def ground_judgment(self, judgment: GroundedJudgment,
                          max_recursion: int = 3) -> GroundedJudgment:
        """
        核心方法2: 根基性还原 (GROUND)

        将判断递归地还原到第一性原理。
        如果判断的置信度低或是假设，就追问"为什么"直到触及第一性原理。

        这是 FP-Meta Loop 的第二步。

        注意：返回新的 GroundedJudgment 实例，不修改输入 judgment，
        以便调用方对比还原前后的状态差异。
        """
        if judgment.epistemic_status == EpistemicStatus.FIRST_PRINCIPLE:
            return judgment  # 已经是第一性原理，无需还原

        # 创建副本以保留原始 judgment 供调用方对比
        import copy
        grounded = copy.deepcopy(judgment)

        t0 = time.time()
        depth = 0
        current = grounded
        grounding_chain = [grounded.claim]

        while depth < max_recursion:
            # 对当前的假设追问"为什么"
            why_questions = self._ask_why(current)
            if not why_questions:
                break

            # 分析每个"为什么"的答案
            all_grounded = True
            for q in why_questions:
                ans_status, _ = self._classify_epistemic_status(q, [])
                grounding_chain.append(f"{q} -> {ans_status.value}")
                if ans_status != EpistemicStatus.FIRST_PRINCIPLE:
                    all_grounded = False

            if all_grounded:
                break
            depth += 1

        # 仅更新还原后的副本，不修改原始 judgment
        grounded.meta_level = max(grounded.meta_level, depth)
        grounded.first_principles_used.extend(grounding_chain[-3:])
        grounded.confidence = min(1.0, grounded.confidence + depth * 0.1)
        self.state.total_fp_groundings += 1
        self.state.recursive_depth = max(self.state.recursive_depth, depth)

        logger.info(f"根基还原: depth={depth}, chain={len(grounding_chain)} steps")
        return grounded

    def recursive_examine(self, trace: Optional[ThinkingTrace] = None,
                            max_depth: int = 3) -> Dict[str, Any]:
        """
        核心方法3: 递归自审视 (RECURSE)

        对思维轨迹进行递归审视：
        - Level 1: 审视思维内容
        - Level 2: 审视审视过程本身
        - Level 3: 对审视的审视进行审视

        这是 FP-Meta Loop 的第四步，也是最具 LAAP 特色的能力。
        """
        if trace is None:
            trace = self._current_trace
        if trace is None:
            return {"error": "没有可审视的思维轨迹"}

        examination_log = []
        current_level = 1

        while current_level <= max_depth:
            level_results = {
                "level": current_level,
                "examination": self._examine_at_level(trace, current_level),
                "findings": [],
                "confidence_delta": 0.0,
            }

            if current_level == 1:
                # Level 1: 审视思维内容
                findings = self._examine_content(trace)
            elif current_level == 2:
                # Level 2: 审视审视过程
                findings = self._examine_process(trace, examination_log)
            else:
                # Level 3+: 元审视
                findings = self._meta_examine(trace, examination_log)

            level_results["findings"] = findings
            examination_log.append(level_results)

            # 如果没有新发现，停止递归
            if not findings:
                break

            current_level += 1

        # 更新轨迹
        trace.recursive_examinations = [
            f"L{e['level']}: {len(e['findings'])} findings"
            for e in examination_log
        ]
        trace.deepest_meta_level = max(trace.deepest_meta_level, current_level - 1)
        self.state.current_meta_level = max(self.state.current_meta_level, current_level - 1)

        result = {
            "trace_id": trace.id,
            "recursive_depth": current_level - 1,
            "examinations": examination_log,
            "summary": self._summarize_examination(examination_log),
        }

        logger.info(f"递归自审视完成: depth={current_level-1}, {len(examination_log)} levels")
        return result

    def evaluate_decision(self, decision, outcome=None):
        judgment = self.monitor_thinking(decision.get("decision",""))
        grounded = self.ground_judgment(judgment)
        bias_score = len(grounded.biases_detected) / max(1, len(FPCognitiveBias))
        quality = grounded.confidence * (1 - bias_score)
        if outcome:
            quality = quality * 0.7 + outcome.get("score",0.5) * 0.3
        return {
            "quality": round(quality, 3),
            "status": grounded.epistemic_status.value,
            "biases": grounded.biases_detected,
        }


    def get_fp_meta_prompt_block(self) -> str:
        parts = ["[第一性原理元认知状态]", ""]
        parts.append(f"当前元认知层级: {self.state.current_meta_level}")
        parts.append(f"思维清晰度: {self.state.thinking_clarity:.0%}")
        parts.append(f"主导认知状态: {self.state.dominant_epistemic}")
        parts.append("")
        parts.append("[认知原则]")
        parts.append("- 每个结论都要追溯其根基")
        parts.append("- 区分事实、推理、假设、推测")
        parts.append("- 当不确定性高时递归追问")
        return "\n".join(parts)

    def introspect(self) -> str:
        s = self.state
        parts = ["=" * 48]
        parts.append("  第一性原理元认知状态报告")
        parts.append("=" * 48)
        parts.append(f"元认知层级: {s.current_meta_level}")
        parts.append(f"递归深度: {s.recursive_depth}")
        parts.append(f"思维清晰度: {s.thinking_clarity:.0%}")
        parts.append(f"平均置信度: {s.average_confidence:.0%}")
        parts.append("")
        parts.append("认知状态分布:")
        total = sum(self._epistemic_counts.values()) or 1
        for st, cnt in sorted(self._epistemic_counts.items()):
            if cnt > 0:
                pct = cnt / total * 100
                parts.append(f"  {st:25s} {cnt:3d} ({pct:.0f}%)")
        if s.active_biases:
            parts.append("活跃偏差:")
            for b in s.active_biases:
                parts.append(f"  ! {b}")
        parts.append(f"总轨迹数: {s.total_traces}")
        parts.append(f"根基还原: {s.total_fp_groundings}")
        return "\n".join(parts)



    # ══════════════════════════════════════════════════════
    # 内部方法
    # ══════════════════════════════════════════════════════

    def _identify_assumptions_in_claim(self, claim: str) -> List[str]:
        assumptions = []
        text = claim.lower()
        patterns = [
            ("隐含价值判断", ["应该", "必须", "一定", "ought", "must", "should"]),
            ("隐含全称量化", ["所有", "总是", "every", "always", "never"]),
            ("隐含因果关系", ["因为", "所以", "因此", "because", "therefore"]),
            ("隐含能力限制", ["不能", "不可能", "无法", "cannot", "impossible"]),
            ("隐含路径依赖", ["传统", "标准", "常规", "traditional", "standard"]),
        ]
        for label, keywords in patterns:
            if any(k in text for k in keywords):
                assumptions.append(f"{label}: 陈述中包含隐含前提")
        if len(claim) > 200:
            assumptions.append("信息过载: 陈述过长，可能包含未检验的细节假设")
        return assumptions

    def _classify_epistemic_status(self, claim: str, assumptions: List[str]) -> Tuple[EpistemicStatus, float]:
        # 1. 第一性原理（不可再分的基本真理）
        if self._is_first_principle(claim):
            return EpistemicStatus.FIRST_PRINCIPLE, 0.95
        # 2. 自相矛盾
        if self._is_contradiction(claim):
            return EpistemicStatus.CONTRADICTION, 0.0
        # 3. 条件式假设推理（"如果...那么..." 形式）
        if self._is_conditional_hypothesis(claim):
            return EpistemicStatus.SUPPORTED_HYPOTHESIS, 0.5
        # 4. 经验观察（可重复验证的实测陈述）
        if self._is_observable(claim):
            return EpistemicStatus.EMPIRICAL_OBSERVATION, 0.8
        # 5. 推测（使用不确定性语言且无具体证据）
        if self._is_speculation(claim):
            return EpistemicStatus.SPECULATION, 0.2
        # 6. 未经检验的假设（以"假设"开头的断言式陈述）
        if self._is_assumption(claim):
            return EpistemicStatus.ASSUMPTION, 0.1
        # 7. 默认分类（基于隐含假设数量与陈述长度）
        if len(assumptions) == 0 and len(claim) > 20:
            return EpistemicStatus.LOGICAL_INFERENCE, 0.7
        if len(assumptions) <= 2:
            return EpistemicStatus.SUPPORTED_HYPOTHESIS, 0.5
        if len(assumptions) <= 4:
            return EpistemicStatus.SPECULATION, 0.3
        if self._contains_bias_markers(claim):
            return EpistemicStatus.BIAS, 0.1
        return EpistemicStatus.ASSUMPTION, 0.2

    def _is_first_principle(self, claim: str) -> bool:
        text = claim.lower()
        # 1. 直接陈述某个第一性原理：以原理名开头（如"矛盾律：..."）
        principle_starts = ["矛盾律", "排中律", "同一律", "充足理由律",
                            "law of", "axiom of"]
        if any(text.startswith(p.lower()) for p in principle_starts):
            return True
        # 2. 完全包含某个原理的描述（标准化中英文冒号与空格后再比较前 30 字符）
        for domain, principles in self._first_principles.items():
            for p in principles:
                p_norm = p.lower()[:30].replace(":", "：").replace(" ", "")
                text_norm = text.replace(":", "：").replace(" ", "")
                if p_norm in text_norm:
                    return True
        # 3. 包含第一性原理标记词
        fp_markers = ["定律", "公理", "原理", "law", "axiom", "定理",
                      "不可再分", "基本真理", "self-evident"]
        if any(m in text for m in fp_markers):
            return True
        return False

    def _is_contradiction(self, claim: str) -> bool:
        text = claim.lower()
        # 1. 直接的矛盾措辞
        direct_markers = [
            "既是真的又是假的", "既真又假", "既为真又为假",
            "同时为真和假", "同时为真与假", "同时是真的又是假的",
            "既存在又不存在", "self-contradict", "contradict itself",
            "既是真又是假", "又真又假",
        ]
        if any(m in text for m in direct_markers):
            return True
        # 2. "既...又..." 模式 + 矛盾对（同时成立两个互斥属性）
        if "既" in text and "又" in text:
            opposite_pairs = [("真", "假"), ("对", "错"), ("是", "非"),
                              ("存在", "不存在"), ("有", "没有")]
            for a, b in opposite_pairs:
                if a in text and b in text:
                    return True
        # 3. 标准矛盾对（处理子串重叠：先去除 b 再查 a 是否独立出现）
        contradict_pairs = [
            ("是", "不是"), ("有", "没有"), ("能", "不能"),
            ("存在", "不存在"), ("true", "false"), ("always", "never"),
        ]
        for a, b in contradict_pairs:
            if b in text:
                stripped = text.replace(b, "")
                if a in stripped:
                    return True
        return False

    def _is_conditional_hypothesis(self, claim: str) -> bool:
        """条件式假设推理：'如果...那么...', '假如...就...' 等形式"""
        markers = ["如果", "假如", "倘若", "若", "if ", "assuming that"]
        return any(m in claim.lower() for m in markers)

    def _is_speculation(self, claim: str) -> bool:
        """推测：使用明确的不确定性语言但无具体证据支撑"""
        markers = ["也许", "或许", "可能会", "也许会",
                   "maybe", "perhaps", "might", "could be"]
        return any(m in claim.lower() for m in markers)

    def _is_assumption(self, claim: str) -> bool:
        """未经检验的假设：以"假设"作为动词开头，或包含"我们认为"等断言"""
        text = claim.strip()
        # 注意区分：'假设' 作为动词（开头）引入一个待检验前提 vs 作为名词（"这个假设..."）指代已有假设
        if text.startswith("假设"):
            return True
        assertion_markers = ["我们认为", "我假设", "我假定"]
        if any(m in text for m in assertion_markers):
            return True
        return False

    def _is_observable(self, claim: str) -> bool:
        obs_markers = ["观察到", "数据显示", "实验表明", "observed", "measured",
                       "数据显示", "统计表明", "根据记录", "detected"]
        return any(m in claim.lower() for m in obs_markers)

    def _contains_bias_markers(self, claim: str) -> bool:
        bias_markers = ["绝对", "毫无疑问", "100%", "definitely",
                        "obviously", "clearly", "everyone knows"]
        return sum(1 for m in bias_markers if m in claim.lower()) >= 2

    def _detect_fp_biases(self, claim: str, status: EpistemicStatus,
                          assumptions: List[str]) -> List[str]:
        biases = []
        # FP-specific biases (original)
        if self._is_overconfident(claim, status):
            biases.append(FPCognitiveBias.FALSE_CERTAINTY.value)
        # 注意：不再依据 "len(assumptions)==0" 推断 UNEXAMINED_ASSUMPTION，
        # 因为 "未检测到隐含假设" ≠ "存在未检验的假设"。
        # 真正的未检验假设检测由下方 _has_unexamined_assumption_bias
        # 通过具体措辞（"行业标准"、"根据经验" 等）识别，避免对干净的事实陈述误报。
        if self._uses_analogy_instead_of_fp(claim):
            biases.append(FPCognitiveBias.ANALOGY_OVER_FUNDAMENTAL.value)
        # Classic cognitive biases (additive, by canonical name)
        for name, detector in (
            ("overconfidence", self._has_overconfidence_bias),
            ("confirmation", self._has_confirmation_bias),
            ("anchoring", self._has_anchoring_bias),
            ("availability", self._has_availability_bias),
            ("hasty_generalization", self._has_hasty_generalization_bias),
            ("sunk_cost", self._has_sunk_cost_bias),
            ("recency_bias", self._has_recency_bias),
            ("unexamined_assumption", self._has_unexamined_assumption_bias),
            ("false_certainty", self._has_false_certainty_bias),
            ("analogy_override", self._uses_analogy_instead_of_fp),
        ):
            if detector(claim) and name not in biases:
                biases.append(name)
        return biases

    def _has_unexamined_assumption_bias(self, claim: str) -> bool:
        """依赖行业惯例、经验、常识等未经检验的假设。"""
        markers = ["行业标准", "大家都是", "通常都是", "根据经验",
                   "经验告诉我", "常识", "一直都是这么做的",
                   "industry standard", "convention"]
        return any(m in claim.lower() for m in markers)

    def _has_false_certainty_bias(self, claim: str) -> bool:
        """将经验性判断断言为必然结论。"""
        markers = ["肯定能", "一定能", "肯定会", "必然",
                   "肯定会成功", "肯定能解决"]
        return any(m in claim for m in markers)

    def _is_overconfident(self, claim: str, status: EpistemicStatus) -> bool:
        if status.trustworthiness < 0.5:
            overconfident_words = ["确定", "肯定", "一定", "certain", "definite",
                                   "毫无疑问", "绝对", "absolutely"]
            if any(w in claim.lower() for w in overconfident_words):
                return True
        return False

    def _uses_analogy_instead_of_fp(self, claim: str) -> bool:
        analogy_markers = ["就像", "好比", "类比", "similar to", "like",
                           "analogous", "同样的道理"]
        fp_markers = ["因为", "所以", "推理", "therefore", "thus", "推导"]
        has_analogy = any(m in claim.lower() for m in analogy_markers)
        has_fp = any(m in claim.lower() for m in fp_markers)
        return has_analogy and not has_fp

    def _has_overconfidence_bias(self, claim: str) -> bool:
        """绝对化、100% 等过度自信措辞（不限认知状态）。"""
        markers = ["绝对", "肯定", "毫无疑问", "100%", "一定会", "绝对不会",
                   "certainly", "definitely", "must be"]
        return any(m in claim.lower() for m in markers)

    def _has_confirmation_bias(self, claim: str) -> bool:
        """只引用支持自己观点的证据、声称无反例。"""
        markers = ["支持我的观点", "支持我的", "没有反例", "没有任何反例",
                   "完美解释", "都支持"]
        return any(m in claim for m in markers)

    def _has_anchoring_bias(self, claim: str) -> bool:
        """以先前数值/估计为锚点进行微调。"""
        markers = ["上次", "上次估计", "上次我们估计", "差不多", "大概在",
                   "上次的价格", "之前的报价"]
        return any(m in claim for m in markers)

    def _has_availability_bias(self, claim: str) -> bool:
        """以近期易回想起的个例作为决策依据。"""
        markers = ["昨天刚看到", "刚看到", "前几天", "最近看到",
                   "i recently", "i just saw"]
        return any(m in claim.lower() for m in markers)

    def _has_hasty_generalization_bias(self, claim: str) -> bool:
        """由少数样本推出全称结论。"""
        markers = ["所有用户", "所有", "每次都", "也一定能", "肯定有效",
                   "every", "all users", "always works"]
        has_quantifier = any(m in claim for m in ["所有", "每次", "也一定"])
        has_small_sample = bool(re.search(r"[一二两三四五1-5]\s*(个|次|名)", claim))
        return has_quantifier or ("肯定有效" in claim and "成功案例" in claim)

    def _has_sunk_cost_bias(self, claim: str) -> bool:
        """以已投入资源为由继续投入。"""
        markers = ["投入了这么多", "投入了这么多资源", "放弃太可惜",
                   "已经投入", "sunk cost", "已经花了"]
        return any(m in claim for m in markers)

    def _has_recency_bias(self, claim: str) -> bool:
        """以最近几次结果推断未来。"""
        markers = ["最近几次都", "最近都", "最近几次", "上次成功"]
        return any(m in claim for m in markers)

    def _find_relevant_principles(self, claim: str) -> List[str]:
        relevant = []
        for domain, principles in self._first_principles.items():
            for p in principles:
                keywords = p.lower().split()[:4]
                if any(k in claim.lower() for k in keywords):
                    relevant.append(p)
        return relevant[:3]

    def _generate_falsification(self, claim: str, status: EpistemicStatus) -> str:
        if status == EpistemicStatus.FIRST_PRINCIPLE:
            return "第一性原理不可证伪（它是推理的起点）"
        if status == EpistemicStatus.EMPIRICAL_OBSERVATION:
            return "可以通过重复实验验证"
        if status == EpistemicStatus.LOGICAL_INFERENCE:
            return "检查推理链的每一步逻辑有效性"
        return f"找反例: 如果'{claim[:40]}'不成立，需要什么证据？"

    def _ask_why(self, judgment: GroundedJudgment) -> List[str]:
        questions = []
        for a in judgment.assumptions[:3]:
            questions.append(f"为什么假设'{a[:30]}'成立？")
        if not questions:
            questions.append(f"'{judgment.claim[:40]}'的前提是什么？")
        return questions



    def _update_state_from_judgment(self, judgment: GroundedJudgment):
        self.state.average_confidence = (
            self.state.average_confidence * 0.95 + judgment.confidence * 0.05
        )
        if judgment.biases_detected:
            for b in judgment.biases_detected:
                if b not in self.state.active_biases:
                    self.state.active_biases.append(b)
        status_counts = self._epistemic_counts
        if status_counts:
            dominant = max(status_counts, key=status_counts.get)
            self.state.dominant_epistemic = dominant

    def _compute_overall_confidence(self, trace: ThinkingTrace) -> float:
        if not trace.judgments:
            return 0.0
        return sum(j.confidence for j in trace.judgments) / len(trace.judgments)

    def _examine_at_level(self, trace: ThinkingTrace, level: int) -> str:
        descriptions = {
            1: "审视思维内容的质量和一致性",
            2: "审视审视过程本身的完整性",
            3: "对元认知过程进行元-审视",
        }
        return descriptions.get(level, f"Level {level} 递归审视")

    def _examine_content(self, trace: ThinkingTrace) -> List[str]:
        findings = []
        for j in trace.judgments:
            if j.epistemic_status == EpistemicStatus.ASSUMPTION:
                findings.append(f"未检验的假设: {j.claim[:40]}")
            if j.epistemic_status == EpistemicStatus.BIAS:
                findings.append(f"认知偏差: {j.claim[:40]}")
            if j.epistemic_status == EpistemicStatus.CONTRADICTION:
                findings.append(f"自相矛盾: {j.claim[:40]}")
        if not findings:
            findings.append("思维内容基本一致，无明显问题")
        return findings

    def _examine_process(self, trace: ThinkingTrace, logs: List) -> List[str]:
        findings = []
        if len(trace.judgments) < 3:
            findings.append("推理步骤过少，可能存在跳跃")
        high_conf_low_status = [
            j for j in trace.judgments
            if j.confidence > 0.8 and j.epistemic_status.trustworthiness < 0.3
        ]
        if high_conf_low_status:
            findings.append(f"检测到{len(high_conf_low_status)}个高置信度但低可信度的判断")
        return findings

    def _meta_examine(self, trace: ThinkingTrace, logs: List) -> List[str]:
        findings = []
        if logs:
            level1_findings = logs[-1].get("findings", []) if logs else []
            if len(level1_findings) == len(logs[-2].get("findings", [])) if len(logs) > 1 else False:
                findings.append("递归审视陷入循环，需要外部视角")
        return findings

    def _summarize_examination(self, logs: List) -> str:
        if not logs:
            return "未进行递归审视"
        total_findings = sum(len(e["findings"]) for e in logs)
        return f"递归审视{len(logs)}层, 共{total_findings}项发现"

    def _generate_recommendation(self, judgment: GroundedJudgment, quality: float) -> str:
        if quality < 0.3:
            return "建议回退到第一性原理重新推理"
        if quality < 0.6:
            return "建议增加递归审视深度，检验未检验的假设"
        if judgment.assumptions:
            return "可以接受，但标注了待检验的假设"
        return "判断质量良好，基于可靠根基"

