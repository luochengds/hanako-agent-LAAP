"""LAAP ExecutionLayer runtime backed by HarnessX."""

from __future__ import annotations

from typing import Any

from laap.integrations.harnessx.config import ensure_harnessx_importable

ensure_harnessx_importable()

from harnessx.core.harness import BaseTask, HarnessConfig
from harnessx.core.model_config import ModelConfig


class HarnessXRuntime:
    """Thin wrapper that lets LAAP run tasks through a HarnessX agent.

    Example::

        from harnessx.core.model_config import ModelConfig
        from harnessx.providers.litellm_provider import LiteLLMProvider
        from laap.integrations.harnessx import HarnessXRuntime

        model = ModelConfig(main=LiteLLMProvider("openai/gpt-4o"))
        rt = HarnessXRuntime(model_config=model)
        result = await rt.run_task("Summarize the project README")
    """

    def __init__(
        self,
        model_config: ModelConfig | None = None,
        harness_config: HarnessConfig | None = None,
    ) -> None:
        self.model_config = model_config
        self.harness_config = harness_config or HarnessConfig()

    async def run_task(
        self,
        description: str,
        success_criteria: str = "",
        max_steps: int = 20,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Run a single HarnessX task and return a normalized result dict.

        Args:
            description: The task description passed to ``BaseTask``.
            success_criteria: Optional success criteria string.
            max_steps: Maximum number of steps (default 20).
            **kwargs: Extra fields forwarded to ``BaseTask``.

        Returns:
            A dict with ``task_end``, ``trajectory``, ``final_output``,
            and ``exit_reason``.
        """
        if self.model_config is None:
            raise RuntimeError(
                "HarnessXRuntime requires a ModelConfig. "
                "Pass one to the constructor or call set_model_config()."
            )

        agent = self.model_config.agentic(self.harness_config)
        task = BaseTask(
            description=description,
            success_criteria=success_criteria,
            max_steps=max_steps,
            **kwargs,
        )
        result = await agent.run(task)
        return {
            "task_end": result.task_end,
            "trajectory": result.trajectory,
            "final_output": result.task_end.final_output,
            "exit_reason": result.task_end.exit_reason,
        }

    def set_model_config(self, model_config: ModelConfig) -> None:
        """Allow late binding of the model config."""
        self.model_config = model_config
