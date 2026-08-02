"""Mandatory PSI turn boundary for canonical runtime interactions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterator, Optional
import hashlib
import json
import os
from pathlib import Path
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
    status: str = "started"
    cognitive_turn: Any = None


class PSITurnGateway:
    """Run every canonical Agent turn through a PSI before/after boundary.

    The gateway does not ask the LLM to role-play PSI.  It invokes the
    configured cognitive engine directly before and after the language I/O
    call.  A failed boundary raises instead of silently bypassing PSI.
    """

    def __init__(self, driver: Any, *, receipt_path: Optional[Path] = None):
        self.driver = driver
        self._turn_count = 0
        self.last_receipt: Optional[PSITurnReceipt] = None
        self.receipt_path = receipt_path or self._default_receipt_path()

    @staticmethod
    def _default_receipt_path() -> Path:
        configured = os.environ.get("LAAP_PSI_RECEIPT_PATH")
        if configured:
            return Path(configured).expanduser()
        try:
            from laap.config.paths import get_state_dir
            return get_state_dir() / "psi-turn-receipts.jsonl"
        except Exception:
            return Path.cwd() / ".laap" / "state" / "psi-turn-receipts.jsonl"

    @staticmethod
    def _digest(value: Any) -> str:
        return hashlib.sha256(str(value).encode("utf-8", errors="replace")).hexdigest()

    def _persist_receipt(self, receipt: PSITurnReceipt, output: Any = "") -> None:
        record = {
            "turn_id": receipt.turn_id,
            "input_sha256": self._digest(receipt.user_input),
            "output_sha256": self._digest(output) if receipt.output_seen else None,
            "context_keys": sorted(receipt.context.keys()),
            "output_seen": receipt.output_seen,
            "status": receipt.status,
            "started_at": receipt.started_at,
            "finished_at": receipt.finished_at,
        }
        try:
            receipt_path = Path(self.receipt_path)
            receipt_path.parent.mkdir(parents=True, exist_ok=True)
            with receipt_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            if os.environ.get("LAAP_PSI_RECEIPT_REQUIRED") == "1":
                raise

    @classmethod
    def default(cls) -> "PSITurnGateway":
        from .cognitive_runtime import AGIAgentCognitiveRuntime, BridgeCognitiveRuntime

        if os.environ.get("LAAP_COGNITIVE_RUNTIME", "bridge").lower() == "agi":
            return cls(AGIAgentCognitiveRuntime.create())

        from laap.agent.laap_bridge import get_bridge
        bridge = get_bridge()
        if not bridge.initialize():
            raise RuntimeError("PSI gateway initialization failed")
        return cls(BridgeCognitiveRuntime(bridge))

    def _before(self, user_input: str) -> PSITurnReceipt:
        self._turn_count += 1
        cognitive_turn = None
        if hasattr(self.driver, "begin_turn"):
            cognitive_turn = self.driver.begin_turn(user_input)
            context = getattr(cognitive_turn, "context", {})
        else:
            context = self.driver.before_turn(user_input)
        if not isinstance(context, dict):
            context = {"result": context}
        receipt = PSITurnReceipt(
            turn_id=self._turn_count,
            user_input=user_input,
            context=context,
            cognitive_turn=cognitive_turn,
        )
        self.last_receipt = receipt
        return receipt

    def _after(self, receipt: PSITurnReceipt, output: Any) -> Any:
        receipt.output_seen = True
        receipt.finished_at = time.time()
        receipt.status = "completed"
        if hasattr(self.driver, "complete_turn"):
            self.driver.complete_turn(receipt.cognitive_turn, str(output))
        else:
            self.driver.after_turn(str(output))
        self._persist_receipt(receipt, output)
        return output

    def invoke(self, user_input: str, operation: Callable[[], Any]) -> Any:
        receipt = self._before(user_input)
        try:
            output = operation()
        except Exception:
            # The input crossed PSI, but no output was produced. Preserve the
            # receipt and re-raise the original backend error.
            receipt.finished_at = time.time()
            receipt.status = "backend_error"
            self._persist_receipt(receipt)
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
            receipt.status = "backend_error"
            self._persist_receipt(receipt)
            raise
        else:
            output = "".join(str(item) for item in chunks)
            receipt.output_seen = True
            receipt.finished_at = time.time()
            receipt.status = "completed"
            if hasattr(self.driver, "complete_turn"):
                self.driver.complete_turn(receipt.cognitive_turn, output)
            else:
                self.driver.after_turn(output)
            self._persist_receipt(receipt, output)


__all__ = ["PSITurnGateway", "PSITurnReceipt"]
