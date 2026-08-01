"""SEAGym / Harbor integration adapter (M6 E3).

SEAGym (Self-Evolving Agent Gym) is an evaluation framework for agentic
systems, accessed via the Harbor orchestration service. This adapter
provides a stub interface for running LAAP agents against SEAGym
benchmarks including Terminal-Bench and HLE (Humanity's Last Exam).

Expected integration path
-------------------------
1. Deploy the Harbor service (default endpoint: ``http://localhost:8000``)
   which exposes the SEAGym task registry and evaluation harness.
2. Register the LAAP agent as a Harbor-compatible agent by posting
   ``agent_config`` to ``/agents``. The adapter would then receive an
   ``agent_id`` to reference in subsequent evaluation jobs.
3. Use :meth:`SEAGymAdapter.run_terminal_bench` or
   :meth:`SEAGymAdapter.run_hle` to create an evaluation job on Harbor.
   Each job runs ``num_tasks`` tasks sampled from the benchmark and
   returns ID (in-distribution) / OOD (out-of-distribution) / replay
   metrics.
4. Use :meth:`SEAGymAdapter.compare_with_baseline` to compare the
   agent's results against the published baselines (``ACE``,
   ``TF-GRPO``, ``AHE``) from the SEAGym paper.

Note
----
This is a **stub** implementation. The actual Harbor integration
requires the external Harbor service to be running and configured. All
methods return informative placeholder structures with clear ``TODO``
markers indicating where real HTTP calls and result aggregation should
be wired in.
"""

from __future__ import annotations

from typing import Any, Dict


# Published SEAGym-paper baseline numbers (placeholder values for the
# stub; replace with the canonical numbers from the SEAGym paper once
# integration is wired up).
_SEAGYM_BASELINES: Dict[str, Dict[str, float]] = {
    "ACE": {"id_pass_at_1": 0.32, "ood_pass_at_1": 0.18, "replay_pass_at_1": 0.25},
    "TF-GRPO": {"id_pass_at_1": 0.41, "ood_pass_at_1": 0.22, "replay_pass_at_1": 0.30},
    "AHE": {"id_pass_at_1": 0.55, "ood_pass_at_1": 0.31, "replay_pass_at_1": 0.38},
}


class SEAGymAdapter:
    """Stub adapter for SEAGym / Harbor evaluation integration.

    Parameters
    ----------
    harbor_endpoint:
        Base URL of the Harbor service. Default ``http://localhost:8000``.
    """

    def __init__(self, harbor_endpoint: str = "http://localhost:8000") -> None:
        self.harbor_endpoint = harbor_endpoint.rstrip("/")

    def run_terminal_bench(
        self, agent_config: Dict, num_tasks: int = 10
    ) -> Dict[str, Any]:
        """Run an agent on Terminal-Bench tasks (stub).

        Args:
            agent_config: Agent configuration dict (model, tools, prompts).
            num_tasks: Number of tasks to evaluate.

        Returns:
            Dict containing the ID / OOD / replay metrics structure.
            Real values are zeros until Harbor integration is wired up.
        """
        # TODO: implement actual Harbor integration
        # 1. POST agent_config to ``{harbor_endpoint}/agents`` → agent_id
        # 2. POST to ``{harbor_endpoint}/jobs`` with benchmark="terminal_bench"
        #    and num_tasks → job_id
        # 3. Poll ``{harbor_endpoint}/jobs/{job_id}`` until status=="done"
        # 4. Aggregate per-task outcomes into ID / OOD / replay buckets
        return {
            "benchmark": "terminal_bench",
            "harbor_endpoint": self.harbor_endpoint,
            "num_tasks": num_tasks,
            "agent_config": agent_config,
            "status": "stub",
            "metrics": {
                "id": {"pass_at_1": 0.0, "pass_at_5": 0.0, "num_tasks": num_tasks},
                "ood": {"pass_at_1": 0.0, "pass_at_5": 0.0, "num_tasks": num_tasks},
                "replay": {"pass_at_1": 0.0, "pass_at_5": 0.0, "num_tasks": num_tasks},
            },
            "todo": "Wire up POST /agents, POST /jobs, polling, aggregation.",
        }

    def run_hle(
        self, agent_config: Dict, num_tasks: int = 10
    ) -> Dict[str, Any]:
        """Run an agent on HLE (Humanity's Last Exam) tasks (stub).

        Args:
            agent_config: Agent configuration dict.
            num_tasks: Number of tasks to evaluate.

        Returns:
            Dict containing the HLE metrics structure.
        """
        # TODO: implement actual Harbor integration
        # Same flow as run_terminal_bench but with benchmark="hle".
        return {
            "benchmark": "hle",
            "harbor_endpoint": self.harbor_endpoint,
            "num_tasks": num_tasks,
            "agent_config": agent_config,
            "status": "stub",
            "metrics": {
                "id": {"pass_at_1": 0.0, "num_tasks": num_tasks},
                "ood": {"pass_at_1": 0.0, "num_tasks": num_tasks},
                "replay": {"pass_at_1": 0.0, "num_tasks": num_tasks},
            },
            "todo": "Wire up POST /agents, POST /jobs, polling, aggregation.",
        }

    def compare_with_baseline(
        self, results: Dict, baseline: str = "AHE"
    ) -> Dict[str, Any]:
        """Compare agent results against a SEAGym-paper baseline (stub).

        Args:
            results: Results dict returned by ``run_terminal_bench`` or
                ``run_hle``.
            baseline: Baseline name — one of ``"ACE"``, ``"TF-GRPO"``,
                ``"AHE"``. Default ``"AHE"``.

        Returns:
            Dict containing the baseline metrics, agent metrics, and a
            delta breakdown. ``status`` is ``"stub"`` until the real
            comparison logic is implemented.
        """
        # TODO: load canonical baseline numbers from the SEAGym paper and
        # compute per-metric deltas (agent − baseline) with significance
        # testing once sample sizes are available.
        baseline_metrics = _SEAGYM_BASELINES.get(baseline)
        if baseline_metrics is None:
            return {
                "status": "error",
                "error": f"Unknown baseline: {baseline!r}",
                "available_baselines": list(_SEAGYM_BASELINES.keys()),
            }

        agent_metrics = results.get("metrics", {})
        return {
            "status": "stub",
            "baseline": baseline,
            "baseline_metrics": baseline_metrics,
            "agent_metrics": agent_metrics,
            "deltas": {
                "id_pass_at_1": (
                    agent_metrics.get("id", {}).get("pass_at_1", 0.0)
                    - baseline_metrics["id_pass_at_1"]
                ),
                "ood_pass_at_1": (
                    agent_metrics.get("ood", {}).get("pass_at_1", 0.0)
                    - baseline_metrics["ood_pass_at_1"]
                ),
                "replay_pass_at_1": (
                    agent_metrics.get("replay", {}).get("pass_at_1", 0.0)
                    - baseline_metrics["replay_pass_at_1"]
                ),
            },
            "todo": (
                "Replace placeholder baseline numbers with canonical "
                "SEAGym-paper values; add significance testing."
            ),
        }
