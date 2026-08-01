"""Kalman filter self-model — recursive Bayesian state estimation for cognition.

Replaces the heuristic ``SelfPerception`` class in ``aris_consciousness.py``.

The Kalman filter provides a principled framework for estimating the agent's
internal cognitive state (confidence, arousal, valence, fatigue, attention
quality, coherence) by fusing:
  - a dynamics model (how the state evolves naturally over time)
  - noisy observations (how perceptions constrain the state)

The Kalman gain K automatically determines whether to trust the dynamics
prediction or the current observation based on their relative uncertainties.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger('quantum_cognition.kalman_self')


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class KalmanFilterError(Exception):
    """Raised on numerical failure of the Kalman filter."""


# ---------------------------------------------------------------------------
# Default state dimensions
# ---------------------------------------------------------------------------

#: Default state vector indices
IDX_CONFIDENCE = 0
IDX_AROUSAL = 1
IDX_VALENCE = 2
IDX_FATIGUE = 3
IDX_ATTENTION = 4
IDX_COHERENCE = 5

STATE_LABELS: List[str] = [
    'confidence', 'arousal', 'valence', 'fatigue',
    'attention_quality', 'coherence',
]

#: Default number of state dimensions
DEFAULT_DIM = len(STATE_LABELS)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class KalmanConfig:
    """Configurable parameters for the Kalman self-model.

    Parameters
    ----------
    dim_state : int
        Dimensionality of the cognitive state vector.
    process_noise : float or np.ndarray
        Base process noise variance (scalar or diag matrix).  Higher values
        make the model trust observations more.
    observation_noise : float or np.ndarray
        Base observation noise variance.  Higher values make the model trust
        its dynamics prediction more.
    state_decay : float or np.ndarray
        Per-state retention factor (0-1).  1 = perfect memory, 0 = reset each
        step.  Applied as diagonal of state transition matrix F.
    state_bounds : Dict[int, Tuple[float, float]], optional
        Per-dimension (min, max) bounds.  Unbounded dimensions omitted.
    name : str
        Human-readable identifier for logging.
    """
    dim_state: int = DEFAULT_DIM
    process_noise: float = 0.01
    observation_noise: float = 0.05
    state_decay: float = 0.90
    state_bounds: Dict[int, Tuple[float, float]] = field(default_factory=lambda: {
        IDX_CONFIDENCE: (0.0, 1.0),
        IDX_AROUSAL: (0.0, 1.0),
        IDX_VALENCE: (-1.0, 1.0),
        IDX_FATIGUE: (0.0, 1.0),
        IDX_ATTENTION: (0.0, 1.0),
        IDX_COHERENCE: (0.0, 1.0),
    })
    adaptive_noise: bool = True
    """If True, estimate R (observation noise) online from residual history."""

    name: str = "kalman_self"


# ---------------------------------------------------------------------------
# KalmanSelfModel
# ---------------------------------------------------------------------------

class KalmanSelfModel:
    """Recursive Bayesian estimator for the agent's cognitive state.

    Standard linear Kalman filter:
      Predict:  x̂ₜ|ₜ₋₁ = F x̂ₜ₋₁|ₜ₋₁
                Pₜ|ₜ₋₁  = F Pₜ₋₁|ₜ₋₁ Fᵀ + Q
      Update:   Kₜ      = Pₜ|ₜ₋₁ Hᵀ (H Pₜ|ₜ₋₁ Hᵀ + R)⁻¹
                x̂ₜ|ₜ    = x̂ₜ|ₜ₋₁ + Kₜ (yₜ - H x̂ₜ|ₜ₋₁)
                Pₜ|ₜ    = (I - Kₜ H) Pₜ|ₜ₋₁

    Parameters
    ----------
    config : KalmanConfig, optional
        Filter configuration.
    """

    def __init__(self, config: Optional[KalmanConfig] = None):
        self.cfg = config or KalmanConfig()
        n = self.cfg.dim_state

        # State
        self._x: np.ndarray = np.full(n, 0.5, dtype=np.float32)
        self._x[IDX_VALENCE] = 0.0          # neutral valence initially
        self._x[IDX_FATIGUE] = 0.1          # low fatigue initially
        self._x[IDX_COHERENCE] = 0.7        # moderate coherence initially

        # Error covariance
        self._P: np.ndarray = np.eye(n, dtype=np.float32) * 0.1

        # State transition
        decay = self.cfg.state_decay
        if isinstance(decay, (int, float)):
            self._F: np.ndarray = np.eye(n, dtype=np.float32) * decay
            # Custom dynamics: arousal decays faster, fatigue accumulates
            self._F[IDX_AROUSAL, IDX_AROUSAL] = 0.85
            self._F[IDX_FATIGUE, IDX_FATIGUE] = 0.98  # fatigue persists
            # Attention influenced by arousal
            self._F[IDX_ATTENTION, IDX_AROUSAL] = 0.15
            # Coherence influenced by valence + attention
            self._F[IDX_COHERENCE, IDX_VALENCE] = 0.10
            self._F[IDX_COHERENCE, IDX_ATTENTION] = 0.10
        else:
            self._F = np.asarray(decay, dtype=np.float32)

        # Observation matrix (full state observation by default)
        self._H: np.ndarray = np.eye(n, dtype=np.float32)

        # Noise covariances
        pq = self.cfg.process_noise
        self._Q: np.ndarray = np.eye(n, dtype=np.float32) * (
            pq if isinstance(pq, (int, float)) else pq
        )
        pr = self.cfg.observation_noise
        self._R: np.ndarray = np.eye(n, dtype=np.float32) * (
            pr if isinstance(pr, (int, float)) else pr
        )

        # Bounds projection
        self._bounds: Dict[int, Tuple[float, float]] = self.cfg.state_bounds
        self._residual_buffer: list[np.ndarray] = []
        self._max_residuals: int = 50

        # Tracking
        self._step_count: int = 0
        self._log_interval: int = 100
        self._last_logged_state: Optional[np.ndarray] = None

    # -- Public API ---------------------------------------------------------

    def predict(self) -> np.ndarray:
        """Prediction step: evolve the state estimate forward in time.

        Returns
        -------
        np.ndarray
            Predicted state vector x̂ₜ|ₜ₋₁.
        """
        try:
            self._x = self._F @ self._x
            self._P = self._F @ self._P @ self._F.T + self._Q
            self._x = self._apply_bounds(self._x)
            self._step_count += 1
            return self._x.copy()
        except np.linalg.LinAlgError as e:
            raise KalmanFilterError(f"Predict failed: {e}") from e

    def update(self, observation: np.ndarray) -> np.ndarray:
        """Update step: fuse observation to correct the state estimate.

        Parameters
        ----------
        observation : np.ndarray
            Observed cognitive state values (same dimension as state).

        Returns
        -------
        np.ndarray
            Corrected state vector x̂ₜ|ₜ.

        Raises
        ------
        KalmanFilterError
            On numerical failure of the matrix operations.
        """
        obs = np.asarray(observation, dtype=np.float32).flatten()
        if obs.shape[0] != self._x.shape[0]:
            raise ValueError(
                f"Observation dim {obs.shape[0]} != state dim {self._x.shape[0]}"
            )

        try:
            # Innovation (residual)
            y = obs - self._H @ self._x
            S = self._H @ self._P @ self._H.T + self._R
            Sinv = np.linalg.inv(S)

            # Kalman gain
            K = self._P @ self._H.T @ Sinv

            # State update
            self._x = self._x + K @ y

            # Covariance update (Joseph form for numerical stability)
            I = np.eye(self._x.shape[0], dtype=np.float32)
            self._P = (I - K @ self._H) @ self._P @ (I - K @ self._H).T + \
                      K @ self._R @ K.T

            # Bounds
            self._x = self._apply_bounds(self._x)

            # Adaptive noise
            if self.cfg.adaptive_noise:
                self._update_adaptive_noise(y)

            # Logging
            if self._step_count % self._log_interval == 0:
                self._log_state()

            return self._x.copy()

        except np.linalg.LinAlgError as e:
            raise KalmanFilterError(f"Update failed: {e}") from e

    def observe(self, observation: np.ndarray) -> np.ndarray:
        """Convenience: predict + update in one call.

        Parameters
        ----------
        observation : np.ndarray
            Observed state.

        Returns
        -------
        np.ndarray
            Corrected state estimate.
        """
        self.predict()
        return self.update(observation)

    # -- State queries ------------------------------------------------------

    @property
    def state_vector(self) -> np.ndarray:
        """Current state vector (read-only copy)."""
        return self._x.copy()

    @property
    def state_dict(self) -> Dict[str, float]:
        """State as a dictionary keyed by dimension names."""
        return {STATE_LABELS[i]: float(self._x[i])
                for i in range(min(len(STATE_LABELS), self._x.shape[0]))}

    @property
    def calibrated_confidence(self) -> float:
        """Confidence after Kalman filtering, clamped to [0, 1]."""
        return float(np.clip(self._x[IDX_CONFIDENCE], 0.0, 1.0))

    @property
    def uncertainty(self) -> np.ndarray:
        """Diagonal of the error covariance matrix (per-dimension uncertainty)."""
        return np.sqrt(np.diag(self._P))

    @property
    def total_uncertainty(self) -> float:
        """Trace of the error covariance (scalar uncertainty measure)."""
        return float(np.trace(self._P))

    @property
    def kalman_gain_magnitude(self) -> float:
        """Frobenius norm of the most recent Kalman gain.

        High gain → model is trusting observations more than dynamics.
        Low gain → model is trusting its internal dynamics.
        """
        return float(np.linalg.norm(self._P @ self._H.T))

    # -- Internal methods ---------------------------------------------------

    def _apply_bounds(self, x: np.ndarray) -> np.ndarray:
        """Project state onto feasible bounds."""
        x = x.copy()
        for idx, (lo, hi) in self._bounds.items():
            x[idx] = np.clip(x[idx], lo, hi)
        return x

    def _update_adaptive_noise(self, residual: np.ndarray):
        """Online estimation of observation noise via exponential moving average.

        Adapts R matrix based on observed residual covariance.  Overconfident
        predictions (small innovation compared to S) increase R, reducing
        future trust in observations.
        """
        self._residual_buffer.append(residual)
        if len(self._residual_buffer) > self._max_residuals:
            self._residual_buffer.pop(0)

        if len(self._residual_buffer) >= 10:
            residual_cov = np.cov(np.array(self._residual_buffer).T)
            # Exponentially smooth R toward observed residual covariance
            alpha = 0.05
            self._R = (1 - alpha) * self._R + alpha * np.diag(np.diag(residual_cov))
            # Ensure positive definiteness floor
            self._R = np.maximum(self._R, np.eye(self._R.shape[0]) * 1e-6)

    def _log_state(self):
        """Write structured log of current state."""
        sd = self.state_dict
        logger.info(
            f"[kalman] step={self._step_count} | "
            + " | ".join(f"{k}={v:.3f}" for k, v in sd.items())
            + f" | uncertainty={self.total_uncertainty:.4f}"
        )
        self._last_logged_state = self._x.copy()

    def reset(self, initial_state: Optional[np.ndarray] = None):
        """Reset the filter to initial conditions.

        Parameters
        ----------
        initial_state : np.ndarray, optional
            If provided, sets the initial state; otherwise uses defaults.
        """
        n = self.cfg.dim_state
        if initial_state is not None:
            self._x = np.asarray(initial_state, dtype=np.float32).flatten()
        else:
            self._x = np.full(n, 0.5, dtype=np.float32)
            self._x[IDX_VALENCE] = 0.0
            self._x[IDX_FATIGUE] = 0.1
            self._x[IDX_COHERENCE] = 0.7
        self._P = np.eye(n, dtype=np.float32) * 0.1
        self._residual_buffer.clear()
        self._step_count = 0

    def __repr__(self) -> str:
        return (f"KalmanSelfModel(dim={self.cfg.dim_state}, "
                f"step={self._step_count}, "
                f"conf={self.calibrated_confidence:.2f}, "
                f"uncertainty={self.total_uncertainty:.4f})")
