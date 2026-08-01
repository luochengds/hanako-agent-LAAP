"""Insights — 洞察引擎"""
from typing import Any, Dict, List, Optional
from collections import Counter

class InsightsEngine:
    def __init__(self):
        self._interactions: List[Dict] = []
    def record(self, user_msg: str, agent_msg: str, duration_ms: float):
        self._interactions.append({"user": user_msg, "agent": agent_msg, "duration": duration_ms})
    def get_topics(self) -> List[str]:
        words = []
        for i in self._interactions:
            words.extend(i["user"].split())
        return [w for w, _ in Counter(words).most_common(10) if len(w) > 2]
    def avg_response_time(self) -> float:
        if not self._interactions: return 0
        return sum(i["duration"] for i in self._interactions) / len(self._interactions)
    def total_interactions(self) -> int:
        return len(self._interactions)
