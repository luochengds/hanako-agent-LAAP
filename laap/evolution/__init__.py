"""LAAP - Evolution: RSI, Symbolic, Sandbox, Mutation, AEvo

注意：laap/evolution/rsi.py 中的 RSIEngine 已 DEPRECATED（实际为参数调优循环，
非 True RSI）。True RSI 实现见 M4 阶段 laap/evolution/true_rsi.py。
保留导出仅为 import 兼容，调用方应迁移至 laap/agi/rsi_engine.py。
"""
import warnings as _warnings

from laap.evolution.rsi import RSIEngine, ImprovementProposal
from laap.evolution.symbolic import SymbolicRecursionLayer
from laap.evolution.sandbox import Sandbox
from laap.evolution.mutation import MutationStrategy
from laap.evolution.aevo import (
    CandidateRecord, CandidateHistory,
    ProtectedEvaluator,
    MetaEditor, EditPlan, EditTarget,
    EvolutionHarness, RunPlan,
)

# 触发 DeprecationWarning（仅当实际访问 RSIEngine 时）
_warnings.warn(
    "laap.evolution.rsi.RSIEngine is deprecated (parameter-tuning, not True RSI). "
    "Use laap.agi.rsi_engine for parameter optimization, or wait for M4 True RSI.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    "RSIEngine", "ImprovementProposal", "SymbolicRecursionLayer",
    "Sandbox", "MutationStrategy",
    "CandidateRecord", "CandidateHistory", "ProtectedEvaluator",
    "MetaEditor", "EditPlan", "EditTarget", "EvolutionHarness", "RunPlan",
]
