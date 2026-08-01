"""LAAP Orchestration — Quality Metrics (M6 E4).

Records task execution quality (success rate, latency, quality score)
and computes:

    • pass@k          — fraction of tasks that succeeded at least once
                        in their last k attempts.
    • transfer        — ID / OOD pass-rate ratio across two domains.
    • trend report    — cumulative time-series for charting.

Persistence: results can be exported to ``~/.laap/quality_metrics.json``
or an explicit path.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional


class QualityMetrics:
    """Records task results and computes quality metrics."""

    def __init__(self) -> None:
        self._results: List[Dict[str, Any]] = []
        self._domain_results: Dict[str, List[Dict[str, Any]]] = {}

    def record_task_result(
        self,
        task_id: str,
        success: bool,
        latency_ms: float,
        quality_score: float,
        domain: str = "general",
    ) -> None:
        """Record the result of a single task execution.

        Args:
            task_id: Unique task identifier (may repeat for retries).
            success: Whether the attempt succeeded.
            latency_ms: Execution latency in milliseconds.
            quality_score: Quality score in [0.0, 1.0].
            domain: Task domain, used for ID/OOD transfer computation.
        """
        record: Dict[str, Any] = {
            "task_id": task_id,
            "success": bool(success),
            "latency_ms": float(latency_ms),
            "quality_score": float(quality_score),
            "domain": domain,
            "timestamp": time.time(),
        }
        self._results.append(record)
        self._domain_results.setdefault(domain, []).append(record)

    def compute_pass_at_k(self, k: int = 1) -> float:
        """Compute the pass@k metric.

        For ``k == 1`` this is the fraction of recorded attempts that
        succeeded. For ``k > 1`` attempts are grouped by ``task_id`` and
        a task counts as passed if any of its last ``k`` attempts
        succeeded.

        Returns:
            Pass rate in [0.0, 1.0]. Returns 0.0 if no results recorded.
        """
        if k < 1:
            raise ValueError(f"k must be >= 1, got {k}")
        if not self._results:
            return 0.0
        if k == 1:
            successes = sum(1 for r in self._results if r["success"])
            return successes / len(self._results)
        # k > 1: group by task_id, check last k attempts.
        by_task: Dict[str, List[bool]] = {}
        for r in self._results:
            by_task.setdefault(r["task_id"], []).append(r["success"])
        if not by_task:
            return 0.0
        passed = sum(1 for succ in by_task.values() if any(succ[-k:]))
        return passed / len(by_task)

    def compute_transfer(
        self, source_domain: str, target_domain: str
    ) -> Dict[str, float]:
        """Compute ID / OOD transfer between two domains.

        Args:
            source_domain: In-distribution (ID) domain.
            target_domain: Out-of-distribution (OOD) domain.

        Returns:
            Dict with ``id_pass_rate``, ``ood_pass_rate``,
            ``transfer_ratio`` (ood / id, or 0.0 if id is 0),
            ``id_samples``, ``ood_samples``.
        """
        id_results = self._domain_results.get(source_domain, [])
        ood_results = self._domain_results.get(target_domain, [])

        id_pass = (
            sum(1 for r in id_results if r["success"]) / len(id_results)
            if id_results
            else 0.0
        )
        ood_pass = (
            sum(1 for r in ood_results if r["success"]) / len(ood_results)
            if ood_results
            else 0.0
        )
        transfer_ratio = ood_pass / id_pass if id_pass > 0 else 0.0

        return {
            "id_pass_rate": id_pass,
            "ood_pass_rate": ood_pass,
            "transfer_ratio": transfer_ratio,
            "id_samples": float(len(id_results)),
            "ood_samples": float(len(ood_results)),
        }

    def export_results(self, path: Optional[str] = None) -> Dict[str, Any]:
        """Persist results to a JSON file and return the exported dict.

        Args:
            path: Output path. Defaults to ``~/.laap/quality_metrics.json``.

        Returns:
            The exported results dict (also written to disk).
        """
        if path is None:
            path = os.path.expanduser("~/.laap/quality_metrics.json")
        path_dir = os.path.dirname(path)
        if path_dir:
            os.makedirs(path_dir, exist_ok=True)

        export: Dict[str, Any] = {
            "results": self._results,
            "domain_results": self._domain_results,
            "summary": {
                "total_tasks": len(self._results),
                "pass_at_1": self.compute_pass_at_k(1),
                "pass_at_5": self.compute_pass_at_k(5),
            },
            "exported_at": time.time(),
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(export, f, indent=2, ensure_ascii=False)
        return export

    def generate_trend_report(self) -> Dict[str, Any]:
        """Generate cumulative trend data suitable for charting.

        Returns:
            Dict with parallel lists: ``timestamps``, ``success_rate``,
            ``avg_latency_ms``, ``avg_quality_score``. Empty lists if
            no results have been recorded.
        """
        if not self._results:
            return {
                "timestamps": [],
                "success_rate": [],
                "avg_latency_ms": [],
                "avg_quality_score": [],
            }

        sorted_results = sorted(self._results, key=lambda r: r["timestamp"])
        timestamps: List[float] = []
        success_rates: List[float] = []
        avg_latencies: List[float] = []
        avg_qualities: List[float] = []

        successes = 0
        total_latency = 0.0
        total_quality = 0.0

        for i, r in enumerate(sorted_results, 1):
            if r["success"]:
                successes += 1
            total_latency += r["latency_ms"]
            total_quality += r["quality_score"]
            timestamps.append(r["timestamp"])
            success_rates.append(successes / i)
            avg_latencies.append(total_latency / i)
            avg_qualities.append(total_quality / i)

        return {
            "timestamps": timestamps,
            "success_rate": success_rates,
            "avg_latency_ms": avg_latencies,
            "avg_quality_score": avg_qualities,
        }
