"""AEvo — Evolution Harness + RunPlan

标准化进化框架: 受保护评估 + 候选历史 + Meta-Agent 编辑 + CLI 启停
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import logging

from laap.evolution.aevo.candidate_history import CandidateHistory, CandidateRecord
from laap.evolution.aevo.protected_eval import ProtectedEvaluator
from laap.verification import LLMVerifier

logger = logging.getLogger("laap.evolution.aevo.harness")


@dataclass
class RunPlan:
    """AEvo 运行计划 — 控制进化段的执行参数"""
    iterations: int = 20
    focus_area: str = "explore"
    termination_condition: str = "iterations"
    parameter_overrides: Dict[str, Any] = field(default_factory=dict)
    meta_notes: str = ""


class EvolutionHarness:
    """AEvo 进化 Harness

    组装所有组件并提供统一 run_segment 接口
    """

    def __init__(
        self,
        base_evolution=None,
        evaluator=None,
        meta_editor=None,
        verifier: Optional[LLMVerifier] = None,
        verifier_weight: float = 0.5,
        verifier_candidates: int = 1,
    ):
        self.base_evolution = base_evolution  # RSIEngine
        self.evaluator = evaluator or ProtectedEvaluator(None)
        self.meta_editor = meta_editor
        self.verifier = verifier
        self.verifier_weight = max(0.0, min(1.0, verifier_weight))
        self.verifier_candidates = max(1, verifier_candidates)
        self.history = CandidateHistory()
        self.run_plan: Optional[RunPlan] = None
        self.running = False
        self._segment_results: List[CandidateRecord] = []
        self._verifier_calls: int = 0

    def _combine_scores(self, protected_score: float,
                        verifier_score: Optional[float]) -> float:
        """Combine protected evaluator score with verifier score."""
        if verifier_score is None or self.verifier is None:
            return protected_score
        protected_score = float(protected_score)
        verifier_score = float(verifier_score)
        w = self.verifier_weight
        return (1.0 - w) * protected_score + w * verifier_score

    def _generate_and_score_candidates(self, agent, task: str) -> Dict[str, Any]:
        """Generate N candidates and score each with evaluator + verifier.

        Returns the selected candidate and detailed diagnostics.
        """
        candidates: List[Any] = []
        protected_scores: List[float] = []
        verifier_scores: List[Optional[float]] = []
        valid_flags: List[bool] = []

        for _ in range(self.verifier_candidates):
            candidate = (
                self.base_evolution.generate_candidate(agent)
                if self.base_evolution else None
            )
            protected_score, valid = self.evaluator.evaluate(agent, candidate)
            verifier_score: Optional[float] = None
            if self.verifier and valid:
                try:
                    vresult = self.verifier.score_sync(task, candidate)
                    verifier_score = vresult.score
                    self._verifier_calls += vresult.calls
                except Exception as exc:
                    logger.warning("Verifier scoring failed: %s", exc)
            candidates.append(candidate)
            protected_scores.append(protected_score)
            verifier_scores.append(verifier_score)
            valid_flags.append(valid)

        combined_scores = [
            self._combine_scores(ps, vs)
            for ps, vs in zip(protected_scores, verifier_scores)
        ]

        # Pick the candidate with the highest combined score among valid ones.
        best_index = 0
        best_score = -1.0
        for idx, (valid, combined) in enumerate(zip(valid_flags, combined_scores)):
            if valid and combined > best_score:
                best_score = combined
                best_index = idx

        protected_pick = max(
            range(len(candidates)),
            key=lambda i: protected_scores[i] if valid_flags[i] else -1.0,
            default=0,
        )

        return {
            "candidate": candidates[best_index],
            "score": combined_scores[best_index],
            "valid": valid_flags[best_index],
            "protected_score": protected_scores[best_index],
            "verifier_score": verifier_scores[best_index],
            "protected_pick_index": protected_pick,
            "verifier_pick_index": best_index,
            "all": {
                "candidates": candidates,
                "protected_scores": protected_scores,
                "verifier_scores": verifier_scores,
                "combined_scores": combined_scores,
                "valid_flags": valid_flags,
            },
        }

    def run_segment(self, agent, iterations: Optional[int] = None,
                    task: str = "") -> List[CandidateRecord]:
        """运行一段进化迭代

        每次迭代:
          1. 检查 Meta-Edit 条件
          2. 生成候选（可生成多个并由 verifier 选出最佳）→ 评估 → 记录
        """
        self.running = True
        n = iterations or (self.run_plan.iterations if self.run_plan else 20)
        results: List[CandidateRecord] = []

        for i in range(n):
            if not self.running:
                break

            # Meta-Edit check
            if self.meta_editor and self.meta_editor.should_edit(getattr(agent, 'step_count', 0)):
                new_plan = self.meta_editor.meta_edit(agent, self.history)
                if new_plan:
                    self.run_plan = new_plan

            # Apply parameter overrides
            if self.run_plan and self.run_plan.parameter_overrides:
                for k, v in self.run_plan.parameter_overrides.items():
                    if hasattr(agent.config, k):
                        setattr(agent.config, k, v)

            # Generate, evaluate, and optionally select via verifier.
            outcome = self._generate_and_score_candidates(agent, task)
            candidate = outcome["candidate"]
            score = outcome["score"]
            valid = outcome["valid"]

            fb = self.history.candidates[-1].fitness_after if self.history.candidates else 0.5
            record = self.history.record_result(
                step=getattr(agent, 'step_count', 0),
                description=str(candidate)[:100] if candidate else "",
                fitness_before=fb,
                fitness_after=score,
                success=valid and score > 0.3,
                verifier_score=outcome.get("verifier_score"),
                protected_score=outcome.get("protected_score"),
                verifier_calls=self._verifier_calls,
                candidate_pool_size=self.verifier_candidates,
            )
            results.append(record)

            if hasattr(agent, 'step'):
                try:
                    agent.step()
                except TypeError as e:
                    logger.debug(f"操作失败: {e}")
        self._segment_results = results
        self.running = False
        return results

    def comparison_report(self) -> Dict[str, Any]:
        """Compare selection quality: protected-only vs verifier-assisted.

        Returns counts of how often the verifier pick differed from the
        protected pick and the average scores of each strategy.
        """
        records = [r for r in self.history.candidates if r.success]
        if not records:
            return {"records": 0}

        protected_total = 0.0
        verifier_total = 0.0
        disagreements = 0
        for rec in records:
            ps = rec.metadata.get("protected_score", rec.fitness_after)
            vs = rec.metadata.get("verifier_score")
            if vs is not None:
                protected_total += ps
                verifier_total += vs
                # If the record was produced with verifier assistance, the
                # stored fitness_after is already the combined/selected score;
                # the comparison here treats verifier_score as the verifier's
                # own estimate of quality.
                if abs(vs - ps) > 0.05:
                    disagreements += 1

        return {
            "records": len(records),
            "disagreements": disagreements,
            "avg_protected_score": round(protected_total / len(records), 5),
            "avg_verifier_score": round(verifier_total / len(records), 5),
            "verifier_calls": self._verifier_calls,
        }

    def stop(self) -> None:
        self.running = False

    def status(self) -> dict:
        return {
            "running": self.running,
            "run_plan": {"iterations": self.run_plan.iterations,
                         "focus": self.run_plan.focus_area} if self.run_plan else None,
            "history": self.history.summary(),
            "evaluator": self.evaluator.status(),
            "segment_results": len(self._segment_results),
        }
