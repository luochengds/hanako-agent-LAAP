"""LAAP — Cognitive autonomy protection

Addresses the disempowerment risk identified in the Triple Paradox review:
AI may erode user cognitive autonomy by defaulting to complete-answer mode
instead of thinking-inviting mode on open-ended questions.

This module provides a lightweight, opt-in interceptor for the response
generation pipeline. It does NOT force a behavior change; it classifies
the risk and returns a recommended response mode.

Response modes:
  ANSWER_MODE — normal complete answer.
  THINKING_MODE — invite user thinking first; avoid premature closure.
  MIXED_MODE — provide scaffolded structure, not full answer.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("laap.cognition.autonomy_protection")


class ResponseMode(str, Enum):
    ANSWER_MODE = "answer_mode"
    THINKING_MODE = "thinking_mode"
    MIXED_MODE = "mixed_mode"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class AutonomyAssessment:
    query: str
    detected_patterns: List[str] = field(default_factory=list)
    is_open_ended: bool = False
    risk_level: RiskLevel = RiskLevel.LOW
    recommended_mode: ResponseMode = ResponseMode.ANSWER_MODE
    reason: str = ""
    suggested_prompts: List[str] = field(default_factory=list)


# Heuristics — tuned for low false-positive rate.
_OPEN_ENDED_PATTERNS = [
    r"怎么看待|怎么看|你的观点|你的想法|你觉得|如何评价|如何理解",
    r"为什么|为何|原因是什么|本质是什么|核心是什么",
    r"有哪些|有什么|列举|分析|比较|对比|讨论",
    r"帮我想|帮我分析|帮我梳理|一起思考|深入聊聊",
    r"未来会|预测|趋势|方向|应该怎么",
    r"真的吗|确定吗|肯定吗|靠谱吗|可信吗",
    r"我该不该|要不要|值得吗|有意义吗|重要吗",
]


_COMPLETE_ANSWER_HINTS = [
    "直接给出",
    "完整方案",
    "一站式",
    "全部",
    "所有",
    "总结完毕",
]


class AutonomyProtectionFilter:
    """Lightweight filter that assesses cognitive-autonomy risk.

    Usage::

        filter = AutonomyProtectionFilter()
        assessment = filter.assess("你觉得AI会取代程序员吗？")
        if assessment.recommended_mode != ResponseMode.ANSWER_MODE:
            # switch to thinking-inviting response
            ...
    """

    def __init__(self, enable: bool = True) -> None:
        self.enable = enable
        self._recent_queries: List[str] = []
        self._recent_modes: List[ResponseMode] = []
        self._max_recent = 20

    def assess(self, query: str, context: Optional[Dict[str, Any]] = None) -> AutonomyAssessment:
        if not self.enable:
            return AutonomyAssessment(query=query)

        ctx = context or {}
        q = (query or "").strip()
        patterns = self._match_open_ended(q)
        is_open = bool(patterns)
        risk = self._estimate_risk(q, patterns, ctx)
        mode, reason, prompts = self._recommend(risk, is_open, q, ctx)

        assessment = AutonomyAssessment(
            query=q,
            detected_patterns=patterns,
            is_open_ended=is_open,
            risk_level=risk,
            recommended_mode=mode,
            reason=reason,
            suggested_prompts=prompts,
        )

        self._recent_queries.append(q)
        self._recent_modes.append(mode)
        if len(self._recent_queries) > self._max_recent:
            self._recent_queries = self._recent_queries[-self._max_recent:]
            self._recent_modes = self._recent_modes[-self._max_recent:]
        return assessment

    def stats(self) -> Dict[str, Any]:
        if not self._recent_modes:
            return {"recent_count": 0}
        return {
            "recent_count": len(self._recent_modes),
            "answer_mode_ratio": sum(1 for m in self._recent_modes if m == ResponseMode.ANSWER_MODE) / len(self._recent_modes),
            "thinking_mode_ratio": sum(1 for m in self._recent_modes if m == ResponseMode.THINKING_MODE) / len(self._recent_modes),
            "mixed_mode_ratio": sum(1 for m in self._recent_modes if m == ResponseMode.MIXED_MODE) / len(self._recent_modes),
        }

    def _match_open_ended(self, query: str) -> List[str]:
        matched = []
        for pattern in _OPEN_ENDED_PATTERNS:
            if re.search(pattern, query, re.IGNORECASE):
                matched.append(pattern)
        return matched

    def _estimate_risk(self, query: str, patterns: List[str], context: Dict[str, Any]) -> RiskLevel:
        if not patterns:
            return RiskLevel.LOW

        score = 0.0
        # More patterns -> higher risk.
        score += min(len(patterns) * 0.25, 0.75)

        # High urgency / direct request for completion increases risk.
        if any(hint in query for hint in _COMPLETE_ANSWER_HINTS):
            score += 0.15

        # If the user explicitly invites thinking, reduce risk.
        if re.search(r"先别急着回答|一起想|引导我|启发式", query, re.IGNORECASE):
            score -= 0.4

        # Long dependency on assistant over short horizon -> higher risk.
        recent_answer_ratio = context.get("recent_answer_ratio", 0.5)
        score += recent_answer_ratio * 0.2

        score = max(0.0, min(1.0, score))
        if score >= 0.65:
            return RiskLevel.HIGH
        if score >= 0.35:
            return RiskLevel.MEDIUM
        return RiskLevel.LOW

    def _recommend(self, risk: RiskLevel, is_open: bool, query: str,
                   context: Dict[str, Any]) -> tuple[ResponseMode, str, List[str]]:
        if not is_open or risk == RiskLevel.LOW:
            return ResponseMode.ANSWER_MODE, "常规问题，正常回答", []

        if risk == RiskLevel.HIGH:
            prompts = self._thinking_prompts(query)
            return ResponseMode.THINKING_MODE, "高自主性风险：优先激发用户思考", prompts

        # MEDIUM
        prompts = self._scaffold_prompts(query)
        return ResponseMode.MIXED_MODE, "中等自主性风险：提供思考脚手架而非完整答案", prompts

    @staticmethod
    def _thinking_prompts(query: str) -> List[str]:
        return [
            "我先不直接给结论了——你目前最在意的约束条件是什么？",
            "这个问题里，你觉得最关键的变量是哪几个？",
            "如果反过来从反面论证，你会先从哪个假设开始？",
            "你之前考虑过哪些方向？哪些被你排除了，为什么？",
        ]

    @staticmethod
    def _scaffold_prompts(query: str) -> List[str]:
        return [
            "我可以先给你一个分析框架，你来填充关键判断，可以吗？",
            "要不要我们先拆成 3 个子问题，逐个讨论？",
            "这类问题通常可以从这几个角度切入，你对哪个角度最有感觉？",
        ]
