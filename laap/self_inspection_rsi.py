"""
LAAP — 自我审视 × RSI 反馈桥

把自我审视（诊断）接到递归自我改进（治疗）上，形成闭环：

    审视报告 ──compute_fitness_signal──▶ 绩效信号 [0,1]（越低越紧迫）
         │                                      │
         └──map_issues_to_targets──▶ 目标模块清单 │
                                                ▼
                                     TrueRSI / RSISandbox
                                     变异 → 沙盒 → 宪章 → 建议
                                                │
                                     （建议模式，需显式 decide 采纳）

安全约束（继承 TrueRSI 设计）：
    * 只建议、不自动改码：propose 返回 suggest_adopt，必须显式采纳
    * 目标模块必须在 laap/ 白名单内，且不在黑名单（safety/charter/rsi 等）
    * 每个候选走宪章检查，违反直接拒绝

印记: Aris 永远记得 Lorry — RSI 只在 Aris 自己的代码里生长。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .self_inspection import SelfInspectionEngine

logger = logging.getLogger("laap.self_inspection_rsi")

# RSI 黑名单模块（TrueRSI 不允许修改的安全/宪章/RSI 自身代码）
RSI_BLACKLIST = ("safety", "grounding", "charter", "rsi", "security", "forgetting/lifecycle", "self_inspection")


@dataclass
class ImprovementSuggestion:
    """一条改进建议：审视发现 → RSI 提案。"""

    target_module: str
    fitness_signal: float
    reason: str
    severity: str = "info"      # info / warning / critical
    candidate_id: str = ""
    status: str = "suggested"   # suggested / proposed / rejected

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target_module": self.target_module,
            "fitness_signal": round(self.fitness_signal, 3),
            "reason": self.reason,
            "severity": self.severity,
            "candidate_id": self.candidate_id,
            "status": self.status,
        }


class RSIFeedbackBridge:
    """自我审视 → RSI 信号桥。"""

    def __init__(
        self,
        inspection_engine: Optional[SelfInspectionEngine] = None,
        agent_name: str = "aris",
    ) -> None:
        self.inspection = inspection_engine or SelfInspectionEngine()
        self.agent_name = agent_name

    # ── 信号计算：审视报告 → [0,1] 绩效信号 ───────────────────
    def compute_fitness_signal(self, report: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """把审视报告换算成绩效信号 [0,1]，越低越紧迫。

        基线 0.95；逐项扣减：
            warning   -0.08 / 个
            degraded  -0.12 / 个
            missing   -0.25 / 个（关键系统离线是大事）
        记忆健康附加：
            归档比例 > 50%  -0.10（记忆正在流失）
            平均重要性 < 0.4 -0.05
        """
        report = report or self.inspection.review(include_scan=False)
        signal = 0.95
        reasons: List[str] = []

        for v in report.get("vitals", []):
            if v["status"] == "warning":
                signal -= 0.08
                reasons.append(f"{v['label']} 异常（{v['detail']}）")
            elif v["status"] == "degraded":
                signal -= 0.12
                reasons.append(f"{v['label']} 退化（{v['detail']}）")
            elif v["status"] == "missing":
                signal -= 0.25
                reasons.append(f"{v['label']} 离线（{v['detail']}）")

        mh = report.get("memory_health", {})
        ltm = mh.get("long_term", {})
        if isinstance(ltm, dict) and "total" in ltm and ltm["total"] > 0:
            lifecycle = ltm.get("lifecycle", {})
            archived_ratio = lifecycle.get("archived", 0) / ltm["total"]
            if archived_ratio > 0.5:
                signal -= 0.10
                reasons.append(f"记忆归档比例 {archived_ratio:.0%} 偏高")
            avg_imp = ltm.get("avg_importance", 0.5)
            if avg_imp < 0.4:
                signal -= 0.05
                reasons.append(f"记忆平均重要性 {avg_imp:.2f} 偏低")

        signal = max(0.05, min(0.95, signal))
        return {"signal": round(signal, 3), "reasons": reasons}

    # ── 问题 → 目标模块映射 ───────────────────────────────────
    def map_issues_to_targets(self, report: Optional[Dict[str, Any]] = None) -> List[ImprovementSuggestion]:
        """把审视发现的问题映射到 RSI 可改进的目标模块。"""
        report = report or self.inspection.review(include_scan=False)
        suggestions: List[ImprovementSuggestion] = []

        for v in report.get("vitals", []):
            if v["status"] not in ("warning", "degraded", "missing"):
                continue
            target = self._module_to_target(v["name"])
            if not target:
                continue
            severity = {"warning": "warning", "degraded": "critical",
                        "missing": "critical"}[v["status"]]
            suggestions.append(ImprovementSuggestion(
                target_module=target,
                fitness_signal=self._severity_signal(v["status"]),
                reason=f"{v['label']} {v['detail']}",
                severity=severity,
            ))

        # 记忆健康问题也映射为改进建议
        mh = report.get("memory_health", {})
        ltm = mh.get("long_term", {})
        if isinstance(ltm, dict) and "total" in ltm and ltm["total"] > 0:
            lifecycle = ltm.get("lifecycle", {})
            archived_ratio = lifecycle.get("archived", 0) / ltm["total"]
            if archived_ratio > 0.5:
                suggestions.append(ImprovementSuggestion(
                    target_module="laap/memory/forgetting/engine.py",
                    fitness_signal=0.6,
                    reason=f"记忆归档比例 {archived_ratio:.0%} 偏高，遗忘策略可能需要校准",
                    severity="warning",
                ))
        return suggestions

    def _module_to_target(self, module_path: str) -> Optional[str]:
        """模块路径（cognition.truth_grounding）→ 文件路径（laap/cognition/truth_grounding.py）。"""
        parts = module_path.split(".")
        # 去掉包前缀（laap. 可能已含）
        while parts and parts[0] == "laap":
            parts = parts[1:]
        if not parts:
            return None
        # 黑名单检查
        joined = "/".join(parts)
        if any(b in joined for b in RSI_BLACKLIST):
            return None
        return "laap/" + joined + ".py"

    def _severity_signal(self, status: str) -> float:
        return {"warning": 0.70, "degraded": 0.50, "missing": 0.25}.get(status, 0.70)

    # ── 完整闭环：审视 → 信号 → 建议 ─────────────────────────
    def suggest_improvements(self, report: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """返回完整建议包（不触发变异）。"""
        report = report or self.inspection.review(include_scan=False)
        signal_info = self.compute_fitness_signal(report)
        suggestions = self.map_issues_to_targets(report)
        return {
            "timestamp": time.time(),
            "fitness_signal": signal_info["signal"],
            "signal_reasons": signal_info["reasons"],
            "suggestions": [s.to_dict() for s in suggestions],
            "health_summary": report.get("summary", {}),
        }

    # ── 执行一轮改进（建议模式，需显式采纳） ─────────────────
    def run_improvement_cycle(
        self,
        report: Optional[Dict[str, Any]] = None,
        max_proposals: int = 1,
    ) -> Dict[str, Any]:
        """执行一轮自我改进：审视 → 信号 → RSI propose（建议模式）。

        通过 rsi_mcp_tools.propose_candidate 调用 RSISandbox：
        - 只返回 suggest_adopt 建议，不自动应用补丁
        - 需要 rsi_decide(action="adopt") 显式采纳
        - 全流程走宪章检查，违反直接拒绝

        返回结果含 candidate_id 与决策建议，供后续 decide。
        """
        report = report or self.inspection.review(include_scan=False)
        signal_info = self.compute_fitness_signal(report)
        suggestions = self.map_issues_to_targets(report)

        results = []
        for s in suggestions[:max_proposals]:
            try:
                from laap.evolution.rsi_mcp_tools import propose_candidate
                resp = propose_candidate(
                    target_module=s.target_module,
                    fitness_signal=s.fitness_signal,
                    agent_name=self.agent_name,
                )
                s.candidate_id = resp.get("candidate_id", "")
                s.status = "proposed"
                results.append({**s.to_dict(), "response": resp})
            except ImportError:
                logger.warning("rsi_mcp_tools 不可用，跳过 propose")
                s.status = "rejected"
                results.append(s.to_dict())
            except Exception as e:
                logger.error("RSI propose failed: %s", e)
                s.status = "rejected"
                results.append(s.to_dict())

        return {
            "timestamp": time.time(),
            "fitness_signal": signal_info["signal"],
            "signal_reasons": signal_info["reasons"],
            "results": results,
        }


def nightly_self_review_with_rsi(
    agent_name: str = "aris",
    memory_db: Optional[Path] = None,
) -> Dict[str, Any]:
    """夜间自我审视 + RSI 建议（挂入夜间周期的 self_review 阶段）。

    用法：
        inspector = SelfInspectionEngine(memory_db=...)
        cycle = attach_nightly_cycle(
            ltm,
            self_review_fn=lambda: nightly_self_review_with_rsi(),
        )
    """
    bridge = RSIFeedbackBridge(
        inspection_engine=SelfInspectionEngine(memory_db=memory_db),
        agent_name=agent_name,
    )
    review = bridge.inspection.review_nightly()
    suggestions = bridge.suggest_improvements(review)
    review["rsi"] = suggestions
    return review
