"""Mandatory PSI turn boundary for canonical runtime interactions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterator, Optional
import time


@dataclass
class PSITurnReceipt:
    """Auditable record that a turn crossed both PSI boundaries."""

    turn_id: int
    user_input: str
    context: Dict[str, Any] = field(default_factory=dict)
    output_seen: bool = False
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None


class PSITurnGateway:
    """Run every canonical Agent turn through a PSI before/after boundary.

    The gateway does not ask the LLM to role-play PSI.  It invokes the
    configured cognitive engine directly before and after the language I/O
    call.  A failed boundary raises instead of silently bypassing PSI.
    """

    def __init__(self, driver: Any):
        self.driver = driver
        self._turn_count = 0
        self.last_receipt: Optional[PSITurnReceipt] = None

    @classmethod
    def default(cls) -> "PSITurnGateway":
        from laap.agent.laap_bridge import get_bridge

        driver = get_bridge()
        if not driver.initialize():
            raise RuntimeError("PSI gateway initialization failed")
        return cls(driver)

    def _before(self, user_input: str) -> PSITurnReceipt:
        self._turn_count += 1
        context = self.driver.before_turn(user_input)
        if not isinstance(context, dict):
            context = {"result": context}
        receipt = PSITurnReceipt(
            turn_id=self._turn_count,
            user_input=user_input,
            context=context,
        )
        self.last_receipt = receipt
        return receipt

    def _after(self, receipt: PSITurnReceipt, output: Any) -> Any:
        receipt.output_seen = True
        receipt.finished_at = time.time()
        self.driver.after_turn(str(output))
        return output

    def invoke(self, user_input: str, operation: Callable[[], Any]) -> Any:
        receipt = self._before(user_input)
        try:
            output = operation()
        except Exception:
            # The input crossed PSI, but no output was produced. Preserve the
            # receipt and re-raise the original backend error.
            receipt.finished_at = time.time()
            raise
        return self._after(receipt, output)

    def stream(self, user_input: str, operation: Callable[[], Iterator[Any]]) -> Iterator[Any]:
        receipt = self._before(user_input)
        chunks = []
        try:
            for item in operation():
                chunks.append(item)
                yield item
        except Exception:
            receipt.finished_at = time.time()
            raise
        else:
            receipt.output_seen = True
            receipt.finished_at = time.time()
            self.driver.after_turn("".join(str(item) for item in chunks))


__all__ = ["PSITurnGateway", "PSITurnReceipt"]
