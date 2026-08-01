"""Convert HarnessX artifacts into formats consumed by LAAP evolution."""

from __future__ import annotations

from typing import Any

from laap.integrations.harnessx.config import ensure_harnessx_importable

ensure_harnessx_importable()

from harnessx.core.harness import HarnessResult


class TrajectoryAdapter:
    """Adapt a HarnessX ``HarnessResult`` into an Aris ``Trajectory`` dict.

    The output is directly ingestible by
    ``aris_brain.evolution.rsi_meta_engine.RSIMetaEngine.ingest_trajectories()``.
    """

    @staticmethod
    def to_aris_trajectory(
        result: HarnessResult,
        task_name: str = "harnessx_task",
    ) -> dict[str, Any]:
        """Return a trajectory dict matching ``RSIMetaEngine`` expectations."""
        task_end = result.task_end
        outcome = "success" if task_end.exit_reason == "done" else "failure"
        error = task_end.error if task_end.exit_reason == "error" else None

        return {
            "id": f"{task_end.run_id}_{task_end.step_id}",
            "task": task_name,
            "steps": TrajectoryAdapter._extract_steps(result),
            "outcome": outcome,
            "error": error,
            "duration": 0.0,
            "token_cost": task_end.total_cost_usd,
            "harness_snapshot": {
                "exit_reason": task_end.exit_reason,
                "total_steps": task_end.total_steps,
                "total_tokens": task_end.total_tokens,
                "total_cost_usd": task_end.total_cost_usd,
            },
        }

    @staticmethod
    def _extract_steps(result: HarnessResult) -> list[dict[str, Any]]:
        traj = result.trajectory
        if traj is None or not hasattr(traj, "steps"):
            return []

        steps: list[dict[str, Any]] = []
        for step in traj.steps:
            action = getattr(step, "action", None)
            observation = getattr(step, "observation", []) or []
            steps.append({
                "step_id": getattr(step, "step_id", 0),
                "action": getattr(action, "content", "") if action else "",
                "tool_calls": [
                    {"name": tc.name, "input": tc.input}
                    for tc in getattr(action, "tool_calls", ())
                ] if action else [],
                "observations": [
                    {
                        "tool_name": getattr(obs, "tool_name", "?"),
                        "result": getattr(obs, "result", "")[:500],
                        "error": getattr(obs, "error", None),
                    }
                    for obs in observation
                ],
                "reward": getattr(step, "reward", 0.0),
            })
        return steps
