"""
LAAP-MEM Memory Curve Protocol — Ebbinghaus forgetting curve
"""
from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class MemoryCurvePoint:
    t_hours: float = 0.0
    recall_probability: float = 1.0
    strength: float = 1.0


@dataclass
class MemoryCurve:
    initial_strength: float = 1.0
    decay_factor: float = 0.5
    stability: float = 1.0
    repetitions: int = 0
    points: List[MemoryCurvePoint] = field(default_factory=list)
    
    def retention_at(self, t_hours: float) -> float:
        return math.exp(-self.decay_factor * t_hours / self.stability)
    
    def recall_probability(self, t_hours: float) -> float:
        s = self.initial_strength * math.exp(self.repetitions * 0.3)
        d = max(0.1, self.decay_factor - self.initial_strength * 0.2)
        return math.exp(-d * t_hours / s)
    
    def after_review(self, t_hours: float, quality: int = 1) -> "MemoryCurve":
        before = self.retention_at(t_hours)
        current_strength = before * self.initial_strength
        new_strength = current_strength + (self.initial_strength * (1 + 0.5 ** self.repetitions))
        return MemoryCurve(
            initial_strength=new_strength,
            decay_factor=self.decay_factor,
            stability=self.stability * 1.2,
            repetitions=self.repetitions + 1,
        )
    
    def optimal_review(self, threshold: float = 0.7) -> float:
        if self.recall_probability(0) <= threshold:
            return 0.0
        t = 0.0
        step = 0.1
        for _ in range(10000):
            if self.recall_probability(t) < threshold:
                return round(t, 2)
            t += step
        return round(t, 2)
    
    def generate_curve(self, max_hours: float = 168.0, steps: int = 50) -> List[MemoryCurvePoint]:
        points = []
        for i in range(steps):
            t = max_hours * i / (steps - 1)
            rp = self.recall_probability(t)
            s = self.initial_strength * math.exp(-self.decay_factor * t / self.stability)
            points.append(MemoryCurvePoint(t_hours=t, recall_probability=rp, strength=s))
        self.points = points
        return points
    
    def to_dict(self) -> dict:
        return {
            "initial_strength": self.initial_strength,
            "decay_factor": self.decay_factor,
            "stability": self.stability,
            "repetitions": self.repetitions,
            "points": [{"t_hours": p.t_hours, "recall_probability": p.recall_probability, "strength": p.strength} for p in self.points],
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "MemoryCurve":
        curve = cls(
            initial_strength=data.get("initial_strength", 1.0),
            decay_factor=data.get("decay_factor", 0.5),
            stability=data.get("stability", 1.0),
            repetitions=data.get("repetitions", 0),
        )
        curve.points = [MemoryCurvePoint(**p) for p in data.get("points", [])]
        return curve
