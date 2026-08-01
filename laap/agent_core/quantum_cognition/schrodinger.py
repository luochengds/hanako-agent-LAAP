"""Schrodinger evolver — Hamiltonian-driven consciousness state evolution.

Implements the core quantum dynamics of the cognitive architecture:
  - A learned Hermitian Hamiltonian H encodes the natural dynamics of the
    cognitive system (modal coupling strengths, energy landscape).
  - The consciousness state |psi⟩ evolves unitarily via the Crank-Nicolson
    discretization of the Schrodinger equation.
  - Stimuli are applied as perturbations to the Hamiltonian or as projections
    onto specific basis states (excitation of specific cognitive modes).
  - Action selection uses the Born rule to project |psi⟩ onto the action basis.

The Hamiltonian's eigendecomposition provides interpretable insight:
  - Eigenvalues = cognitive 'energy levels' (stability of each mode)
  - Eigenvectors = the 'natural modes' of the cognitive system
  - The ground state = the attractor state the system drifts toward
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from .base import (
    CognitiveKet,
    CognitiveOperator,
    CrankNicolson,
    BornRule,
    zero_state,
    DEFAULT_DT,
    NORM_TOLERANCE,
    StateNormError,
    OperatorError,
)

logger = logging.getLogger('quantum_cognition.schrodinger')


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class SchrodingerError(Exception):
    """Raised on numerical failure of the Schrodinger engine."""


# ---------------------------------------------------------------------------
# Default basis state labels
# ---------------------------------------------------------------------------

DEFAULT_BASIS_LABELS: List[str] = [
    'perceive',      # 0 — sensory input processing
    'select',        # 1 — intention selection
    'integrate',     # 2 — cognitive integration
    'act',           # 3 — action execution
    'learn',         # 4 — learning from outcome
    'rest',          # 5 — cognitive rest / idle
    'attention',     # 6 — focused attention
    'emotion',       # 7 — emotional / valence-arousal state
    'meta',          # 8 — meta-cognition / self-reflection
    'memory',        # 9 — memory retrieval / consolidation
]


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class SchrodingerConfig:
    """Configuration for the Schrodinger evolver.

    Parameters
    ----------
    dims : int
        Hilbert space dimension (number of cognitive modalities).
    dt : float
        Consciousness time step in arbitrary units.
    coupling_strength : float
        Default off-diagonal coupling magnitude for Hamiltonian initialization.
    diagonal_energies : List[float], optional
        On-site energies for each cognitive mode.  Default assigns higher
        energy to 'rest' and 'meta', lower to 'perceive' and 'act'.
    basis_labels : List[str], optional
        Human-readable labels for each basis state.
    random_seed : int, optional
        Seed for reproducible Hamiltonian initialization.
    learn_rate : float
        Learning rate for Hamiltonian updates from experience.
    name : str
        Human-readable identifier for logging.
    """
    dims: int = len(DEFAULT_BASIS_LABELS)
    dt: float = DEFAULT_DT
    coupling_strength: float = 0.15
    diagonal_energies: Optional[List[float]] = None
    basis_labels: Optional[List[str]] = None
    random_seed: Optional[int] = None
    learn_rate: float = 0.01
    name: str = "schrodinger"


# ---------------------------------------------------------------------------
# SchrodingerEvolver
# ---------------------------------------------------------------------------

class SchrodingerEvolver:
    """Hamiltonian-driven consciousness state evolution.

    Manages the cognitive state vector |psi⟩, the Hamiltonian H, and
    provides methods for evolution, measurement, stimulus application,
    and Hamiltonian learning.

    Parameters
    ----------
    config : SchrodingerConfig, optional
    """

    def __init__(self, config: Optional[SchrodingerConfig] = None):
        self.cfg = config or SchrodingerConfig()
        self._dims = self.cfg.dims
        self._dt = self.cfg.dt

        # Basis labels
        self._labels = (self.cfg.basis_labels or
                        DEFAULT_BASIS_LABELS[:self._dims])
        if len(self._labels) > self._dims:
            self._labels = self._labels[:self._dims]
        while len(self._labels) < self._dims:
            self._labels.append(f"mode_{len(self._labels)}")

        # Hamiltonian
        self._hamiltonian: CognitiveOperator = self._init_hamiltonian()

        # Time evolution operator
        self._cn = CrankNicolson(self._hamiltonian.matrix, self._dt)

        # Current state (start in |perceive⟩)
        self._psi: CognitiveKet = zero_state(self._dims, index=0)

        # Born rule engine
        self._born = BornRule()

        # Tracking
        self._steps: int = 0
        self._state_history: List[CognitiveKet] = []

    # -- Core evolution -----------------------------------------------------

    def step(self, stimulus: Optional[np.ndarray] = None) -> CognitiveKet:
        """Advance the consciousness state by one time step.

        1. Apply stimulus perturbation (if provided)
        2. Evolve via CN step
        3. Increment step counter

        Parameters
        ----------
        stimulus : np.ndarray, optional
            Feature vector of shape ``(dims,)`` that couples into the
            Hamiltonian as an external potential perturbation.

        Returns
        -------
        CognitiveKet
            New consciousness state |ψ(t+dt)⟩.
        """
        try:
            if stimulus is not None:
                self._apply_stimulus(stimulus)

            self._psi = self._cn.step(self._psi)
            self._steps += 1
            return self._psi.copy()

        except (StateNormError, np.linalg.LinAlgError) as e:
            raise SchrodingerError(f"Evolution failed: {e}") from e

    def evolve(self, num_steps: int) -> CognitiveKet:
        """Advance state by *num_steps* steps (no external stimulus)."""
        for _ in range(num_steps):
            self._psi = self._cn.step(self._psi)
            self._steps += 1
        return self._psi.copy()

    # -- Measurement --------------------------------------------------------

    def measure(self, temperature: float = 0.0) -> int:
        """Measure the consciousness state and collapse.

        Parameters
        ----------
        temperature : float
            If 0, deterministic argmax; if >0, softmax-weighted sampling.

        Returns
        -------
        int
            Index of the selected cognitive mode (basis state).
        """
        return self._born.measure_deterministic(self._psi, temperature)

    def measure_born(self) -> Tuple[int, float]:
        """True Born-rule measurement (stochastic sampling).

        Returns
        -------
        (int, float)
            (outcome index, probability of that outcome)
        """
        return self._born.measure(self._psi)

    @property
    def probabilities(self) -> np.ndarray:
        """Born probabilities for each cognitive mode."""
        return self._psi.probabilities

    def entropy(self) -> float:
        """Shannon entropy of the current state (uncertainty measure)."""
        return self._born.entropy(self._psi)

    def most_likely_mode(self) -> Tuple[str, float]:
        """Return (label, probability) of the most likely cognitive mode."""
        idx = int(np.argmax(self._psi.probabilities))
        return self._labels[idx], float(self._psi.probabilities[idx])

    # -- State access -------------------------------------------------------

    @property
    def psi(self) -> CognitiveKet:
        """Current consciousness state (read-only copy)."""
        return self._psi.copy()

    @psi.setter
    def psi(self, new_psi: CognitiveKet):
        """Set consciousness state directly (use with care)."""
        if new_psi.dims != self._dims:
            raise ValueError(
                f"Cannot set state with dim {new_psi.dims} != {self._dims}"
            )
        self._psi = new_psi.copy()

    @property
    def hamiltonian(self) -> np.ndarray:
        """Current Hamiltonian matrix (read-only copy)."""
        return self._hamiltonian.matrix.copy()

    @property
    def spectrum(self) -> Tuple[np.ndarray, np.ndarray]:
        """(eigenvalues, eigenvectors) of the current Hamiltonian."""
        return self._hamiltonian.spectral_decomposition

    @property
    def energy(self) -> float:
        """Expected energy ⟨ψ|H|ψ⟩ of the current state."""
        return float(np.real(
            np.vdot(self._psi.data,
                    self._hamiltonian.matrix @ self._psi.data)
        ))

    @property
    def ground_state(self) -> CognitiveKet:
        """Ground state of the Hamiltonian (lowest energy eigenstate).

        This is the natural attractor of the cognitive system — the state
        it trends toward in the absence of external stimuli.
        """
        eigvals, eigvecs = self._hamiltonian.spectral_decomposition
        gs = eigvecs[:, 0]  # smallest eigenvalue
        return CognitiveKet(gs, normalize=True)

    # -- Hamiltonian management ---------------------------------------------

    def update_hamiltonian(self, delta_H: np.ndarray):
        """Apply a Hermitian update to the Hamiltonian.

        Parameters
        ----------
        delta_H : np.ndarray
            Hermitian matrix of same dimension as H.
        """
        if delta_H.shape != (self._dims, self._dims):
            raise OperatorError(
                f"Delta shape {delta_H.shape} != ({self._dims}, {self._dims})"
            )
        new_H = self._hamiltonian.matrix + self.cfg.learn_rate * delta_H
        # Ensure Hermiticity
        new_H = (new_H + new_H.conj().T) / 2.0
        self._hamiltonian = CognitiveOperator(new_H)
        self._rebuild_cn()

    def learn_from_experience(self, outcome_state: CognitiveKet,
                               reward: float):
        """Update Hamiltonian based on outcome: Hebbian-like reinforcement.

        Strengthens couplings between active modes that led to positive
        outcomes.  This is essentially a quantum Hebbian learning rule:

            ΔH = α * (reward - baseline) * |ψ_outcome⟩⟨ψ_outcome|

        Parameters
        ----------
        outcome_state : CognitiveKet
            The cognitive state at outcome time.
        reward : float
            Reward signal (positive = reinforce, negative = weaken).
        """
        # Outer product |ψ⟩⟨ψ| — the 'density matrix' of the outcome
        density = np.outer(outcome_state.data, outcome_state.data.conj())
        # Ensure Hermitian
        density = (density + density.conj().T) / 2.0
        # Scale by reward
        delta = density * self.cfg.learn_rate * reward
        self.update_hamiltonian(delta)

    # -- Stimulus processing -------------------------------------------------

    def _apply_stimulus(self, stimulus: np.ndarray):
        """Apply a stimulus as a potential perturbation V(t).

        V(t) = diag(stimulus_features) + off-diagonal coupling * features_outer

        This models the stimulus as an external potential that locally
        modifies the energy landscape of the cognitive system.
        """
        # Diagonal excitation
        V_diag = np.diag(stimulus.astype(np.complex64))

        # Off-diagonal coupling (pairwise mode excitation)
        coupling = self.cfg.coupling_strength
        V_off = coupling * np.outer(stimulus, stimulus.conj())

        V_total = V_diag + V_off
        V_total = (V_total + V_total.conj().T) / 2.0  # ensure Hermitian

        # Apply perturbation via modified short-time evolution
        # (single step with modified Hamiltonian)
        total_H = self._hamiltonian.matrix + V_total
        tmp_cn = CrankNicolson(total_H, self._dt)
        self._psi = tmp_cn.step(self._psi)

    def _init_hamiltonian(self) -> CognitiveOperator:
        """Build the initial cognitive Hamiltonian.

        Diagonal: base energies per cognitive mode.
        Off-diagonal: small coupling between related modes.
        """
        diag = self.cfg.diagonal_energies
        if diag is None:
            base = np.array([0.5, 1.0, 1.0, 0.8, 1.2, 2.0, 0.5, 1.5, 1.8, 1.0],
                            dtype=np.float32)
            if self._dims <= len(base):
                diag = base[:self._dims].tolist()
            else:
                diag = base.tolist() + [1.0] * (self._dims - len(base))

        H = np.diag(diag).astype(np.complex64)

        # Off-diagonal couplings with interpretable structure
        coupling = self.cfg.coupling_strength
        rng = np.random.default_rng(self.cfg.random_seed)

        # perceive ↔ attention (strong): attention amplifies perception
        if self._dims > 6:
            H[0, 6] = H[6, 0] = coupling * 1.5

        # select ↔ integrate (moderate): selection feeds integration
        if self._dims > 2:
            H[1, 2] = H[2, 1] = coupling * 1.0

        # perceive ↔ emotion (moderate): emotion colors perception
        if self._dims > 7:
            H[0, 7] = H[7, 0] = coupling * 0.8

        # meta ↔ all (weak): meta-cognition weakly coupled to all modes
        if self._dims > 8:
            for i in range(min(8, self._dims)):
                H[i, 8] = H[8, i] = coupling * 0.3 + rng.uniform(0, 0.1)

        # Add small random symmetric coupling
        sym = (rng.uniform(-0.1, 0.1, (self._dims, self._dims)) +
               rng.uniform(-0.1, 0.1, (self._dims, self._dims)) * 1j)
        sym = (sym + sym.conj().T) / 2.0
        H += sym * coupling * 0.2

        return CognitiveOperator(H)

    def _rebuild_cn(self):
        """Rebuild the Crank-Nicolson propagator after Hamiltonian change."""
        self._cn = CrankNicolson(self._hamiltonian.matrix, self._dt)

    # -- Serialization helpers -----------------------------------------------

    def get_debug_info(self) -> dict:
        """Detailed debug information."""
        eigvals, _ = self.spectrum
        mode, prob = self.most_likely_mode()
        return {
            'dims': self._dims,
            'dt': self._dt,
            'steps': self._steps,
            'energy': self.energy,
            'entropy': self.entropy(),
            'most_likely_mode': mode,
            'mode_probability': prob,
            'eigenvalue_range': [float(eigvals[0]), float(eigvals[-1])],
            'hamiltonian_norm': float(np.linalg.norm(self._hamiltonian.matrix)),
            'basis_labels': self._labels,
        }

    def reset(self):
        """Reset state and history (keeps Hamiltonian)."""
        self._psi = zero_state(self._dims, index=0)
        self._steps = 0
        self._state_history.clear()

    def __repr__(self) -> str:
        mode, prob = self.most_likely_mode()
        return (f"SchrodingerEvolver(dims={self._dims}, "
                f"steps={self._steps}, "
                f"E={self.energy:.3f}, "
                f"S={self.entropy():.3f}, "
                f"mode='{mode}'({prob:.1%}))")
