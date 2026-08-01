"""CreditsTracker — 信用追踪"""
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

@dataclass
class UsageRecord:
    timestamp: float = 0.0; model: str = ""
    input_tokens: int = 0; output_tokens: int = 0; cost: float = 0.0

class CreditsTracker:
    def __init__(self, budget: float = 10.0):
        self.budget = budget
        self._records: List[UsageRecord] = []
    def record(self, model: str, input_tokens: int, output_tokens: int, cost: float):
        self._records.append(UsageRecord(time.time(), model, input_tokens, output_tokens, cost))
    def total_cost(self) -> float:
        return sum(r.cost for r in self._records)
    def remaining(self) -> float:
        return self.budget - self.total_cost()
    def exceeded(self) -> bool:
        return self.total_cost() >= self.budget
    def get_stats(self) -> dict:
        return {"budget": self.budget, "spent": round(self.total_cost(), 4), "remaining": round(self.remaining(), 4)}
