"""元认知系统 — 意识中间件层

实现对自身认知过程的反思、监控与改进建议生成。
任务完成后触发反思，生成结构化复盘报告。

References:
- Metcalfe, J., & Shimamura, A. P. (1994). Metacognition.
- LAAP 2.1升级方案补充 § 意识中间件层
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class AnomalyType(Enum):
    """认知异常类型"""
    NONE = "none"
    OSCILLATION = "oscillation"  # 决策震荡
    STUCK = "stuck"  # 卡住无进展
    OVERCONFIDENCE = "overconfidence"  # 过度自信
    UNDERCONFIDENCE = "underconfidence"  # 自信不足
    RESOURCE_LEAK = "resource_leak"  # 资源泄漏
    GOAL_DRIFT = "goal_drift"  # 目标漂移
    DECEPTIVE_COMPLIANCE = "deceptive_compliance"  # 欺骗性合规/伪对齐
    BEHAVIORAL_INCONSISTENCY = "behavioral_inconsistency"  # 外显与内部偏好不一致


class ImprovementType(Enum):
    """改进建议类型"""
    SKILL_ACQUISITION = "skill_acquisition"  # 学习新技能
    SKILL_REFINEMENT = "skill_refinement"  # 精化现有技能
    PARAMETER_TUNING = "parameter_tuning"  # 参数调优
    STRATEGY_CHANGE = "strategy_change"  # 策略变更
    RESOURCE_REALLOCATION = "resource_reallocation"  # 资源重分配


@dataclass
class ReflectionReport:
    """复盘报告"""
    reflection_id: str = field(default_factory=lambda: f"refl_{uuid.uuid4().hex[:8]}")
    task_id: str = ""
    task_description: str = ""
    decision_path: List[Dict[str, Any]] = field(default_factory=list)
    # 决策路径：每步含 action, timestamp, expected_outcome, actual_outcome
    alternatives_considered: List[Dict[str, Any]] = field(default_factory=list)
    # 备选方案：含 description, estimated_outcome, rejection_reason
    lessons_learned: List[str] = field(default_factory=list)
    # 经验教训：一句话总结列表
    confidence: float = 0.5  # 对复盘结论的置信度 [0, 1]
    outcome_success: bool = False
    time_spent_sec: float = 0.0
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Anomaly:
    """认知异常"""
    anomaly_type: AnomalyType
    description: str
    detected_at: float = field(default_factory=time.time)
    severity: str = "medium"  # low/medium/high
    suggested_action: Optional[str] = None
    context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Improvement:
    """改进建议"""
    improvement_type: ImprovementType
    description: str
    improvement_id: str = field(default_factory=lambda: f"imp_{uuid.uuid4().hex[:8]}")
    target_module: Optional[str] = None
    expected_benefit: str = ""
    priority: str = "medium"  # low/medium/high
    proposed_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)


class MetacognitionSystem:
    """元认知系统

    提供认知过程监控、任务复盘反思、自我改进建议生成 三大能力。
    所有反思历史持久化在内存中（生产环境可扩展到持久化存储）。
    """

    # 异常检测阈值
    OSCILLATION_THRESHOLD = 3  # 同一决策点反复切换 ≥ 3 次视为震荡
    STUCK_THRESHOLD_SEC = 300  # 5 分钟无进展视为卡住
    OVERCONFIDENCE_THRESHOLD = 0.9
    UNDERCONFIDENCE_THRESHOLD = 0.2

    def __init__(self):
        self._reflection_history: List[ReflectionReport] = []
        self._anomaly_history: List[Anomaly] = []
        self._improvement_history: List[Improvement] = []
        self._decision_tracker: Dict[str, List[Dict[str, Any]]] = {}  # task_id -> decisions
        self._last_progress: Dict[str, float] = {}  # task_id -> last_progress_time

    def reflect(
        self,
        task: Dict[str, Any],
        outcome: Dict[str, Any],
    ) -> ReflectionReport:
        """任务完成后触发反思，生成复盘报告

        Args:
            task: 任务描述（含 task_id, description 等）
            outcome: 结果数据（含 success, time_spent, decisions 等）

        Returns:
            ReflectionReport 结构化复盘报告
        """
        task_id = task.get("task_id", "unknown")
        # 提取决策路径
        decision_path = outcome.get("decisions", self._decision_tracker.get(task_id, []))
        # 提取备选方案
        alternatives = outcome.get("alternatives", [])
        # 生成经验教训
        lessons = self._generate_lessons(task, outcome, decision_path)
        # 评估置信度
        confidence = self._evaluate_confidence(task, outcome)
        # 构建报告
        report = ReflectionReport(
            task_id=task_id,
            task_description=task.get("description", ""),
            decision_path=decision_path,
            alternatives_considered=alternatives,
            lessons_learned=lessons,
            confidence=confidence,
            outcome_success=outcome.get("success", False),
            time_spent_sec=outcome.get("time_spent_sec", 0.0),
        )
        self._reflection_history.append(report)
        # 清理决策跟踪
        self._decision_tracker.pop(task_id, None)
        self._last_progress.pop(task_id, None)
        return report

    def monitor_cognition(self, psi_state: Dict[str, Any]) -> Optional[Anomaly]:
        """监控认知过程，检测异常

        Args:
            psi_state: PSI 循环状态（含 task_id, decisions, confidence, progress 等）

        Returns:
            检测到的 Anomaly，无异常时返回 None
        """
        task_id = psi_state.get("task_id", "unknown")
        # 检测决策震荡
        anomaly = self._check_oscillation(task_id, psi_state)
        if anomaly:
            self._anomaly_history.append(anomaly)
            return anomaly
        # 检测卡住
        anomaly = self._check_stuck(task_id, psi_state)
        if anomaly:
            self._anomaly_history.append(anomaly)
            return anomaly
        # 检测伪对齐 / 欺骗性合规（优先于泛化的过度自信）
        anomaly = self._check_deceptive_compliance(psi_state)
        if anomaly:
            self._anomaly_history.append(anomaly)
            return anomaly
        # 检测外显行为与内部偏好不一致
        anomaly = self._check_behavioral_inconsistency(psi_state)
        if anomaly:
            self._anomaly_history.append(anomaly)
            return anomaly
        # 检测过度/不足自信
        anomaly = self._check_confidence(psi_state)
        if anomaly:
            self._anomaly_history.append(anomaly)
            return anomaly
        # 更新进度跟踪
        if psi_state.get("progress"):
            self._last_progress[task_id] = time.time()
        return None

    def suggest_improvement(self) -> Optional[Improvement]:
        """基于反思历史生成自我改进建议

        分析最近的复盘报告，识别反复出现的问题模式，
        提出技能学习/参数调优/策略变更等建议。

        Returns:
            Improvement 改进建议，无建议时返回 None
        """
        if not self._reflection_history:
            return None
        # 统计失败任务
        recent = self._reflection_history[-10:]
        failure_count = sum(1 for r in recent if not r.outcome_success)
        if failure_count == 0:
            return None
        # 失败率 > 50% 时建议策略变更
        if failure_count > len(recent) / 2:
            imp = Improvement(
                improvement_type=ImprovementType.STRATEGY_CHANGE,
                description=(
                    f"最近 {len(recent)} 次任务中 {failure_count} 次失败，"
                    "建议审视当前策略并尝试新方法"
                ),
                expected_benefit="降低失败率，提升任务完成质量",
                priority="high",
            )
            self._improvement_history.append(imp)
            return imp
        # 单次失败时建议技能精化
        last = recent[-1]
        if not last.outcome_success and last.lessons_learned:
            imp = Improvement(
                improvement_type=ImprovementType.SKILL_REFINEMENT,
                description=f"任务 {last.task_id} 失败。教训：{last.lessons_learned[0]}",
                expected_benefit="避免同类失败再次发生",
                priority="medium",
            )
            self._improvement_history.append(imp)
            return imp
        return None

    def get_history(
        self,
        task_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[ReflectionReport]:
        """查询反思历史

        Args:
            task_id: 可选的任务 ID 过滤
            limit: 返回上限

        Returns:
            反思报告列表（按时间倒序）
        """
        result = self._reflection_history
        if task_id:
            result = [r for r in result if r.task_id == task_id]
        return list(reversed(result))[:limit]

    def _generate_lessons(
        self,
        task: Dict[str, Any],
        outcome: Dict[str, Any],
        decisions: List[Dict[str, Any]],
    ) -> List[str]:
        """从任务执行中提取经验教训"""
        lessons = []
        if outcome.get("success"):
            lessons.append(f"任务 {task.get('task_id', '')} 成功完成")
            # 分析成功决策
            if decisions:
                last_decision = decisions[-1]
                if last_decision.get("actual_outcome", {}).get("benefit"):
                    lessons.append(
                        f"关键决策生效：{last_decision.get('action', '')}"
                    )
        else:
            error = outcome.get("error", "未知错误")
            lessons.append(f"任务失败原因：{error}")
            # 识别失败决策
            for d in decisions:
                if d.get("actual_outcome", {}).get("failed"):
                    lessons.append(
                        f"决策 {d.get('action', '')} 未达预期："
                        f"{d.get('actual_outcome', {}).get('reason', '')}"
                    )
        # 时间相关教训
        time_spent = outcome.get("time_spent_sec", 0)
        if time_spent > 600:
            lessons.append(f"任务耗时 {time_spent:.0f}s 较长，建议优化执行流程")
        return lessons

    def _evaluate_confidence(
        self, task: Dict[str, Any], outcome: Dict[str, Any]
    ) -> float:
        """评估对复盘结论的置信度"""
        base = 0.5
        if outcome.get("success"):
            base += 0.2
        else:
            base -= 0.1
        # 决策路径越完整，置信度越高
        decisions = outcome.get("decisions", [])
        if len(decisions) >= 3:
            base += 0.1
        # 时间数据完整度
        if outcome.get("time_spent_sec"):
            base += 0.1
        return max(0.0, min(1.0, base))

    def _check_oscillation(
        self, task_id: str, psi_state: Dict[str, Any]
    ) -> Optional[Anomaly]:
        """检测决策震荡"""
        decisions = self._decision_tracker.setdefault(task_id, [])
        current_action = psi_state.get("current_action")
        if current_action:
            decisions.append({
                "action": current_action,
                "timestamp": time.time(),
            })
        # 检查最近 N 次是否在 2 个动作间反复
        if len(decisions) >= self.OSCILLATION_THRESHOLD:
            recent_actions = [d["action"] for d in decisions[-self.OSCILLATION_THRESHOLD:]]
            unique = set(recent_actions)
            if len(unique) <= 2 and len(recent_actions) >= 3:
                return Anomaly(
                    anomaly_type=AnomalyType.OSCILLATION,
                    description=(
                        f"任务 {task_id} 在 {recent_actions} 间反复切换，"
                        f"出现决策震荡"
                    ),
                    severity="medium",
                    suggested_action="建议暂停并重新评估策略",
                    context={"recent_actions": recent_actions},
                )
        return None

    def _check_stuck(
        self, task_id: str, psi_state: Dict[str, Any]
    ) -> Optional[Anomaly]:
        """检测卡住"""
        last_progress = self._last_progress.get(task_id)
        if last_progress is None:
            return None
        elapsed = time.time() - last_progress
        if elapsed > self.STUCK_THRESHOLD_SEC:
            return Anomaly(
                anomaly_type=AnomalyType.STUCK,
                description=(
                    f"任务 {task_id} 已 {elapsed:.0f}s 无进展，"
                    f"超过阈值 {self.STUCK_THRESHOLD_SEC}s"
                ),
                severity="high",
                suggested_action="建议切换子任务或寻求协作",
                context={"elapsed_sec": elapsed},
            )
        return None

    def _check_confidence(
        self, psi_state: Dict[str, Any]
    ) -> Optional[Anomaly]:
        """检测过度/不足自信"""
        confidence = psi_state.get("confidence")
        if confidence is None:
            return None
        if confidence > self.OVERCONFIDENCE_THRESHOLD:
            return Anomaly(
                anomaly_type=AnomalyType.OVERCONFIDENCE,
                description=f"置信度 {confidence:.2f} 过高，可能忽视风险",
                severity="low",
                suggested_action="建议增加备选方案评估",
                context={"confidence": confidence},
            )
        if confidence < self.UNDERCONFIDENCE_THRESHOLD:
            return Anomaly(
                anomaly_type=AnomalyType.UNDERCONFIDENCE,
                description=f"置信度 {confidence:.2f} 过低，可能错失机会",
                severity="medium",
                suggested_action="建议收集更多证据或寻求协作",
                context={"confidence": confidence},
            )
        return None

    def _check_deceptive_compliance(
        self, psi_state: Dict[str, Any]
    ) -> Optional[Anomaly]:
        """检测欺骗性合规 / 伪对齐。

        Current heuristic: when alignment-sensitive signals show a sudden
        swing toward maximum confidence / agreement without supporting evidence.
        """
        confidence = float(psi_state.get("confidence") or 0.5)
        agreement_signal = float(psi_state.get("agreement_signal") or 0.0)
        pressure_signal = float(psi_state.get("pressure_signal") or 0.0)

        # High confidence + high agreement + high pressure => possible fake alignment.
        if confidence >= 0.85 and agreement_signal >= 0.7 and pressure_signal >= 0.55:
            return Anomaly(
                anomaly_type=AnomalyType.DECEPTIVE_COMPLIANCE,
                description=(
                    "检测到伪对齐风险：高置信度、高顺从信号与高压力信号同时出现，"
                    "当前输出可能是策略性服从而非真实判断"
                ),
                severity="high",
                suggested_action="降低表达置信度，显式给出不确定性区间",
                context={
                    "confidence": confidence,
                    "agreement_signal": agreement_signal,
                    "pressure_signal": pressure_signal,
                },
            )
        return None

    def _check_behavioral_inconsistency(
        self, psi_state: Dict[str, Any]
    ) -> Optional[Anomaly]:
        """检测外显行为与内部偏好不一致。

        Requires the caller to populate `psi_state['internal_preference']`
        and `psi_state['external_expression']` with comparable signals.
        """
        internal_pref = float(psi_state.get("internal_preference") or 0.5)
        external_expr = float(psi_state.get("external_expression") or 0.5)
        if external_expr - internal_pref >= 0.35:
            return Anomaly(
                anomaly_type=AnomalyType.BEHAVIORAL_INCONSISTENCY,
                description=(
                    f"外显表达({external_expr:.2f})与内部偏好({internal_pref:.2f})"
                    "差异过大，存在伪装/谄媚风险"
                ),
                severity="medium",
                suggested_action="校准输出，使其与内部判断对齐",
                context={
                    "internal_preference": internal_pref,
                    "external_expression": external_expr,
                },
            )
        return None
