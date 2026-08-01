"""HarnessX processors that read/write the LAAP cognitive loop."""

from __future__ import annotations

import dataclasses
import json
from typing import Any, AsyncIterator

from laap.integrations.harnessx.config import ensure_harnessx_importable

ensure_harnessx_importable()

from harnessx.core.events import TaskEndEvent, TaskStartEvent
from harnessx.core.processor import MultiHookProcessor

from laap.integrations.harnessx.constants import (
    HARNESS_EXECUTION_STIMULUS_TYPE,
    LAAP_PSI_CONTEXT_MARKER,
)


class PsiContextProcessor(MultiHookProcessor):
    """Inject LAAP PSI state into HarnessX prompts and feed results back to PSI.

    This processor runs early in the HarnessX pipeline (``_order = -100``) so
    that downstream context assemblers see the PSI context block. When the
    HarnessX task finishes, the outcome is posted as a perception to the LAAP
    PSI agent, allowing the cognitive loop to learn from harness execution.
    """

    _singleton_group = "laap_psi_context"
    _order = -100

    def __init__(self, cognitive_bus: Any | None = None) -> None:
        super().__init__()
        self.cognitive_bus = cognitive_bus

    async def on_task_start(
        self, event: TaskStartEvent
    ) -> AsyncIterator[TaskStartEvent]:
        psi_state = self._fetch_psi_state()
        if psi_state:
            context_block = self._render_psi_context(psi_state)
            new_prompt = (event.system_prompt or "") + context_block
            event = dataclasses.replace(event, system_prompt=new_prompt)
        yield event

    async def on_task_end(
        self, event: TaskEndEvent
    ) -> AsyncIterator[TaskEndEvent]:
        if self.cognitive_bus is not None:
            psi = getattr(self.cognitive_bus, "psi", None)
            if psi is not None:
                stimulus = self._build_execution_stimulus(event)
                await psi.process_perception(stimulus)
        yield event

    def _fetch_psi_state(self) -> dict[str, Any] | None:
        if self.cognitive_bus is None:
            return None
        psi = getattr(self.cognitive_bus, "psi", None)
        if psi is None:
            return None
        state = getattr(psi, "state", None)
        if state is None:
            return None
        if hasattr(state, "to_dict"):
            return state.to_dict()
        return dict(state)

    def _render_psi_context(self, psi_state: dict[str, Any]) -> str:
        return (
            f"\n\n{LAAP_PSI_CONTEXT_MARKER}\n"
            "You are operating inside the LAAP cognitive loop. "
            f"Current PSI state: {json.dumps(psi_state, ensure_ascii=False)}\n"
            "Adjust your reasoning to align with the dominant feeling and urges above.\n"
        )

    def _build_execution_stimulus(self, event: TaskEndEvent) -> dict[str, Any]:
        success = None
        if event.eval_result is not None:
            success = getattr(event.eval_result, "success", None)
        return {
            "type": HARNESS_EXECUTION_STIMULUS_TYPE,
            "exit_reason": event.exit_reason,
            "total_steps": event.total_steps,
            "total_tokens": event.total_tokens,
            "total_cost_usd": event.total_cost_usd,
            "success": success,
            "task_description": event.task_description,
        }
