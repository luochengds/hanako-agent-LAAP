"""Quantum cognition engine for LAAP digital lifeforms.

A unified cognitive architecture upgrade fusing five principles:
  - Schrodinger dynamics     → consciousness state evolution via unitary operators
  - Fourier transform       → spectral saliency analysis of stimulus stream
  - Bayesian optimization   → intention selection via Expected Free Energy
  - Kalman filter           → recursive self-model state estimation
  - Occam's razor           → meta-cognitive complexity regularization

Usage:
    from laap.agent_core.quantum_cognition import PsiQuantumCognition

    engine = PsiQuantumCognition(dim_state=8, mode='hybrid')
    goal, state = engine.decide(stimulus="user message")
    engine.learn(outcome="result", success=True)

Design principles:
  - All components are individually testable and replaceable.
  - Production-grade: full type hints, structured logging, thread safety,
    graceful degradation fallback chains.
  - Progressive adoption: configurable 'mode' flag selects pure quantum /
    hybrid / classic PSI backend at runtime.
"""

from .psi_quantum import (
    PsiQuantumCognition,
    QuantumCognitionConfig,
    QuantumMode,
)

from .kalman_self import KalmanSelfModel
from .spectral_saliency import SpectralSaliency
from .bayesian_selector import BayesianIntentionSelector
from .occam_meta import OccamMetaController
from .schrodinger import SchrodingerEvolver
from .hallucination_guard import HallucinationGuard, GuardConfig, PreGateDecision, ModulatedParams, ValidationResult
from .base import CognitiveKet, CognitiveOperator, CrankNicolson, BornRule

__all__ = [
    "PsiQuantumCognition",
    "QuantumCognitionConfig",
    "QuantumMode",
    "KalmanSelfModel",
    "SpectralSaliency",
    "BayesianIntentionSelector",
    "OccamMetaController",
    "SchrodingerEvolver",
    "HallucinationGuard",
    "GuardConfig",
    "PreGateDecision",
    "ModulatedParams",
    "ValidationResult",
    "CognitiveKet",
    "CognitiveOperator",
    "CrankNicolson",
    "BornRule",
]
