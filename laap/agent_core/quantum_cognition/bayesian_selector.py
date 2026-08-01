"""Bayesian intention selector — GP-based EFE acquisition for action selection.

Replaces the linear ``priority * 0.6 + urgency * 0.4`` ranking in
``psi_cognition.py``.

Core idea:
  - Each candidate intention is a point in a latent state space.
  - A Gaussian Process (GP) models the mapping from intention features to
    expected utility, with uncertainty quantification.
  - The **Expected Free Energy (EFE)** acquisition function selects the
    intention with the best exploration-exploitation trade-off:

      EFE = pragmatic_value (goal-seeking) + curiosity * epistemic_value (info-seeking)

    where epistemic_value is the posterior standard deviation from the GP.
  - After execution, the observed outcome updates the GP, and the curiosity
    coefficient adapts based on recent regret.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger('quantum_cognition.bayesian_selector')


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class BayesianSelectionError(Exception):
    """Raised when GP inference or acquisition fails."""


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class BayesianSelectorConfig:
    """Configuration for the Bayesian intention selector.

    Parameters
    ----------
    feature_dim : int
        Dimensionality of the intention feature space.
    max_intentions : int
        Maximum number of tracked intentions in the GP training set.
    curiosity_initial : float
        Initial curiosity coefficient (exploration weight).
    curiosity_min : float
        Minimum curiosity (always maintains some exploration).
    curiosity_max : float
        Maximum curiosity (never over-explores).
    curiosity_decay : float
        Decay factor when regret is low (success ratio high).
    curiosity_boost : float
        Boost factor when regret is high (stuck in rut).
    kernel_length_scale : float
        RBF kernel length scale.
    kernel_variance : float
        RBF kernel output variance.
    noise_variance : float
        Observation noise variance for GP.
    regret_window : int
        Number of recent outcomes to track for adaptive curiosity.
    name : str
        Human-readable identifier for logging.
    """
    feature_dim: int = 6
    max_intentions: int = 100
    curiosity_initial: float = 1.0
    curiosity_min: float = 0.2
    curiosity_max: float = 3.0
    curiosity_decay: float = 0.97
    curiosity_boost: float = 1.15
    kernel_length_scale: float = 0.5
    kernel_variance: float = 1.0
    noise_variance: float = 0.01
    regret_window: int = 20
    name: str = "bayesian_selector"


# ---------------------------------------------------------------------------
# Intention
# ---------------------------------------------------------------------------

@dataclass
class Intention:
    """A single cognitive intention with GP-derived scores.

    Parameters
    ----------
    id : str
        Unique identifier.
    goal : str
        Short description of the intention.
    features : np.ndarray
        Feature vector in GP input space.
    priority : float
        Heuristic priority (for hybrid fallback).
    urgency : float
        Heuristic urgency (for hybrid fallback).
    """
    id: str
    goal: str
    features: np.ndarray
    priority: float = 0.5
    urgency: float = 0.0
    selected: bool = False
    efe_score: float = 0.0
    pragmatic_value: float = 0.0
    epistemic_value: float = 0.0

    def __post_init__(self):
        self.features = np.asarray(self.features, dtype=np.float32)

    def __repr__(self) -> str:
        return (f"Intention({self.goal[:20]}, "
                f"efe={self.efe_score:.3f}, "
                f"selected={self.selected})")


# ---------------------------------------------------------------------------
# Gaussian Process (exact, small-n)
# ---------------------------------------------------------------------------

class _ExactGP:
    """Exact GP regression for small training sets (n <= 100).

    Uses RBF kernel with automatic relevance determination stub.

    Parameters
    ----------
    length_scale : float
    variance : float
    noise_var : float
    """

    def __init__(self, length_scale: float = 0.5, variance: float = 1.0,
                 noise_var: float = 0.01):
        self._ls = length_scale
        self._var = variance
        self._noise = noise_var
        self._X: Optional[np.ndarray] = None
        self._y: Optional[np.ndarray] = None
        self._L: Optional[np.ndarray] = None   # Cholesky factor
        self._alpha: Optional[np.ndarray] = None  # K^{-1} y
        self._n: int = 0

    def fit(self, X: np.ndarray, y: np.ndarray):
        """Fit the GP by computing Cholesky decomposition.

        Parameters
        ----------
        X : np.ndarray, shape (n, d)
            Training inputs.
        y : np.ndarray, shape (n,)
            Training targets.
        """
        n = X.shape[0]
        K = self._rbf_kernel(X, X) + np.eye(n) * self._noise
        try:
            self._L = np.linalg.cholesky(K)
            self._alpha = np.linalg.solve(self._L.T,
                                          np.linalg.solve(self._L, y))
        except np.linalg.LinAlgError as e:
            raise BayesianSelectionError(
                f"Cholesky failed (n={n}), try increasing noise_variance"
            ) from e
        self._X = X.copy()
        self._y = y.copy()
        self._n = n

    def predict(self, X_new: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """Predict mean and standard deviation at test points.

        Parameters
        ----------
        X_new : np.ndarray, shape (m, d)

        Returns
        -------
        (mu, sigma) : (np.ndarray, np.ndarray)
            Predictive mean and standard deviation, each shape (m,).
        """
        if self._X is None or self._n == 0:
            return np.zeros(X_new.shape[0]), np.ones(X_new.shape[0]) * self._var

        K_s = self._rbf_kernel(X_new, self._X)
        mu = K_s @ self._alpha

        v = np.linalg.solve(self._L, K_s.T)
        K_ss = self._rbf_kernel(X_new, X_new)
        var = np.diag(K_ss) - np.sum(v ** 2, axis=0)
        var = np.maximum(var, 1e-10)  # numerical safety
        sigma = np.sqrt(var)

        return mu.flatten(), sigma.flatten()

    def _rbf_kernel(self, A: np.ndarray, B: np.ndarray) -> np.ndarray:
        """RBF kernel matrix K(A, B)."""
        dist_sq = np.sum(A ** 2, axis=1, keepdims=True) \
                  + np.sum(B ** 2, axis=1) \
                  - 2.0 * A @ B.T
        return self._var * np.exp(-0.5 * dist_sq / self._ls ** 2)


# ---------------------------------------------------------------------------
# BayesianIntentionSelector
# ---------------------------------------------------------------------------

class BayesianIntentionSelector:
    """GP-based intention selection via Expected Free Energy.

    Parameters
    ----------
    config : BayesianSelectorConfig, optional
    feature_extractor : Callable, optional
        Function that maps an Intention to its feature vector.
        Default uses ``intention.features`` directly.
    """

    def __init__(
        self,
        config: Optional[BayesianSelectorConfig] = None,
        feature_extractor: Optional[Callable[[Intention], np.ndarray]] = None,
    ):
        self.cfg = config or BayesianSelectorConfig()
        self._gp = _ExactGP(
            length_scale=self.cfg.kernel_length_scale,
            variance=self.cfg.kernel_variance,
            noise_var=self.cfg.noise_variance,
        )
        self._feature_extractor = feature_extractor or (lambda i: i.features)

        self._curiosity = self.cfg.curiosity_initial
        self._outcomes: List[float] = []
        self._selection_count: int = 0

        # GP training data (warmup with prior)
        self._init_gp_prior()

    def _init_gp_prior(self):
        """Initialize GP with a few synthetic prior points to avoid cold start.

        Creates a smooth prior that slightly prefers moderate intentions over
        extreme ones (default utility ~0.5 at moderate features).
        """
        n_prior = 5
        X_prior = np.random.default_rng(42).uniform(
            -1, 1, size=(n_prior, self.cfg.feature_dim)
        ).astype(np.float32)
        y_prior = np.full(n_prior, 0.5, dtype=np.float32)
        self._gp.fit(X_prior, y_prior)

    # -- Public API ---------------------------------------------------------

    def select(self, intentions: List[Intention]) -> Intention:
        """Select the best intention via EFE acquisition.

        Parameters
        ----------
        intentions : List[Intention]
            Candidate intentions for the current cognitive cycle.

        Returns
        -------
        Intention
            The elected intention (mutated in-place with efe_score).

        Raises
        ------
        BayesianSelectionError
            If no intentions provided or GP inference fails.
        """
        if not intentions:
            raise BayesianSelectionError("Cannot select from empty intention list")

        if len(intentions) == 1:
            # Trivial case
            return self._score_intention(intentions[0])

        # Batch predict all candidates
        X = np.array([self._feature_extractor(i) for i in intentions])
        try:
            mu, sigma = self._gp.predict(X)
        except BayesianSelectionError:
            # Fallback to heuristic scoring
            return self._fallback_select(intentions)

        # Score each intention with EFE
        best_idx = 0
        best_efe = -float('inf')

        for idx, intention in enumerate(intentions):
            pragmatic = float(mu[idx])
            epistemic = float(sigma[idx])
            efe = pragmatic + self._curiosity * epistemic

            intention.pragmatic_value = pragmatic
            intention.epistemic_value = epistemic
            intention.efe_score = efe

            if efe > best_efe:
                best_efe = efe
                best_idx = idx

        intentions[best_idx].selected = True
        self._selection_count += 1

        logger.debug(
            f"[bayes] selected '{intentions[best_idx].goal[:30]}' "
            f"efe={best_efe:.3f} (prag={intentions[best_idx].pragmatic_value:.3f}, "
            f"epist={intentions[best_idx].epistemic_value:.3f}, "
            f"curiosity={self._curiosity:.2f})"
        )
        return intentions[best_idx]

    def observe(self, intention: Intention, success: bool,
                reward: Optional[float] = None):
        """Observe the outcome of a selected intention and update the GP.

        Parameters
        ----------
        intention : Intention
            The intention that was executed.
        success : bool
            Whether the intention succeeded.
        reward : float, optional
            Optional custom reward value.  Default 1.0 for success, 0.0 for
            failure.
        """
        r = reward if reward is not None else (1.0 if success else 0.0)
        self._outcomes.append(r)
        if len(self._outcomes) > self.cfg.regret_window:
            self._outcomes.pop(0)

        # Add to GP training data
        x = self._feature_extractor(intention).reshape(1, -1)
        y = np.array([r])

        X_old = self._gp._X
        y_old = self._gp._y
        if X_old is not None:
            X_new = np.vstack([X_old, x])
            y_new = np.hstack([y_old, y])
        else:
            X_new, y_new = x, y

        # Trim to max_intentions
        if X_new.shape[0] > self.cfg.max_intentions:
            X_new = X_new[-self.cfg.max_intentions:]
            y_new = y_new[-self.cfg.max_intentions:]

        try:
            self._gp.fit(X_new, y_new)
        except BayesianSelectionError as e:
            logger.warning(f"GP fit failed after observe: {e}")

        # Adapt curiosity
        self._adapt_curiosity(success)
        logger.debug(
            f"[bayes] observe '{intention.goal[:20]}: "
            f"success={success}, reward={r:.2f}, "
            f"curiosity={self._curiosity:.2f}, "
            f"gp_size={X_new.shape[0]}"
        )

    # -- Properties ---------------------------------------------------------

    @property
    def curiosity(self) -> float:
        """Current curiosity coefficient."""
        return self._curiosity

    @property
    def success_rate(self) -> float:
        """Recent success rate within the regret window."""
        if not self._outcomes:
            return 0.5
        return float(np.mean(self._outcomes))

    @property
    def gp_training_size(self) -> int:
        """Number of training points in the GP."""
        return self._gp._n if self._gp is not None else 0

    # -- Internal methods ---------------------------------------------------

    def _score_intention(self, intention: Intention) -> Intention:
        """Score a single intention using GP prediction."""
        x = self._feature_extractor(intention).reshape(1, -1)
        try:
            mu, sigma = self._gp.predict(x)
            intention.pragmatic_value = float(mu[0])
            intention.epistemic_value = float(sigma[0])
            intention.efe_score = intention.pragmatic_value \
                + self._curiosity * intention.epistemic_value
        except BayesianSelectionError:
            intention.efe_score = intention.priority * 0.6 + intention.urgency * 0.4
        intention.selected = True
        return intention

    def _fallback_select(self, intentions: List[Intention]) -> Intention:
        """Heuristic fallback when GP inference fails."""
        logger.warning("GP inference failed, using heuristic fallback")
        for i in intentions:
            i.efe_score = i.priority * 0.6 + i.urgency * 0.4
        best = max(intentions, key=lambda i: i.efe_score)
        best.selected = True
        return best

    def _adapt_curiosity(self, success: bool):
        """Adapt curiosity based on recent success rate.

        High success → reduce curiosity (exploit more)
        Low success → increase curiosity (explore more)
        """
        if len(self._outcomes) < 5:
            return  # not enough data

        rate = self.success_rate
        if rate > 0.7:
            # Doing well — exploit
            self._curiosity *= self.cfg.curiosity_decay
        elif rate < 0.3:
            # Stuck — explore
            self._curiosity *= self.cfg.curiosity_boost
        # else: moderate — maintain

        self._curiosity = np.clip(
            self._curiosity,
            self.cfg.curiosity_min,
            self.cfg.curiosity_max,
        )

    def reset(self):
        """Reset the selector to initial state."""
        self._curiosity = self.cfg.curiosity_initial
        self._outcomes.clear()
        self._selection_count = 0
        self._init_gp_prior()

    def __repr__(self) -> str:
        return (f"BayesianIntentionSelector(gp_n={self.gp_training_size}, "
                f"curiosity={self._curiosity:.2f}, "
                f"success_rate={self.success_rate:.2f})")
