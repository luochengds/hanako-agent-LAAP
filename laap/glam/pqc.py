"""
Gated Long-Attention Memory (GLAM) — classical sigmoid probabilistic gating, no quantum hardware
================================================================================================

Parameterized Probabilistic Circuit (PPC).
Simulated PPC for classical probabilistic state evolution.

# 历史名称 ParameterizedQuantumCircuit 已重命名为 ParameterizedProbabilisticCircuit（经典概率实现，非量子）
"""

from __future__ import annotations
import math
from typing import List, Optional


class ParameterizedProbabilisticCircuit:
    def __init__(self, num_qubits: int = 6, num_layers: int = 2):
        self.num_qubits = num_qubits
        self.num_layers = num_layers
        self.dim = 1 << num_qubits
        self.params = [0.0] * (num_qubits * num_layers * 3)

    def set_parameters(self, params: List[float]):
        n = self.num_qubits * self.num_layers * 3
        self.params = list(params[:n]) if len(params) >= n else params + [0.0] * (n - len(params))

    def evolve(self, state: List[float], theta: Optional[List[float]] = None) -> List[float]:
        if theta is not None:
            self.set_parameters(theta)
        if not state:
            return state
        n = min(len(state), self.dim)
        evolved = []
        for i in range(n):
            angle = sum(self.params[j % len(self.params)] for j in range(i, i + 3))
            evolved.append(state[i] * math.cos(angle))
        remainder = len(state) - n
        if remainder > 0:
            evolved.extend(state[n:])
        norm = math.sqrt(sum(x * x for x in evolved)) or 1.0
        return [x / norm for x in evolved]

    def __repr__(self):
        return f"PPC(qubits={self.num_qubits}, layers={self.num_layers})"
