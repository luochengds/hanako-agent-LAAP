"""TurnFinalizer — 轮次终结"""
import time, logging
logger = logging.getLogger("agent_core.turn_finalizer")
class TurnFinalizer:
    def __init__(self):
        self._turns: List[dict] = []
    def finalize(self, turn: dict) -> dict:
        turn["ended_at"] = time.time()
        turn["duration_ms"] = round((turn["ended_at"] - turn.get("started_at", turn["ended_at"])) * 1000, 2)
        self._turns.append(turn)
        return turn
    def get_stats(self):
        return {"total": len(self._turns)}
