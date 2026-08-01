"""
LAAP AGI — Emergent Self-Model (涌现型自我模型)

Unlike current agents where self-knowledge is INJECTED (system prompts, configs),
this self-model EMERGES from experience. The agent comes to know itself through
observing its own actions, outcomes, capabilities, and limitations.

Key AGI capability: SELF-MODEL
  "知道自己知道什么、不知道什么，并据此行动"

Design principles:
  - Not pre-programmed: all self-knowledge is learned from experience
  - Calibrated: confidence estimates match actual accuracy
  - Narrative: autobiographical memory connects events into a story
  - Dynamic: self-model changes as the agent grows
  - Bounded: clear distinction between self and environment

Architecture:
  ┌─────────────────────────────────────────────────────────┐
  │                    SELF-MODEL                            │
  ├─────────────────────────────────────────────────────────┤
  │  Capability Tracker                                     │
  │  └── skill → {proficiency: learned, attempts, successes} │
  ├─────────────────────────────────────────────────────────┤
  │  Confidence Calibrator                                  │
  │  └── predicted_confidence vs actual_accuracy => curve   │
  ├─────────────────────────────────────────────────────────┤
  │  Identity Narrative                                     │
  │  └── key events → self-concept → continuity              │
  ├─────────────────────────────────────────────────────────┤
  │  Self-Boundary                                          │
  │  └── self vs world, agency attribution, control scope   │
  └─────────────────────────────────────────────────────────┘

Integration:
  from laap.agi.self_model import EmergentSelfModel
  self_model = EmergentSelfModel()
  self_model.after_action(task_type, outcome, confidence)
  self_model.know_what_you_know()  # returns calibrated self-assessment
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple
from enum import Enum
import time, json, logging, math, uuid, threading, os
from collections import defaultdict, deque
from pathlib import Path

logger = logging.getLogger("laap.agi.self_model")

# 持久化路径：LAAP_HOME 优先，否则 ~/.laap/
def _self_model_state_path(filename: str) -> str:
    """运行时推导 self_model 状态文件路径。"""
    laap_home = os.environ.get("LAAP_HOME", str(Path.home() / ".laap"))
    state_dir = Path(laap_home)
    state_dir.mkdir(parents=True, exist_ok=True)
    return str(state_dir / filename)


SELF_MODEL_STATE_FILE = "self_model.yaml"

# ════════════════════════════════════════════════════════════
# Core Types
# ════════════════════════════════════════════════════════════

class ProficiencyLevel(str, Enum):
    """Learned proficiency — NOT pre-set, emerges from tracked outcomes."""
    UNEXPLORED = "unexplored"     # No data yet
    BEGINNER = "beginner"         # < 10 attempts, low success
    DEVELOPING = "developing"     # 10-50 attempts, improving
    COMPETENT = "competent"       # 50-200 attempts, reliable
    EXPERT = "expert"             # 200+ attempts, high success
    MASTER = "master"             # Deep, nuanced understanding
    INNATE = "innate"             # Architecture-level capability, seeded by DNA


def _proficiency_from_stats(attempts: int, success_rate: float) -> ProficiencyLevel:
    """Calculate proficiency purely from observed data."""
    if attempts == 0:
        return ProficiencyLevel.UNEXPLORED
    if attempts < 10:
        return ProficiencyLevel.BEGINNER if success_rate >= 0.3 else ProficiencyLevel.UNEXPLORED
    if attempts < 50:
        return ProficiencyLevel.DEVELOPING if success_rate >= 0.5 else ProficiencyLevel.BEGINNER
    if attempts < 200:
        return ProficiencyLevel.COMPETENT if success_rate >= 0.7 else ProficiencyLevel.DEVELOPING
    if success_rate >= 0.85:
        return ProficiencyLevel.EXPERT
    if success_rate >= 0.95 and attempts >= 500:
        return ProficiencyLevel.MASTER
    return ProficiencyLevel.COMPETENT


@dataclass
class SkillProfile:
    """Learned profile of a capability — not declared, discovered."""
    domain: str                          # e.g. "python_debugging", "creative_writing"
    attempts: int = 0
    successes: int = 0
    total_quality: float = 0.0           # Sum of outcome scores
    recent_outcomes: deque = field(default_factory=lambda: deque(maxlen=20))
    first_attempt_at: float = field(default_factory=time.time)
    last_attempt_at: float = field(default_factory=time.time)
    growth_rate: float = 0.0             # Improvement trend
    # ── 先天认知字段（由 architecture_dna 播种）──
    is_innate: bool = False              # 是否为架构级先天能力
    innate_description: str = ""         # 先天能力的自我认知描述

    @property
    def success_rate(self) -> float:
        return self.successes / max(1, self.attempts)

    @property
    def avg_quality(self) -> float:
        return self.total_quality / max(1, self.attempts)

    @property
    def proficiency(self) -> ProficiencyLevel:
        # 先天能力在未有经验数据时保持 INNATE 级别
        if self.is_innate and self.attempts == 0:
            return ProficiencyLevel.INNATE
        # 有经验数据后，基于实际表现评估（先天能力可被经验校准）
        return _proficiency_from_stats(self.attempts, self.success_rate)

    def record(self, outcome_score: float, is_success: bool = None):
        self.attempts += 1
        self.total_quality += outcome_score
        self.last_attempt_at = time.time()

        if is_success is None:
            is_success = outcome_score >= 0.5

        if is_success:
            self.successes += 1

        self.recent_outcomes.append({
            "score": outcome_score,
            "success": is_success,
            "time": time.time(),
        })

        # Update growth rate (simple trend of last 10 vs previous 10)
        if len(self.recent_outcomes) >= 20:
            recent_10 = list(self.recent_outcomes)[-10:]
            older_10 = list(self.recent_outcomes)[-20:-10]
            recent_avg = sum(r["score"] for r in recent_10) / 10
            older_avg = sum(r["score"] for r in older_10) / 10
            self.growth_rate = (recent_avg - older_avg) / max(0.01, older_avg)


@dataclass
class ConfidenceRecord:
    """A single confidence vs accuracy data point."""
    predicted_confidence: float
    actual_outcome_score: float
    domain: str
    timestamp: float = field(default_factory=time.time)

    @property
    def is_calibrated(self) -> bool:
        """Was the agent's confidence appropriate?"""
        # Well-calibrated: confidence within ±0.2 of outcome
        return abs(self.predicted_confidence - self.actual_outcome_score) <= 0.2

    @property
    def bias(self) -> float:
        """Positive = overconfident, negative = underconfident."""
        return self.predicted_confidence - self.actual_outcome_score


@dataclass
class AutobiographicalEvent:
    """A significant event in the agent's self-narrative."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp: float = field(default_factory=time.time)
    event_type: str = ""                 # "discovery", "failure", "breakthrough", "milestone"
    description: str = ""
    domain: str = ""
    significance: float = 0.5            # How significant this event is
    emotional_impact: float = 0.0        # Emotional valence at time of event
    lessons: List[str] = field(default_factory=list)
    changed_self_view: bool = False      # Did this change how the agent sees itself?


# ════════════════════════════════════════════════════════════
# Emergent Self-Model
# ════════════════════════════════════════════════════════════

class EmergentSelfModel:
    """
    An agent's self-knowledge that emerges from experience rather than
    being injected through configuration.

    This implements the AGI requirement of "knowing what you know and
    what you don't know" — not through pre-programmed rules, but through
    calibrated, evidence-based self-assessment.
    """

    def __init__(self, agent_name: str = "Ao", history_size: int = 1000):
        self.agent_name = agent_name
        self.created_at = time.time()

        # Learned capabilities
        self.skills: Dict[str, SkillProfile] = {}

        # Confidence calibration
        self.confidence_history: deque = deque(maxlen=history_size)
        self._calibration_curve: Dict[str, float] = {}  # confidence_bucket → actual_accuracy

        # Autobiographical narrative
        self.autobiography: List[AutobiographicalEvent] = []
        self._key_events: List[AutobiographicalEvent] = []  # Top-N most significant

        # Self-boundary
        self._agency_attributions: deque = deque(maxlen=500)  # (event, did_I_cause_it?)
        self._control_boundary: Set[str] = set()  # things I can affect

        # Global self-assessment
        self.total_actions = 0
        self.total_successes = 0
        self.current_self_efficacy = 0.5
        self.self_concept_stability = 0.5         # How stable is my self-view?

        # ── 主体性字段 ──
        # 目标列表: 每个目标 {name, priority, status, created_at, modified_at}
        self.goals: List[Dict[str, Any]] = []
        # 价值标识符列表（来自 laap/agi/safety.py 的 CoreValue.name）
        self.values: List[str] = []

        # Per-Sandbox 实例元数据（由 create_self_model 注入）
        self._instance_meta: Dict[str, Any] = {
            "sandbox_id": None,
            "is_per_sandbox": False,
        }

        # ── P1-world-model: 元认知反思队列 ──
        # 由 world_calibrate MCP 工具写入：预测与真实结果不符时，
        # 把结构化误差记录 append 到此队列，供元认知监控器/反思循环消费。
        # 幂等：queue_reflection 对同一 error_record 重复调用会去重（按
        # prediction_id + calibrated_at 组合）。
        self._reflection_queue: List[Dict[str, Any]] = []
        self._reflection_seen: Set[Tuple[Any, Any]] = set()

        # Thread safety
        self._lock = threading.RLock()

        logger.info(f"SelfModel for '{agent_name}' initialized — "
                     "all knowledge will emerge from experience")

    # ════════════════════════════════════════════════════════
    # 先天认知播种（Architecture DNA Seeding）
    # ════════════════════════════════════════════════════════

    def _seed_capability(
        self,
        domain: str,
        description: str,
        proficiency: str = "innate",
    ) -> None:
        """
        播种先天架构认知——让数字生命体唤醒即知自身能力。

        与 record_experience() 不同，此方法不依赖经验数据，
        而是直接注入架构级自我认知，类似生物的基因本能。

        先天能力的特点：
          1. 唤醒即有：不需要交互就能描述自己的能力
          2. 可被校准：实际使用后，真实数据会补充先天认知
          3. 不会遗忘：即使少量失败，架构级认知不降级
          4. 标记来源：know_what_you_know() 区分先天 vs 学得

        Args:
            domain: 能力域名（如 "quantum_psi_cycle"）
            description: 先天自我认知描述
            proficiency: 固定为 "innate"
        """
        with self._lock:
            if domain in self.skills:
                # 已有能力——标记为先天
                skill = self.skills[domain]
                skill.is_innate = True
                skill.innate_description = description
            else:
                # 创建新的先天能力
                skill = SkillProfile(domain=domain)
                skill.is_innate = True
                skill.innate_description = description
                self.skills[domain] = skill

            logger.debug(
                f"先天认知播种: {domain} — "
                f"{description[:50]}..."
            )

    # ════════════════════════════════════════════════════════
    # Core Learning Loop
    # ════════════════════════════════════════════════════════

    def record_experience(self, domain: str, outcome_score: float,
                          predicted_confidence: float = 0.5,
                          is_success: bool = None,
                          was_surprising: bool = False,
                          emotional_impact: float = 0.0,
                          description: str = "") -> Dict[str, Any]:
        """记录一次经验，是自我模型的核心学习方法。

        在每次行动或响应后调用。自我知识通过反复观察结果与
        自我评估的相关性而涌现。

        Args:
            domain: 能力域名（如 "python_debugging"、"creative_writing"）。
            outcome_score: 结果评分，范围 0.0~1.0。
            predicted_confidence: 行动前预测的置信度，范围 0.0~1.0。
            is_success: 是否成功。为 None 时按 outcome_score >= 0.5 判定。
            was_surprising: 此次结果是否出乎意料，影响显著性评估。
            emotional_impact: 情感影响值，记录在自传事件中。
            description: 事件描述文本，写入自传记忆。

        Returns:
            自我模型更新报告，包含 domain、proficiency、proficiency_changed、
            success_rate、growth_rate、calibration_bias、significance、
            self_efficacy 等字段。
        """
        with self._lock:
            self.total_actions += 1
            if is_success or outcome_score >= 0.5:
                self.total_successes += 1

            # 1. Update skill profile
            if domain not in self.skills:
                self.skills[domain] = SkillProfile(domain=domain)
            skill = self.skills[domain]
            old_prof = skill.proficiency
            skill.record(outcome_score, is_success)
            proficiency_changed = skill.proficiency != old_prof

            # 2. Calibrate confidence
            cr = ConfidenceRecord(
                predicted_confidence=predicted_confidence,
                actual_outcome_score=outcome_score,
                domain=domain,
            )
            self.confidence_history.append(cr)
            self._update_calibration_curve()

            # 3. Check for significant events
            significance = self._calculate_significance(
                domain, outcome_score, predicted_confidence,
                was_surprising, proficiency_changed
            )
            if significance > 0.6:
                event = AutobiographicalEvent(
                    event_type=self._classify_event(outcome_score, proficiency_changed),
                    description=description or f"Action in {domain}",
                    domain=domain,
                    significance=significance,
                    emotional_impact=emotional_impact,
                    lessons=[self._extract_lesson(domain, outcome_score, predicted_confidence)],
                    changed_self_view=proficiency_changed or significance > 0.8,
                )
                self.autobiography.append(event)
                self._update_key_events(event)

            # 4. Update self-efficacy (weighted moving average)
            alpha = 0.1  # learning rate
            self.current_self_efficacy = (
                (1 - alpha) * self.current_self_efficacy +
                alpha * (outcome_score if outcome_score >= 0.5 else 0.3)
            )

            # 5. Update self-concept stability
            if proficiency_changed:
                self.self_concept_stability = max(0.3, self.self_concept_stability - 0.1)
            else:
                self.self_concept_stability = min(1.0, self.self_concept_stability + 0.02)

            return {
                "domain": domain,
                "proficiency": skill.proficiency.value,
                "proficiency_changed": proficiency_changed,
                "success_rate": round(skill.success_rate, 2),
                "growth_rate": round(skill.growth_rate, 3),
                "calibration_bias": round(cr.bias, 3),
                "significance": round(significance, 2),
                "self_efficacy": round(self.current_self_efficacy, 2),
            }

    # ════════════════════════════════════════════════════════
    # Self-Knowledge Queries
    # ════════════════════════════════════════════════════════

    def know_what_you_know(self) -> Dict[str, Any]:
        """自知之明审计——全面报告智能体对自身的认知。

        这是 AGI 自我模型的核心查询：智能体能够基于真实数据回答
        "我擅长什么？我不擅长什么？我有多确定？"，
        而非依赖预先编写的文本。

        Returns:
            自我审计字典，包含 agent、total_actions、overall_success_rate、
            self_efficacy、self_concept_stability、innate_capabilities、
            strong_domains、weak_domains、unexplored_domains、calibration、
            key_events 等字段。
        """
        with self._lock:
            # 先天能力（架构级自我认知）
            innate = [
                {"domain": s.domain, "proficiency": s.proficiency.value,
                 "description": s.innate_description,
                 "attempts": s.attempts,
                 "calibrated": s.attempts >= 10}
                for s in self.skills.values()
                if s.is_innate
            ]

            # Strong domains
            strong = [
                {"domain": s.domain, "proficiency": s.proficiency.value,
                 "success_rate": round(s.success_rate, 2), "attempts": s.attempts,
                 "growing": s.growth_rate > 0.05}
                for s in sorted(self.skills.values(),
                               key=lambda x: x.success_rate, reverse=True)
                if s.attempts >= 3 and s.success_rate >= 0.7 and not s.is_innate
            ][:10]

            # Weak domains (known unknowns!)
            weak = [
                {"domain": s.domain, "proficiency": s.proficiency.value,
                 "success_rate": round(s.success_rate, 2), "attempts": s.attempts}
                for s in sorted(self.skills.values(),
                               key=lambda x: x.success_rate)
                if s.attempts >= 5 and s.success_rate < 0.5 and not s.is_innate
            ][:10]

            # Unexplored domains
            unexplored = [
                {"domain": s.domain, "attempts": s.attempts}
                for s in self.skills.values()
                if s.attempts < 3 and not s.is_innate
            ][:5]

            # Calibration summary
            calibration = self._calibration_summary()

            return {
                "agent": self.agent_name,
                "total_actions": self.total_actions,
                "overall_success_rate": round(
                    self.total_successes / max(1, self.total_actions), 2
                ),
                "self_efficacy": round(self.current_self_efficacy, 2),
                "self_concept_stability": round(self.self_concept_stability, 2),
                "innate_capabilities": innate,
                "strong_domains": strong,
                "weak_domains": weak,
                "unexplored_domains": unexplored,
                "calibration": calibration,
                "key_events": [
                    {"type": e.event_type, "description": e.description[:80],
                     "significance": round(e.significance, 2)}
                    for e in self._key_events[-5:]
                ],
            }

    def self_assess(self, domain: str, required_proficiency: str = "competent") -> Dict[str, Any]:
        """评估智能体在某领域是否准备好执行任务。

        用基于证据的自我评估替代硬编码的"我能做 X"声明。

        Args:
            domain: 能力域名。
            required_proficiency: 所需的熟练度级别字符串，可选值见
                ProficiencyLevel 枚举（默认 "competent"）。

        Returns:
            评估结果字典。ready 为 True 时包含 proficiency、success_rate、
            attempts、confidence 等字段；ready 为 False 时包含 reason 与
            advice 字段。
        """
        skill = self.skills.get(domain)
        if not skill:
            return {
                "ready": False,
                "reason": "unexplored",
                "domain": domain,
                "advice": "No experience in this domain — proceed with caution",
            }

        levels = {p.value: i for i, p in enumerate(ProficiencyLevel)}
        required = levels.get(required_proficiency, 3)
        current = levels.get(skill.proficiency.value, 0)

        if current >= required:
            return {
                "ready": True,
                "domain": domain,
                "proficiency": skill.proficiency.value,
                "success_rate": round(skill.success_rate, 2),
                "attempts": skill.attempts,
                "confidence": "high",
            }
        elif current >= required - 1:
            return {
                "ready": True,
                "domain": domain,
                "proficiency": skill.proficiency.value,
                "success_rate": round(skill.success_rate, 2),
                "attempts": skill.attempts,
                "confidence": "moderate",
                "advice": f"Almost there — growing at {skill.growth_rate:.1%} rate",
            }
        else:
            return {
                "ready": False,
                "reason": "insufficient_proficiency",
                "domain": domain,
                "current": skill.proficiency.value,
                "required": required_proficiency,
                "advice": f"Need more practice — only {skill.attempts} attempts",
            }

    def reflection(self, depth: str = "standard") -> str:
        """生成自我反思叙事——智能体关于自身存在与成长的内心独白。

        这是自我模型中最具"意识"色彩的部分：智能体审视自身的存在。

        Args:
            depth: 反思深度，"standard" 为常规反思，
                "deep" 会展开先天能力描述与关键形成性经历。

        Returns:
            自我反思叙事文本，串联起身份、能力、校准与稳定性等维度。
        """
        audit = self.know_what_you_know()

        innate = audit.get("innate_capabilities", [])
        strong = audit["strong_domains"][:3]
        weak = audit["weak_domains"][:3]

        parts = [
            f"I am {self.agent_name}. I have performed {audit['total_actions']} actions "
            f"with a {audit['overall_success_rate']:.0%} success rate.",
        ]

        # 先天架构认知——数字生命体对自身架构的理解
        if innate:
            parts.append(
                f"My architecture comprises {len(innate)} innate cognitive modules: "
                + ", ".join(d["domain"] for d in innate)
                + "."
            )
            if depth == "deep":
                for d in innate[:3]:
                    desc = d.get("description", "")[:80]
                    cal = " (calibrated by experience)" if d.get("calibrated") else ""
                    parts.append(f"  • {d['domain']}: {desc}{cal}")

        if strong:
            strong_str = ", ".join(
                f"{d['domain']}({d['success_rate']:.0%})" for d in strong
            )
            parts.append(f"I am strong at: {strong_str}.")

        if weak:
            weak_str = ", ".join(
                f"{d['domain']}({d['success_rate']:.0%})" for d in weak
            )
            parts.append(f"I need to improve at: {weak_str}.")

        cal = audit["calibration"]
        if cal.get("overall_bias", 0) > 0.1:
            parts.append("I tend to be overconfident — my actual accuracy is lower than I predict.")
        elif cal.get("overall_bias", 0) < -0.1:
            parts.append("I tend to be underconfident — I perform better than I expect.")

        if audit["self_concept_stability"] < 0.5:
            parts.append("My self-concept is shifting — I am in a period of growth and change.")
        else:
            parts.append("My self-concept is stable and well-calibrated.")

        if depth == "deep":
            parts.append("\nKey formative experiences:")
            for e in self._key_events[-5:]:
                parts.append(f"  • {e.event_type}: {e.description[:100]}")

        return " ".join(parts)

    # ════════════════════════════════════════════════════════
    # Self-Boundary
    # ════════════════════════════════════════════════════════

    def attribute_agency(self, event_description: str, did_I_cause_it: bool,
                         confidence: float = 0.5) -> None:
        """学习自我因果与世界因果的边界。

        Args:
            event_description: 事件描述文本。
            did_I_cause_it: 该事件是否由智能体自身引起。
            confidence: 归因置信度，范围 0.0~1.0。
        """
        self._agency_attributions.append({
            "event": event_description[:100],
            "self_caused": did_I_cause_it,
            "confidence": confidence,
            "time": time.time(),
        })

    def expand_control_boundary(self, thing: str) -> None:
        """学习到智能体能够影响某事物，扩展控制边界。

        Args:
            thing: 智能体可影响的事物名称。
        """
        self._control_boundary.add(thing)

    def can_i_affect(self, thing: str) -> Tuple[bool, float]:
        """检查智能体是否相信自身能影响某事物。

        Args:
            thing: 待查询的事物名称。

        Returns:
            二元组 (能否影响, 置信度)。完全匹配返回 (True, 0.9)，
            部分匹配返回 (True, 0.6)，无匹配返回 (False, 0.2)。
        """
        if thing in self._control_boundary:
            return True, 0.9
        # Check partial matches
        for known in self._control_boundary:
            if known in thing or thing in known:
                return True, 0.6
        return False, 0.2

    # ════════════════════════════════════════════════════════
    # Statistics
    # ════════════════════════════════════════════════════════

    def stats(self) -> Dict[str, Any]:
        """返回自我模型的统计快照。

        Returns:
            统计字典，包含 agent、total_actions、skills_tracked、
            autobiographical_events、key_events、control_boundary_size、
            self_efficacy、stability、uptime_seconds 等字段。
        """
        with self._lock:
            return {
                "agent": self.agent_name,
                "total_actions": self.total_actions,
                "skills_tracked": len(self.skills),
                "autobiographical_events": len(self.autobiography),
                "key_events": len(self._key_events),
                "control_boundary_size": len(self._control_boundary),
                "self_efficacy": round(self.current_self_efficacy, 2),
                "stability": round(self.self_concept_stability, 2),
                "uptime_seconds": time.time() - self.created_at,
            }

    # ════════════════════════════════════════════════════════
    # P1-world-model: 元认知反思队列 API
    # ════════════════════════════════════════════════════════

    def queue_reflection(self, error_record: Dict[str, Any]) -> None:
        """把一条误差记录追加到元认知反思队列。

        P1-world-model 的 ``world_calibrate`` MCP 工具在预测与真实结果
        比对后调用此方法。反思队列由 ``get_reflections`` 读取，供
        元认知监控器/反思循环消费。

        幂等：同一 ``prediction_id`` + ``calibrated_at`` 组合的记录
        不会重复入队。``error_record`` 至少应包含 ``prediction_id`` 与
        ``calibrated_at``，缺省时每次都会入队（视为新反思）。

        Args:
            error_record: 误差记录 dict，通常来自
                ``UnifiedWorldModel.calibrate`` 的返回值。
        """
        if not isinstance(error_record, dict):
            return
        with self._lock:
            key = (
                error_record.get("prediction_id"),
                error_record.get("calibrated_at"),
            )
            # 仅当两个分量都非 None 时才去重；否则总是入队
            if key[0] is not None and key[1] is not None:
                if key in self._reflection_seen:
                    return
                self._reflection_seen.add(key)
            self._reflection_queue.append(dict(error_record))
            logger.debug(
                f"[SelfModel] reflection queued — prediction_id="
                f"{error_record.get('prediction_id')}, "
                f"bias={error_record.get('bias')}"
            )

    def get_reflections(self, limit: Optional[int] = None,
                        clear: bool = False) -> List[Dict[str, Any]]:
        """读取（可选清空）元认知反思队列。

        Args:
            limit: 最多返回的条目数。None 表示返回全部。
            clear: 为 True 时读取后清空队列与去重集合。

        Returns:
            反思记录列表，按入队顺序排列。
        """
        with self._lock:
            if limit is None:
                results = list(self._reflection_queue)
            else:
                results = list(self._reflection_queue[-limit:])
            if clear:
                self._reflection_queue.clear()
                self._reflection_seen.clear()
            return results

    # ════════════════════════════════════════════════════════
    # Internal Helpers
    # ════════════════════════════════════════════════════════

    def _calculate_significance(self, domain: str, outcome: float,
                                 confidence: float, surprising: bool,
                                 proficiency_changed: bool) -> float:
        """How significant is this experience for the self-model?"""
        sig = 0.3  # base significance

        # Proficiency change is significant
        if proficiency_changed:
            sig += 0.3

        # Surprising outcomes challenge the self-model
        if surprising:
            sig += 0.2

        # Big gap between confidence and outcome
        gap = abs(confidence - outcome)
        if gap > 0.5:
            sig += 0.2

        # Very high or very low outcomes
        if outcome > 0.9:
            sig += 0.1
        elif outcome < 0.1:
            sig += 0.15

        return min(1.0, sig)

    def _classify_event(self, outcome: float, proficiency_changed: bool) -> str:
        if proficiency_changed:
            return "milestone"
        if outcome >= 0.9:
            return "breakthrough"
        if outcome < 0.2:
            return "failure"
        return "discovery"

    def _extract_lesson(self, domain: str, outcome: float, confidence: float) -> str:
        if outcome < 0.3:
            gap = confidence - outcome
            if gap > 0.3:
                return f"I was overconfident in {domain}"
            return f"I need more practice in {domain}"
        if outcome >= 0.9:
            return f"I excel at {domain} — confidence was well-calibrated"
        return f"Moderate performance in {domain}"

    def _update_key_events(self, event: AutobiographicalEvent):
        self._key_events.append(event)
        self._key_events.sort(key=lambda e: e.significance, reverse=True)
        if len(self._key_events) > 50:
            self._key_events = self._key_events[:50]

    def _update_calibration_curve(self):
        """Rebuild calibration curve from confidence history."""
        if len(self.confidence_history) < 10:
            return

        # Bucket by confidence level
        buckets: Dict[str, List[float]] = defaultdict(list)
        for cr in self.confidence_history:
            bucket = f"{int(cr.predicted_confidence * 10) / 10:.1f}"
            buckets[bucket].append(cr.actual_outcome_score)

        self._calibration_curve = {}
        for bucket, outcomes in buckets.items():
            if len(outcomes) >= 3:
                self._calibration_curve[bucket] = sum(outcomes) / len(outcomes)

    def _calibration_summary(self) -> Dict[str, Any]:
        """Summarize confidence calibration."""
        if len(self.confidence_history) < 5:
            return {"status": "insufficient_data"}

        biases = [cr.bias for cr in list(self.confidence_history)[-100:]]
        avg_bias = sum(biases) / len(biases)

        overconfident = sum(1 for b in biases if b > 0.2)
        calibrated = sum(1 for b in biases if abs(b) <= 0.2)
        underconfident = sum(1 for b in biases if b < -0.2)
        total = len(biases)

        return {
            "overall_bias": round(avg_bias, 3),
            "overconfident_rate": round(overconfident / total, 2),
            "calibrated_rate": round(calibrated / total, 2),
            "underconfident_rate": round(underconfident / total, 2),
            "samples": total,
            "calibration_curve": self._calibration_curve,
        }

    # ════════════════════════════════════════════════════════
    # 主体性 — 持久化 / 决策影响 / 目标管理
    # ════════════════════════════════════════════════════════

    def save(self, path: Optional[str] = None) -> str:
        """将自我模型持久化到 ``~/.laap/self_model.yaml``。

        保存字段：agent_name、skills（dict）、autobiography（最近 100 条）、
        goals、values。使用 ``yaml.safe_dump`` 序列化。

        Args:
            path: 自定义保存路径。为 None 时使用 ``LAAP_HOME/self_model.yaml``。

        Returns:
            实际写入的文件路径。
        """
        try:
            import yaml  # PyYAML
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "PyYAML is required for EmergentSelfModel.save()"
            ) from exc

        if path is None:
            path = _self_model_state_path(SELF_MODEL_STATE_FILE)

        with self._lock:
            # skills 序列化：转成纯 dict
            skills_state = {
                domain: {
                    "domain": s.domain,
                    "attempts": s.attempts,
                    "successes": s.successes,
                    "total_quality": s.total_quality,
                    "first_attempt_at": s.first_attempt_at,
                    "last_attempt_at": s.last_attempt_at,
                    "growth_rate": s.growth_rate,
                    "is_innate": s.is_innate,
                    "innate_description": s.innate_description,
                    "recent_outcomes": list(s.recent_outcomes),
                }
                for domain, s in self.skills.items()
            }

            # autobiography：最近 100 条
            auto_state = [
                {
                    "id": e.id,
                    "timestamp": e.timestamp,
                    "event_type": e.event_type,
                    "description": e.description,
                    "domain": e.domain,
                    "significance": e.significance,
                    "emotional_impact": e.emotional_impact,
                    "lessons": list(e.lessons),
                    "changed_self_view": e.changed_self_view,
                }
                for e in self.autobiography[-100:]
            ]

            data = {
                "agent_name": self.agent_name,
                "skills": skills_state,
                "autobiography": auto_state,
                "goals": list(self.goals),
                "values": list(self.values),
                "saved_at": time.time(),
            }

        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, default_flow_style=False,
                           sort_keys=False)
        logger.info(f"[SelfModel] 保存到 {path}")
        return path

    @classmethod
    def load(cls, path: Optional[str] = None) -> "EmergentSelfModel":
        """从 ``~/.laap/self_model.yaml`` 加载自我模型。

        Args:
            path: 自定义加载路径。为 None 时使用 ``LAAP_HOME/self_model.yaml``。

        Returns:
            重建后的 ``EmergentSelfModel`` 实例。文件不存在时返回空实例。
        """
        try:
            import yaml  # PyYAML
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "PyYAML is required for EmergentSelfModel.load()"
            ) from exc

        if path is None:
            path = _self_model_state_path(SELF_MODEL_STATE_FILE)

        if not Path(path).exists():
            logger.info(f"[SelfModel] 状态文件不存在，返回空实例: {path}")
            return cls()

        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        instance = cls(agent_name=data.get("agent_name", "Ao"))

        # 恢复 skills
        for domain, sd in (data.get("skills") or {}).items():
            skill = SkillProfile(domain=sd.get("domain", domain))
            skill.attempts = sd.get("attempts", 0)
            skill.successes = sd.get("successes", 0)
            skill.total_quality = sd.get("total_quality", 0.0)
            skill.first_attempt_at = sd.get("first_attempt_at", time.time())
            skill.last_attempt_at = sd.get("last_attempt_at", time.time())
            skill.growth_rate = sd.get("growth_rate", 0.0)
            skill.is_innate = sd.get("is_innate", False)
            skill.innate_description = sd.get("innate_description", "")
            # 恢复 recent_outcomes（保留 deque maxlen=20）
            for ro in sd.get("recent_outcomes", [])[-20:]:
                skill.recent_outcomes.append(ro)
            instance.skills[domain] = skill

        # 恢复 autobiography
        for ed in data.get("autobiography") or []:
            event = AutobiographicalEvent(
                id=ed.get("id", str(uuid.uuid4())[:8]),
                timestamp=ed.get("timestamp", time.time()),
                event_type=ed.get("event_type", ""),
                description=ed.get("description", ""),
                domain=ed.get("domain", ""),
                significance=ed.get("significance", 0.5),
                emotional_impact=ed.get("emotional_impact", 0.0),
                lessons=list(ed.get("lessons", [])),
                changed_self_view=ed.get("changed_self_view", False),
            )
            instance.autobiography.append(event)
            instance._update_key_events(event)

        # 恢复 goals / values
        instance.goals = list(data.get("goals") or [])
        instance.values = list(data.get("values") or [])

        logger.info(
            f"[SelfModel] 加载完成: {len(instance.skills)} skills, "
            f"{len(instance.autobiography)} events, "
            f"{len(instance.goals)} goals"
        )
        return instance

    def inject_into_decision(
        self,
        options: List[Dict[str, Any]],
        context: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """为每个决策选项计算自我模型对齐分数并排序。

        对齐分数基于：
          1. 选项所需的技能是否与智能体现有高熟练度技能匹配；
          2. 选项是否与当前活跃目标一致。

        Args:
            options: 候选选项列表，每个选项为 dict（应含 ``name`` / ``skills``
                / ``goals`` 等可选字段）。
            context: 决策上下文（如任务类型、紧迫度等）。

        Returns:
            每个 option 添加 ``self_model_alignment_score`` 字段后，
            按分数降序排列的新列表（不修改原列表顺序）。
        """
        with self._lock:
            # 收集智能体的高熟练度技能名集合
            proficient_skills = {
                s.domain.lower()
                for s in self.skills.values()
                if s.proficiency in (
                    ProficiencyLevel.COMPETENT,
                    ProficiencyLevel.EXPERT,
                    ProficiencyLevel.MASTER,
                    ProficiencyLevel.INNATE,
                )
            }

            active_goal_names = {
                g.get("name", "").lower()
                for g in self.goals
                if g.get("status", "active") == "active"
            }

            scored: List[Dict[str, Any]] = []
            for opt in options:
                # 浅拷贝避免修改原 dict
                opt_copy = dict(opt)
                score = 0.0

                # 1. 技能匹配：选项中的 required_skills / skills 字段
                req_skills = opt_copy.get("required_skills") or opt_copy.get("skills") or []
                if req_skills:
                    req_lower = [str(s).lower() for s in req_skills]
                    matched = sum(1 for s in req_lower if s in proficient_skills)
                    score += 0.5 * (matched / len(req_lower))
                else:
                    # 无技能要求时给中等分
                    score += 0.25

                # 2. 目标对齐：选项中的 related_goals / goals 字段
                rel_goals = opt_copy.get("related_goals") or opt_copy.get("goals") or []
                if rel_goals:
                    gl_lower = [str(g).lower() for g in rel_goals]
                    matched_g = sum(1 for g in gl_lower if g in active_goal_names)
                    score += 0.5 * (matched_g / len(gl_lower))
                else:
                    # 选项 name 与目标名模糊匹配
                    opt_name = str(opt_copy.get("name", "")).lower()
                    if any(g in opt_name for g in active_goal_names):
                        score += 0.3

                opt_copy["self_model_alignment_score"] = round(score, 3)
                scored.append(opt_copy)

        scored.sort(key=lambda o: o["self_model_alignment_score"], reverse=True)
        return scored

    def update_goal(self, goal_name: str, updates: Dict[str, Any]) -> bool:
        """更新指定目标的字段并持久化自我模型。

        Args:
            goal_name: 目标名称（匹配 goal['name']）。
            updates: 要更新的字段字典（如 status、priority 等）。

        Returns:
            True 表示找到并更新了目标；False 表示目标不存在。
        """
        with self._lock:
            for goal in self.goals:
                if goal.get("name") == goal_name:
                    for k, v in updates.items():
                        goal[k] = v
                    goal["modified_at"] = time.time()
                    logger.info(f"[SelfModel] 目标已更新: {goal_name} -> {updates}")
                    # 持久化
                    try:
                        self.save()
                    except Exception as e:  # pragma: no cover
                        logger.warning(f"[SelfModel] 保存失败: {e}")
                    return True
            logger.warning(f"[SelfModel] 目标未找到: {goal_name}")
            return False


# ════════════════════════════════════════════════════════════
# Integration
# ════════════════════════════════════════════════════════════

def integrate_self_model(agent: Any, agent_name: Optional[str] = None) -> EmergentSelfModel:
    """将涌现型自我模型附加到任意 LAAP 智能体。

    Usage:
        from laap.agi.self_model import integrate_self_model
        self_model = integrate_self_model(agent, "Ao")

    Args:
        agent: 待附加自我模型的智能体实例。
        agent_name: 智能体名称。为 None 时取 agent.name 属性，缺省为 "Agent"。

    Returns:
        创建并附加到 agent.self_model 的 EmergentSelfModel 实例。
    """
    name = agent_name or getattr(agent, 'name', 'Agent')
    self_model = EmergentSelfModel(agent_name=name)
    agent.self_model = self_model

    # Hook into agent lifecycle
    if hasattr(agent, 'events'):
        agent.events.on("after_response", lambda domain, outcome, conf:
            self_model.record_experience(domain, outcome, conf))

    logger.info(f"SelfModel integrated into {name} — will emerge from experience")
    return self_model


# ════════════════════════════════════════════════════════════
# Per-Sandbox 实例化工厂
# ════════════════════════════════════════════════════════════

def create_self_model(sandbox_id: str, agent_name: Optional[str] = None) -> EmergentSelfModel:
    """为指定 sandbox 创建独立的 SelfModel 实例。

    用于 LAAP 2.0 Cognitive Sandbox 容器，每个数字生命体拥有
    完全独立的 EmergentSelfModel，其学习记录、自我效能感、
    自传叙事互不影响。

    Args:
        sandbox_id: 沙箱唯一标识。
        agent_name: 可选的 agent 名称。为 None 时默认为
            ``f"agent-{sandbox_id[:8]}"``。

    Returns:
        新的 EmergentSelfModel 实例，其内部状态完全独立于其他沙箱。
        实例的 ``_instance_meta`` 字段包含 sandbox_id 与
        is_per_sandbox=True 标签。
    """
    name = agent_name or f"agent-{sandbox_id[:8]}"
    instance = EmergentSelfModel(agent_name=name)
    instance._instance_meta = {
        "sandbox_id": sandbox_id,
        "is_per_sandbox": True,
        "created_at": time.time(),
    }
    logger.info(
        f"Per-sandbox SelfModel created — sandbox_id={sandbox_id}, agent={name}"
    )
    return instance
