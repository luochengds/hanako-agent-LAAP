"""
LAAP AGI — Meta-Cognitive Monitor (元认知监控器)

实现对认知过程的实时监控、推理分析、偏差检测和自我反思。
这是意识工程的核心模块，支持智能体对自身思考过程的审视。

设计原则：
  - 实时监控：追踪每个认知片段的完整生命周期
  - 偏差检测：识别常见认知偏差（确认偏差、锚定效应、情感偏差等）
  - 自动反思：基于阈值触发自我反思机制
  - 可扩展：支持 LLM 深度反思和自定义监控策略
"""

from __future__ import annotations

import json
import os
import time
import uuid
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


class ReflectionTrigger(Enum):
    """反思触发类型"""
    POST_ACTION = "post_action"
    ERROR_DETECTED = "error_detected"
    CONFIDENCE_LOW = "confidence_low"
    GOAL_CONFLICT = "goal_conflict"
    TIME_BASED = "time_based"
    USER_REQUEST = "user_request"


@dataclass
class CognitiveEpisode:
    """认知片段 — 记录一次完整的思考-行动周期"""
    episode_id: str = field(default_factory=lambda: f"ep_{uuid.uuid4().hex[:8]}")
    timestamp: float = field(default_factory=time.time)
    context: str = ""
    reasoning_trace: List[str] = field(default_factory=list)
    action_taken: str = ""
    outcome: str = ""
    confidence: float = 0.5
    emotional_state: str = "neutral"
    duration_ms: float = 0.0
    _start_perf: float = field(default_factory=time.perf_counter, repr=False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "episode_id": self.episode_id,
            "timestamp": self.timestamp,
            "context": self.context[:100],
            "reasoning_steps": len(self.reasoning_trace),
            "action_taken": self.action_taken[:60],
            "outcome": self.outcome[:60],
            "confidence": round(self.confidence, 3),
            "emotional_state": self.emotional_state,
            "duration_ms": round(self.duration_ms, 1),
        }


class MetaCognitiveMonitor:
    """
    元认知监控器 — 监控和分析智能体的认知过程

    核心能力：
    1. 认知片段追踪：记录思考-行动周期的完整轨迹
    2. 推理分析：分析推理步骤、目标导向、替代方案考虑
    3. 偏差检测：检测确认偏差、锚定效应、循环推理等
    4. 自动反思：基于阈值触发自我反思
    5. 性能评估：生成自我报告和学习要点
    """

    # 反思触发阈值
    LOW_CONFIDENCE_THRESHOLD = 0.3
    HIGH_CONFIDENCE_THRESHOLD = 0.9
    MIN_REASONING_STEPS = 2
    MAX_EPISODES_BEFORE_REFLECTION = 5

    def __init__(self, llm_client: Optional[Any] = None):
        self.llm_client = llm_client
        self.episodes: List[CognitiveEpisode] = []
        self.reflections: List[Dict[str, Any]] = []
        self.current_episode: Optional[CognitiveEpisode] = None
        self.cognitive_biases_detected: List[Dict[str, Any]] = []
        self.performance_metrics: Dict[str, float] = {
            "total_episodes": 0.0,
            "successful_episodes": 0.0,
            "average_confidence": 0.5,
            "average_duration_ms": 0.0,
            "total_reflections": 0.0,
            "biases_found": 0.0,
            "initial_success_rate": 0.5,
        }

    def start_episode(self, context: str = "") -> str:
        """开始新的认知片段"""
        episode = CognitiveEpisode(context=context)
        self.current_episode = episode
        return episode.episode_id

    def record_reasoning(self, step: str) -> None:
        """记录推理步骤"""
        if self.current_episode:
            self.current_episode.reasoning_trace.append(step)

    def record_action(self, action: str, outcome: str, confidence: float = 0.5) -> None:
        """记录行动和结果"""
        if self.current_episode:
            self.current_episode.action_taken = action
            self.current_episode.outcome = outcome
            self.current_episode.confidence = confidence

    def end_episode(self) -> Optional[CognitiveEpisode]:
        """结束认知片段，更新指标，检查自动反思"""
        if self.current_episode is None:
            return None

        episode = self.current_episode
        episode.duration_ms = (time.perf_counter() - episode._start_perf) * 1000
        self.episodes.append(episode)
        self.current_episode = None

        self._update_metrics(episode)
        self._detect_biases(episode)
        self._check_auto_reflection(episode)

        return episode

    def _update_metrics(self, episode: CognitiveEpisode) -> None:
        """更新性能指标"""
        self.performance_metrics["total_episodes"] += 1
        if "success" in episode.outcome.lower() or episode.confidence >= 0.7:
            self.performance_metrics["successful_episodes"] += 1
        self.performance_metrics["average_confidence"] = (
            self.performance_metrics["average_confidence"] * 0.9 +
            episode.confidence * 0.1
        )
        self.performance_metrics["average_duration_ms"] = (
            self.performance_metrics["average_duration_ms"] * 0.9 +
            episode.duration_ms * 0.1
        )

    def _check_auto_reflection(self, episode: CognitiveEpisode) -> None:
        """检查是否需要自动触发反思"""
        triggers = []

        if episode.confidence < self.LOW_CONFIDENCE_THRESHOLD:
            triggers.append(ReflectionTrigger.CONFIDENCE_LOW)

        if "error" in episode.outcome.lower() or "fail" in episode.outcome.lower():
            triggers.append(ReflectionTrigger.ERROR_DETECTED)

        if len(self.episodes) % self.MAX_EPISODES_BEFORE_REFLECTION == 0:
            triggers.append(ReflectionTrigger.TIME_BASED)

        if triggers:
            self._perform_reflection(episode, triggers)

    def _perform_reflection(self, episode: CognitiveEpisode,
                            triggers: List[ReflectionTrigger]) -> Dict[str, Any]:
        """执行反思（包含推理分析和偏差检测）"""
        reflection = {
            "reflection_id": f"refl_{uuid.uuid4().hex[:8]}",
            "episode_id": episode.episode_id,
            "triggers": [t.value for t in triggers],
            "timestamp": time.time(),
            "reasoning_analysis": self._analyze_reasoning(episode),
            "circularity_detected": self._detect_circularity(episode),
            "biases_detected": self._detect_biases(episode),
        }

        if self.llm_client:
            llm_insight = self._llm_reflection(episode)
            reflection["llm_insight"] = llm_insight

        reflection["learning_points"] = self._extract_learning_points(episode)
        reflection["summary"] = self._summarize_biases(reflection["biases_detected"])

        self.reflections.append(reflection)
        self.performance_metrics["total_reflections"] += 1
        self.performance_metrics["biases_found"] += len(reflection["biases_detected"])

        return reflection

    def _analyze_reasoning(self, episode: CognitiveEpisode) -> Dict[str, Any]:
        """分析推理过程"""
        steps = episode.reasoning_trace
        reasoning_text = "\n".join(steps)

        has_goal_mention = any(
            keyword in step.lower() for step in steps
            for keyword in ["goal", "objective", "target", "目的", "目标"]
        )

        has_alternatives = any(
            keyword in step.lower() for step in steps
            for keyword in ["alternative", "option", "choice", "备选", "方案"]
        )

        has_evidence = any(
            keyword in step.lower() for step in steps
            for keyword in ["evidence", "data", "fact", "evidence", "数据", "事实"]
        )

        depth_score = min(1.0, len(steps) / 10)

        return {
            "step_count": len(steps),
            "has_goal_mention": has_goal_mention,
            "has_alternatives": has_alternatives,
            "has_evidence": has_evidence,
            "depth_score": round(depth_score, 2),
            "reasoning_length": len(reasoning_text),
        }

    def _detect_circularity(self, episode: CognitiveEpisode) -> bool:
        """检测循环推理"""
        steps = episode.reasoning_trace
        if len(steps) < 3:
            return False

        normalized_steps = [step.lower().strip() for step in steps]

        for i in range(len(steps) - 2):
            if normalized_steps[i] in normalized_steps[i + 2]:
                return True

        first_keywords = set(normalized_steps[0].split()[:3])
        last_step = normalized_steps[-1]
        if any(kw in last_step for kw in first_keywords):
            return True

        entities = []
        for step in normalized_steps:
            for char in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz":
                if char in step:
                    entities.append(char.upper())
        if len(entities) >= 3:
            seen = {}
            for idx, entity in enumerate(entities):
                if entity in seen:
                    if idx - seen[entity] >= 2:
                        return True
                seen[entity] = idx

        for i in range(len(steps) - 2):
            step1 = normalized_steps[i]
            step3 = normalized_steps[i + 2]
            for char in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz":
                if char in step1 and char in step3:
                    return True

        return False

    def _detect_biases(self, episode: CognitiveEpisode) -> List[str]:
        """检测认知偏差"""
        biases = []
        reasoning_text = "\n".join(episode.reasoning_trace).lower()

        confirmation_markers = [
            "支持我的观点", "没有反例", "完美解释", "都支持",
            "confirms my", "supports my", "no counterexample"
        ]
        if any(marker in reasoning_text for marker in confirmation_markers):
            biases.append("confirmation_bias")

        anchoring_markers = [
            "上次", "之前的", "基准", "锚点",
            "previous", "baseline", "anchor"
        ]
        if any(marker in reasoning_text for marker in anchoring_markers):
            biases.append("anchoring_bias")

        emotional_markers = [
            "我觉得", "我认为", "直觉告诉我", "感觉",
            "i feel", "i think", "intuition"
        ]
        emotional_count = sum(1 for marker in emotional_markers if marker in reasoning_text)
        if emotional_count >= 2 and episode.confidence > 0.7:
            biases.append("emotional_bias")

        overconfidence_markers = [
            "绝对", "肯定", "毫无疑问", "100%",
            "definitely", "absolutely", "without doubt"
        ]
        if episode.confidence > self.HIGH_CONFIDENCE_THRESHOLD:
            if any(marker in reasoning_text for marker in overconfidence_markers):
                biases.append("overconfidence")

        if len(episode.reasoning_trace) < self.MIN_REASONING_STEPS:
            biases.append("insufficient_reasoning")

        if biases:
            self.cognitive_biases_detected.append({
                "episode_id": episode.episode_id,
                "biases": biases,
                "timestamp": time.time(),
            })

        return biases

    def _llm_reflection(self, episode: CognitiveEpisode) -> str:
        """使用 LLM 进行深度反思"""
        if not self.llm_client:
            return ""

        prompt = f"""
请分析以下认知片段，进行深度反思：

推理轨迹：
{chr(10).join(episode.reasoning_trace)}

行动：{episode.action_taken}
结果：{episode.outcome}
置信度：{episode.confidence}

请回答：
1. 推理过程中有什么逻辑漏洞？
2. 是否存在认知偏差？
3. 如果重新思考，会采取什么不同的策略？
4. 从这次经验中学到了什么？

请用简洁的中文回答。
"""

        try:
            response = self.llm_client.complete(prompt)
            return response[:500]
        except Exception:
            return ""

    def get_self_report(self) -> Dict[str, Any]:
        """生成自我报告"""
        recent_episodes = self.episodes[-10:]
        
        if self.performance_metrics["total_episodes"] > 0:
            success_rate = (
                self.performance_metrics["successful_episodes"] /
                self.performance_metrics["total_episodes"]
            )
        else:
            success_rate = self.performance_metrics.get("initial_success_rate", 0.5)

        recent_biases = [
            b for b in self.cognitive_biases_detected[-20:]
        ]
        bias_summary = {}
        for entry in recent_biases:
            for bias in entry["biases"]:
                bias_summary[bias] = bias_summary.get(bias, 0) + 1

        return {
            "meta_cognitive_report": {
                "total_episodes": int(self.performance_metrics["total_episodes"]),
                "success_rate": round(success_rate, 2),
                "average_confidence": round(self.performance_metrics["average_confidence"], 2),
                "average_duration_ms": round(self.performance_metrics["average_duration_ms"], 1),
                "total_reflections": int(self.performance_metrics["total_reflections"]),
                "recent_episodes": len(recent_episodes),
            },
            "bias_distribution": bias_summary,
            "learning_points": self._extract_learning_points(recent_episodes[-1]) if recent_episodes else [],
        }

    def _summarize_biases(self, biases: List[str]) -> str:
        """总结常见偏差"""
        bias_descriptions = {
            "confirmation_bias": "确认偏差：倾向于寻找支持自己观点的证据",
            "anchoring_bias": "锚定效应：过度依赖初始信息",
            "emotional_bias": "情感偏差：基于情绪而非理性做决策",
            "overconfidence": "过度自信：对判断过于确定",
            "insufficient_reasoning": "推理不足：思考步骤太少",
        }

        if not biases:
            return "未检测到明显认知偏差"

        return "; ".join(bias_descriptions.get(b, b) for b in biases)

    def _extract_learning_points(self, episode: CognitiveEpisode) -> List[str]:
        """提取学习要点"""
        points = []

        if episode.confidence < self.LOW_CONFIDENCE_THRESHOLD:
            points.append("置信度低，建议收集更多证据后再做决策")

        if len(episode.reasoning_trace) < self.MIN_REASONING_STEPS:
            points.append("推理步骤不足，建议增加思考深度")

        if "error" in episode.outcome.lower():
            points.append(f"行动失败：{episode.outcome[:50]}")

        if episode.confidence > 0.8 and "success" in episode.outcome.lower():
            points.append("高置信度且成功，策略有效")

        if self._detect_circularity(episode):
            points.append("检测到循环推理，建议重新梳理逻辑")

        return points

    def generate_introspection_prompt(self) -> str:
        """生成内省提示"""
        mc = self.performance_metrics
        success_rate = mc["successful_episodes"] / max(1, mc["total_episodes"])

        parts = [
            "【元认知内省提示】",
            f"- 累计完成 {int(mc['total_episodes'])} 个认知片段",
            f"- 成功率: {success_rate:.0%}",
            f"- 平均置信度: {mc['average_confidence']:.0%}",
            f"- 平均耗时: {mc['average_duration_ms']:.0f}ms",
        ]

        recent_biases = [b for b in self.cognitive_biases_detected[-20:]]
        bias_summary = {}
        for entry in recent_biases:
            for bias in entry["biases"]:
                bias_summary[bias] = bias_summary.get(bias, 0) + 1

        if bias_summary:
            top_bias = max(bias_summary, key=bias_summary.get)
            parts.append(f"- 最常见偏差: {top_bias} ({bias_summary[top_bias]}次)")

        if self.episodes:
            learning = self._extract_learning_points(self.episodes[-1])
            if learning:
                parts.append("- 近期学习要点:")
                for point in learning[:3]:
                    parts.append(f"  * {point}")

        parts.append("\n请反思：当前策略是否有效？是否需要调整？")

        return "\n".join(parts)

    # ════════════════════════════════════════════════════════
    # 主体性反思接口 — reflect / persist / influence_future_decision
    # ════════════════════════════════════════════════════════

    def reflect(
        self,
        task: str,
        outcome: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """对一次任务执行进行反思，生成结构化复盘报告。

        内部构造 ``CognitiveEpisode`` 并调用现有的 ``_perform_reflection``，
        再将原始字段映射为对外稳定的复盘报告字段。

        Args:
            task: 任务描述（用于推理上下文）。
            outcome: 结果描述（如 "success"、"error: ..."）。
            context: 上下文字典，可包含 reasoning_steps、confidence、
                alternatives、action_taken、emotional_state 等字段。

        Returns:
            反思报告字典，包含字段：``reflection_id``、``task``、``outcome``、
            ``decision_path``、``alternatives``、``learning_points``、
            ``value_alignment_check``、``self_model_update_suggestion``、
            ``timestamp``。
        """
        if context is None:
            context = {}

        # 构造 CognitiveEpisode 并填充推理步骤/行动/结果
        episode = CognitiveEpisode(
            context=task[:200],
            action_taken=str(context.get("action_taken", task))[:200],
            outcome=outcome[:200],
            confidence=float(context.get("confidence", 0.5)),
            emotional_state=str(context.get("emotional_state", "neutral")),
        )
        for step in context.get("reasoning_steps", []) or []:
            episode.reasoning_trace.append(str(step))

        # 同步加入 episodes 列表便于后续查询
        self.episodes.append(episode)
        self._update_metrics(episode)
        self._detect_biases(episode)

        # 调用现有 _perform_reflection（自动追加到 self.reflections）
        triggers = [ReflectionTrigger.POST_ACTION]
        if "error" in outcome.lower() or "fail" in outcome.lower():
            triggers.append(ReflectionTrigger.ERROR_DETECTED)
        if episode.confidence < self.LOW_CONFIDENCE_THRESHOLD:
            triggers.append(ReflectionTrigger.CONFIDENCE_LOW)

        internal = self._perform_reflection(episode, triggers)

        # 提取复盘报告字段
        reasoning_analysis = internal.get("reasoning_analysis", {})
        alternatives = list(context.get("alternatives", []) or [])
        learning_points = list(internal.get("learning_points", []) or [])
        biases_detected = list(internal.get("biases_detected", []) or [])

        # 价值对齐检查：如果 context 提供了 value_check 结果，直接使用；
        # 否则基于偏差推断一个简单结论
        value_check = context.get("value_alignment_check")
        if value_check is None:
            value_violations = [
                b for b in biases_detected
                if b in ("confirmation_bias", "emotional_bias", "overconfidence")
            ]
            value_check = {
                "aligned": len(value_violations) == 0,
                "violations": value_violations,
                "note": "基于认知偏差推断（未提供显式价值检查）",
            }

        # 自我模型更新建议
        suggestion = self._build_self_model_update_suggestion(
            task=task, outcome=outcome, episode=episode,
            biases=biases_detected, learning_points=learning_points,
            context=context,
        )

        report = {
            "reflection_id": internal.get("reflection_id"),
            "task": task,
            "outcome": outcome,
            "decision_path": {
                "reasoning_steps": list(episode.reasoning_trace),
                "reasoning_analysis": reasoning_analysis,
                "action_taken": episode.action_taken,
                "circularity_detected": internal.get(
                    "circularity_detected", False),
            },
            "alternatives": alternatives,
            "learning_points": learning_points,
            "value_alignment_check": value_check,
            "self_model_update_suggestion": suggestion,
            "biases_detected": biases_detected,
            "confidence": episode.confidence,
            "timestamp": time.time(),
        }
        return report

    def _build_self_model_update_suggestion(
        self,
        task: str,
        outcome: str,
        episode: CognitiveEpisode,
        biases: List[str],
        learning_points: List[str],
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """基于反思结果生成对自我模型的更新建议。"""
        domain = str(context.get("domain", "general"))
        is_success = "success" in outcome.lower() and "fail" not in outcome.lower()
        confidence_gap = abs(episode.confidence - (
            1.0 if is_success else 0.0
        ))

        suggestions: List[str] = []
        if not is_success:
            suggestions.append(
                f"建议在 self_model 中降低对 '{domain}' 的熟练度预期"
            )
        if episode.confidence > 0.7 and not is_success:
            suggestions.append("存在过度自信，建议调低 confidence 校准曲线")
        if "insufficient_reasoning" in biases:
            suggestions.append("建议在下次类似任务中增加推理步骤")
        if "circularity" in biases:
            suggestions.append("检测到循环推理，建议自我模型记录此偏差模式")
        if not suggestions:
            suggestions.append("无需特别更新——表现与自我评估一致")

        return {
            "domain": domain,
            "should_update": len(suggestions) > 1 or not is_success,
            "suggestions": suggestions,
            "confidence_gap": round(confidence_gap, 3),
            "is_success": is_success,
        }

    def persist_reflection(
        self,
        reflection: Dict[str, Any],
        path: Optional[str] = None,
    ) -> str:
        """将反思报告持久化为 JSON 文件。

        Args:
            reflection: ``reflect()`` 返回的反思报告字典。
            path: 自定义保存路径。为 None 时使用
                ``~/.laap/reflections/{reflection_id}.json``。

        Returns:
            实际写入的文件路径。
        """
        laap_home = os.environ.get("LAAP_HOME", str(Path.home() / ".laap"))
        reflections_dir = Path(laap_home) / "reflections"
        reflections_dir.mkdir(parents=True, exist_ok=True)

        if path is None:
            refl_id = reflection.get("reflection_id") or f"refl_{uuid.uuid4().hex[:8]}"
            path = str(reflections_dir / f"{refl_id}.json")

        # 确保父目录存在
        Path(path).parent.mkdir(parents=True, exist_ok=True)

        with open(path, "w", encoding="utf-8") as f:
            json.dump(reflection, f, ensure_ascii=False, indent=2, default=str)

        return path

    def influence_future_decision(
        self,
        reflection: Dict[str, Any],
    ) -> Dict[str, Any]:
        """从反思中提取未来决策应参考的"经验教训"。

        Args:
            reflection: ``reflect()`` 返回的反思报告字典。

        Returns:
            经验教训字典，包含：
              - ``avoid_patterns``：失败相关模式（应避免）
              - ``prefer_patterns``：成功相关模式（应优先）
              - ``confidence_adjustments``：置信度调整建议
              - ``source_reflection_id``：来源反思 ID
        """
        avoid_patterns: List[str] = []
        prefer_patterns: List[str] = []
        confidence_adjustments: Dict[str, float] = {}

        outcome = str(reflection.get("outcome", "")).lower()
        is_success = "success" in outcome and "fail" not in outcome
        suggestion = reflection.get("self_model_update_suggestion") or {}
        biases = reflection.get("biases_detected", []) or []
        learning_points = reflection.get("learning_points", []) or []

        if is_success:
            prefer_patterns.append(
                f"成功路径: {reflection.get('task', '')[:80]}"
            )
            for lp in learning_points:
                prefer_patterns.append(str(lp))
        else:
            avoid_patterns.append(
                f"失败任务: {reflection.get('task', '')[:80]}"
            )
            for lp in learning_points:
                avoid_patterns.append(str(lp))

        for bias in biases:
            avoid_patterns.append(f"认知偏差: {bias}")

        # 置信度调整
        domain = suggestion.get("domain", "general")
        gap = suggestion.get("confidence_gap", 0.0)
        if suggestion.get("should_update", False):
            # 过度自信则下调；否则按 gap 调整
            if "overconfidence" in biases:
                confidence_adjustments[domain] = -0.1
            elif gap > 0.3:
                confidence_adjustments[domain] = -0.05
            else:
                confidence_adjustments[domain] = 0.02

        return {
            "avoid_patterns": avoid_patterns,
            "prefer_patterns": prefer_patterns,
            "confidence_adjustments": confidence_adjustments,
            "source_reflection_id": reflection.get("reflection_id"),
            "is_success": is_success,
        }

    # ════════════════════════════════════════════════════════
    # 防幻觉管线接入 — record_bias_correction / bias_count
    # ════════════════════════════════════════════════════════

    def record_bias_correction(self, record: Dict[str, Any]) -> None:
        """记录一次由防幻觉管线触发的偏误校正事件。

        本方法是为 truth_grounding 防幻觉管线提供的对外稳定接口：当三态
        判定命中 ``error`` 态时，上层调用本方法把校正记录追加到
        ``cognitive_biases_detected`` 列表中，并同步累加
        ``performance_metrics["biases_found"]``。

        设计要点：
        * **幂等** — 当 ``record`` 中带 ``correction_id`` 时，重复传入同一
          id 不会重复计数（只保留首次写入）；
        * **非阻塞** — 任何异常分支都不抛出，确保管线不会因为元监控失败
          而中断；
        * 不直接修改既有 ``_detect_biases`` 流程，仅在新增字段中累加。

        Args:
            record: 校正记录字典，期望字段：
                * ``bias_type`` (str) — 偏误类型标签，如
                  ``"hallucination"``、``"known_false_fact"``、
                  ``"absolute_claim_without_evidence"``；
                * ``claim`` (str) — 触发校正的论断文本；
                * ``conflicts`` (List[str], 可选) — 冲突来源列表；
                * ``correction_id`` (str, 可选) — 幂等键，重复传入同 id 不会
                  重复计数；
                * ``timestamp`` (float, 可选) — 事件时间戳，默认当前时间。
        """
        try:
            if not isinstance(record, dict):
                return

            correction_id = record.get("correction_id")

            # 幂等检查：若已存在同 correction_id 的记录，直接返回
            if correction_id:
                for existing in self.cognitive_biases_detected:
                    if existing.get("correction_id") == correction_id:
                        return

            entry: Dict[str, Any] = {
                "episode_id": record.get("episode_id", "truth_grounding"),
                "biases": [str(record.get("bias_type", "hallucination"))],
                "timestamp": float(record.get("timestamp", time.time())),
                "source": "truth_grounding",
            }
            # 仅在字段存在时写入，避免 None 污染
            if correction_id:
                entry["correction_id"] = correction_id
            if "claim" in record:
                entry["claim"] = str(record["claim"])[:200]
            if "conflicts" in record and isinstance(record["conflicts"], list):
                entry["conflicts"] = list(record["conflicts"])

            self.cognitive_biases_detected.append(entry)
            self.performance_metrics["biases_found"] = (
                float(self.performance_metrics.get("biases_found", 0.0)) + 1.0
            )
        except Exception:
            # 元监控不得阻塞主管线
            return

    @property
    def bias_count(self) -> int:
        """已检测到的认知偏差事件总数（含防幻觉管线校正）。

        幂等：多次读取返回一致值，仅反映已写入 ``cognitive_biases_detected``
        列表的事件数量。
        """
        return len(self.cognitive_biases_detected)