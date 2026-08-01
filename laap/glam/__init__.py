"""Gated Long-Attention Memory (GLAM) — classical sigmoid probabilistic gating, no quantum hardware.

GLAM is the honest classical renaming of the former QLAM package.
All operations are classical sigmoid probabilistic gating — no quantum hardware.

# 历史名称 qlam 包已重命名为 glam（经典概率实现，非量子）
"""

from laap.glam.core import GLAMConfig, GLAMCell
from laap.glam.measurement import QueryDependentMeasurement
from laap.glam.pqc import ParameterizedProbabilisticCircuit
from laap.glam.quantum_state import AmplitudeEncoding, ProbabilisticStateEncoder

__all__ = [
    "GLAMConfig",
    "GLAMCell",
    "QueryDependentMeasurement",
    "ParameterizedProbabilisticCircuit",
    "AmplitudeEncoding",
    "ProbabilisticStateEncoder",
]
