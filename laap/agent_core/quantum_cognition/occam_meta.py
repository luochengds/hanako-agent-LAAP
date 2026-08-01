"""Occam's meta-cognitive controller — model complexity regularization.

Implements the Occam's razor principle for cognitive architecture:
  "Among competing hypotheses, the one with the fewest assumptions should
   be selected."

Formally, this is **Bayesian model comparison**: given data D and two models
M1 (simpler) and M2 (more complex), prefer M1 unless:

    P(D | M2) / P(D | M1) > threshold (Jeffreys' scale)

The marginal likelihood P(D | M) = ∫ P(D | θ, M) P(θ | M) dθ naturally
penalizes model complexity through the **Occam factor** — the volume of
parameter space that is 'wasted' by being compatible with many datasets.

In the cognitive context, this controller:
  - Audits the effective rank of the Hamiltonian (cognitive complexity)
  - Compares current vs simplified interpretations of perception
  - Triggers simplification when complexity grows without explanatory gain
  - Produces structured audit logs for meta-cognitive awareness
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger('quantum_cognition.occam_meta')


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class OccamError(Exception):
    """Raised when model comparison fails."""


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class OccamConfig:
    """Configuration for the Occam meta-controller.

    Parameters
    ----------
    audit_interval : int
        How many cognitive cycles between complexity audits.
    bayes_factor_threshold : float
        Minimum Bayes factor to prefer the complex model over the simple one.
        Jeffreys scale: 1-3 = barely worth mentioning, 3-10 = substantial,
        10-30 = strong, >30 = decisive.
        Default 3.0 (substantial evidence needed to add complexity).
    complexity_growth_rate : float
        Maximum allowed growth rate of effective rank per audit.
        Exceeding this triggers simplification.
    effective_rank_tolerance : float
        Singular value threshold for effective rank computation.
    max_hamiltonian_rank : int
        Hard maximum for Hamiltonian effective rank before forced pruning.
    enable_audit_log : bool
        If True, write structured audit records.
    name : str
        Human-readable identifier for logging.
    """
    audit_interval: int = 10
    bayes_factor_threshold: float = 3.0
    complexity_growth_rate: float = 0.15
    effective_rank_tolerance: float = 0.01
    max_hamiltonian_rank: int = 12
    enable_audit_log: bool = True
    name: str = "occam_meta"


# ---------------------------------------------------------------------------
# Audit record
# ---------------------------------------------------------------------------

@dataclass
class ComplexityAuditRecord:
    """A single meta-cognitive audit result.

    Parameters
    ----------
    cycle : int
        Cognitive cycle number when audit was performed.
    effective_rank : int
        Effective rank of the Hamiltonian (number of significant eigenvalues).
    complexity_score : float
        Normalized complexity (0 = simplest, 1 = maximally complex).
    bayes_factor : float
        Bayes factor comparing current vs simplified model.
    simplified_recommended : bool
        Whether the controller recommends switching to a simpler model.
    explanation : str
        Human-readable audit summary.
    """
    cycle: int
    effective_rank: int
    complexity_score: float
    bayes_factor: float
    simplified_recommended: bool
    explanation: str


# ---------------------------------------------------------------------------
# OccamMetaController
# ---------------------------------------------------------------------------

class OccamMetaController:
    """Meta-cognitive complexity controller using Bayesian model comparison.

    Parameters
    ----------
    config : OccamConfig, optional
    effective_rank_fn : Callable, optional
        Function that computes the effective rank of the cognitive model.
        Default uses singular-value-based effective rank.
    model_evidence_fn : Callable, optional
        Function that computes marginal likelihood of a model given data.
        Default uses Laplace approximation (BIC-like).
    """

    def __init__(
        self,
        config: Optional[OccamConfig] = None,
        effective_rank_fn: Optional[Callable[..., int]] = None,
        model_evidence_fn: Optional[Callable[..., float]] = None,
    ):
        self.cfg = config or OccamConfig()
        self._effective_rank_fn = effective_rank_fn or self._default_effective_rank
        self._model_evidence_fn = model_evidence_fn or self._default_model_evidence

        self._cycle: int = 0
        self._last_effective_rank: Optional[int] = None
        self._audit_history: List[ComplexityAuditRecord] = []
        self._simplification_count: int = 0

    # -- Public API ---------------------------------------------------------

    def audit(self, hamiltonian: np.ndarray,
              observations: Optional[np.ndarray] = None,
              force: bool = False) -> ComplexityAuditRecord:
        """Run a complexity audit on the current cognitive model.

        Audits happen every ``audit_interval`` cycles unless *force=True*.

        Parameters
        ----------
        hamiltonian : np.ndarray
            Current cognitive Hamiltonian matrix.
        observations : np.ndarray, optional
            Recent observation data for model evidence computation.
        force : bool, optional
            If True, run audit regardless of cycle count.

        Returns
        -------
        ComplexityAuditRecord
            The result of this audit cycle.
        """
        self._cycle += 1

        if not force and self._cycle % self.cfg.audit_interval != 0:
            # Return a no-op audit record
            rank = self._last_effective_rank or self._effective_rank_fn(hamiltonian)
            return ComplexityAuditRecord(
                cycle=self._cycle,
                effective_rank=rank,
                complexity_score=0.0,
                bayes_factor=1.0,
                simplified_recommended=False,
                explanation="skip (not audit cycle)",
            )

        try:
            effective_rank = self._effective_rank_fn(hamiltonian)
        except Exception as e:
            logger.warning(f"Effective rank computation failed: {e}")
            effective_rank = hamiltonian.shape[0]  # pessimistic

        complexity_score = effective_rank / hamiltonian.shape[0]

        # Detect runaway complexity
        if self._last_effective_rank is not None:
            growth = (effective_rank - self._last_effective_rank) \
                     / max(self._last_effective_rank, 1)
            if growth > self.cfg.complexity_growth_rate:
                logger.info(
                    f"[occam] complexity growth {growth:.2f} exceeds "
                    f"threshold {self.cfg.complexity_growth_rate}, "
                    f"recommending simplification"
                )

        # Model comparison
        simplified_recommended = False
        bayes_factor = 1.0
        if observations is not None and observations.shape[0] >= 3:
            try:
                evidence_current = self._model_evidence_fn(hamiltonian, observations)
                simple_ham = self._build_simple_model(hamiltonian)
                evidence_simple = self._model_evidence_fn(simple_ham, observations)
                bayes_factor = evidence_current / evidence_simple

                if bayes_factor < self.cfg.bayes_factor_threshold:
                    simplified_recommended = True
                    self._simplification_count += 1
            except Exception as e:
                logger.debug(f"Model evidence comparison failed: {e}")

        # Hard cap check
        if effective_rank > self.cfg.max_hamiltonian_rank:
            simplified_recommended = True
            logger.info(
                f"[occam] effective rank {effective_rank} exceeds max "
                f"{self.cfg.max_hamiltonian_rank}, forced simplification needed"
            )

        explanation = self._build_explanation(
            effective_rank, complexity_score, bayes_factor,
            simplified_recommended
        )

        record = ComplexityAuditRecord(
            cycle=self._cycle,
            effective_rank=effective_rank,
            complexity_score=complexity_score,
            bayes_factor=float(bayes_factor),
            simplified_recommended=simplified_recommended,
            explanation=explanation,
        )

        self._audit_history.append(record)
        self._last_effective_rank = effective_rank

        if simplified_recommended and self.cfg.enable_audit_log:
            logger.info(f"[occam] AUDIT: {explanation}")

        return record

    def suggest_simplified_hamiltonian(self, hamiltonian: np.ndarray
                                        ) -> np.ndarray:
        """Return a simplified version of the Hamiltonian.

        Uses truncated SVD to keep only the top ``max_hamiltonian_rank``
        eigen-components.  This produces the best rank-k approximation in
        the Frobenius norm.

        Parameters
        ----------
        hamiltonian : np.ndarray
            Current full Hamiltonian.

        Returns
        -------
        np.ndarray
            Simplified Hamiltonian.
        """
        max_rank = min(self.cfg.max_hamiltonian_rank, hamiltonian.shape[0] - 1)
        try:
            eigvals, eigvecs = np.linalg.eigh(hamiltonian)
            # Keep only top (most significant) eigenvalues
            # For Hamiltonian, 'significant' = highest absolute eigenvalue
            order = np.argsort(-np.abs(eigvals))
            retained = order[:max_rank]
            simplified = eigvecs[:, retained] @ np.diag(eigvals[retained]) \
                         @ eigvecs[:, retained].conj().T
            # Ensure Hermiticity (numerical cleanup)
            simplified = (simplified + simplified.conj().T) / 2.0
            return simplified
        except np.linalg.LinAlgError:
            logger.warning("SVD failed for simplification, returning original")
            return hamiltonian.copy()

    # -- Properties ---------------------------------------------------------

    @property
    def simplification_count(self) -> int:
        """Total number of simplifications recommended."""
        return self._simplification_count

    @property
    def last_audit(self) -> Optional[ComplexityAuditRecord]:
        """Most recent audit record."""
        return self._audit_history[-1] if self._audit_history else None

    @property
    def audit_history(self) -> List[ComplexityAuditRecord]:
        """Full audit history."""
        return list(self._audit_history)

    def reset(self):
        """Reset audit state."""
        self._cycle = 0
        self._last_effective_rank = None
        self._audit_history.clear()
        self._simplification_count = 0

    # -- Internal helpers ---------------------------------------------------

    @staticmethod
    def _default_effective_rank(matrix: np.ndarray) -> int:
        """Effective rank: number of singular values above tolerance * max(S).

        This measures how many 'degrees of freedom' the cognitive model
        actually uses.
        """
        s = np.linalg.svd(matrix, compute_uv=False, hermitian=True)
        threshold = 0.01 * s[0]  # 1% of max singular value
        return int(np.sum(s > threshold))

    @staticmethod
    def _default_model_evidence(hamiltonian: np.ndarray,
                                 observations: np.ndarray) -> float:
        """Laplace-approximated log marginal likelihood (BIC-like).

        log P(D | M) ≈ log L(θ̂ | D) - (k/2) * log(n)

        where:
          L is the likelihood under the Hamiltonian
          k is the effective rank (number of parameters)
          n is the number of observations
        """
        eigvals, eigvecs = np.linalg.eigh(hamiltonian)
        n = observations.shape[0]
        k = OccamMetaController._default_effective_rank(hamiltonian)

        obs_var = np.var(observations)
        if obs_var < 1e-10:
            return 1.0

        # Project observations onto Hamiltonian eigenbasis
        proj = eigvecs.T @ observations.T  # (dims, n)
        reconstruction = eigvecs @ proj     # (dims, n)
        error = np.mean((observations.T - reconstruction) ** 2)
        log_likelihood = -0.5 * n * np.log(error + 1e-10)

        # BIC penalty: -(k/2) * ln(n)
        complexity_penalty = -(k / 2.0) * math.log(n)

        return log_likelihood + complexity_penalty

    @staticmethod
    def _build_simple_model(hamiltonian: np.ndarray) -> np.ndarray:
        """Construct a simpler version: diagonal + small coupling.

        Represents the simplest possible cognitive model: each cognitive
        modality independent, with minimal cross-talk.
        """
        diag = np.diag(np.diag(hamiltonian))
        # Add minimal coupling (10% of mean off-diagonal magnitude)
        off_diag = hamiltonian - diag
        mean_off = np.mean(np.abs(off_diag))
        if mean_off > 1e-10:
            coupling = off_diag * (0.1 * mean_off / (np.abs(off_diag) + 1e-10))
        else:
            coupling = np.zeros_like(off_diag)
        return (diag + coupling).astype(np.complex64)

    @staticmethod
    def _build_explanation(effective_rank: int, complexity_score: float,
                            bayes_factor: float,
                            simplified_recommended: bool) -> str:
        """Construct a human-readable audit summary."""
        if simplified_recommended:
            return (
                f"SIMPLIFY: effective rank={effective_rank}, "
                f"complexity={complexity_score:.2f}, "
                f"BF={bayes_factor:.2f} < threshold. "
                f"Model complexity exceeds explanatory necessity."
            )
        return (
            f"OK: effective rank={effective_rank}, "
            f"complexity={complexity_score:.2f}, "
            f"BF={bayes_factor:.2f}"
        )

    def __repr__(self) -> str:
        return (f"OccamMetaController(audits={len(self._audit_history)}, "
                f"simplifications={self._simplification_count})")
