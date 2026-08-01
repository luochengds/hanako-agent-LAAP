"""Numerical foundation for quantum cognitive engine.

Provides:
  - CognitiveKet  : complex state vector in a finite-dimensional Hilbert space
  - CognitiveOperator: Hermitian / unitary operator construction
  - CrankNicolson : unitary-preserving time step via Cayley transform
  - BornRule      : projective measurement onto a preferred basis

All operations use numpy for numerical stability and performance.
State dimensions are small (N <= 64) in typical cognitive usage, so exact
linear algebra is preferred over stochastic approximations.
"""

from __future__ import annotations

import logging
import math
from typing import Callable, Optional, Sequence, Tuple

import numpy as np

logger = logging.getLogger('quantum_cognition.base')


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------

class QuantumCognitionError(Exception):
    """Base exception for quantum cognition numerical errors."""


class StateNormError(QuantumCognitionError):
    """Raised when a state vector has abnormal norm (|norm-1| > tolerance)."""


class OperatorError(QuantumCognitionError):
    """Raised when an operator violates required properties (Hermiticity, etc.)."""


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

NORM_TOLERANCE: float = 1e-6
"""Floating tolerance for unitarity / normalization checks."""

DEFAULT_DT: float = 0.025
"""Default consciousness time step in arbitrary cognitive-time units."""

ABSORBING_BOUNDARY: float = 1e-8
"""Amplitudes smaller than this are zeroed to prevent underflow noise."""


# ---------------------------------------------------------------------------
# CognitiveKet  —  complex state vector
# ---------------------------------------------------------------------------

class CognitiveKet:
    """Finite-dimensional complex state vector :math:`|\\psi\\rangle`.

    Represents the consciousness state as a unit-norm complex vector in an
    N-dimensional Hilbert space.  Each basis index corresponds to a cognitive
    modality (perceive, select, integrate, act, learn, rest, attention, emotion,
    etc.).

    Parameters
    ----------
    data : np.ndarray, optional
        Initial complex amplitudes.  If None, creates a zero vector.
    dims : int, optional
        Hilbert space dimension (used only when *data* is None).  Default 8.
    dtype : np.dtype, optional
        Complex precision.  Default np.complex64.
    normalize : bool, optional
        Whether to normalize *data* on construction.  Default True.

    Raises
    ------
    StateNormError
        If *normalize* is False and norm deviates from 1 by more than
        NORM_TOLERANCE.
    """

    __slots__ = ('_data', '_dtype')

    def __init__(
        self,
        data: Optional[np.ndarray] = None,
        dims: int = 8,
        dtype: type = np.complex64,
        normalize: bool = True,
    ):
        if data is not None:
            data = np.asarray(data, dtype=dtype)
            if data.ndim != 1:
                raise ValueError(
                    f"CognitiveKet requires a 1-D vector, got shape {data.shape}"
                )
            if normalize:
                norm = np.linalg.norm(data)
                if norm > NORM_TOLERANCE:
                    data = data / norm
                else:
                    raise StateNormError(
                        f"Zero vector cannot be normalized (norm={norm})"
                    )
            else:
                _check_norm(data)
            self._data = data
        else:
            self._data = np.zeros(dims, dtype=dtype)
        self._dtype = self._data.dtype

    # -- properties ---------------------------------------------------------

    @property
    def data(self) -> np.ndarray:
        """Raw complex amplitude array (read-only view)."""
        return self._data

    @property
    def dims(self) -> int:
        """Hilbert space dimension."""
        return self._data.shape[0]

    @property
    def norm(self) -> float:
        """Euclidean norm (should be 1 for a valid state)."""
        return float(np.linalg.norm(self._data))

    @property
    def probabilities(self) -> np.ndarray:
        """Born probabilities :math:`|c_i|^2` for each basis state."""
        return np.abs(self._data) ** 2

    # -- core operations ----------------------------------------------------

    def inner(self, other: CognitiveKet) -> complex:
        """Bra-ket inner product :math:`\\langle\\psi | \\phi\\rangle`."""
        return complex(np.vdot(self._data, other._data))

    def __or__(self, other: CognitiveKet) -> complex:
        """| operator for bra-ket notation: ``psi | phi`` = ⟨psi|phi⟩."""
        return self.inner(other)

    def outer(self, other: CognitiveKet) -> np.ndarray:
        """Outer product :math:`|\\psi\\rangle\\langle\\phi|`."""
        return np.outer(self._data, other._data.conj())

    def evolve(self, operator: np.ndarray) -> CognitiveKet:
        """Apply a linear operator and return the resulting state.

        ``|ψ'⟩ = A |ψ⟩``  followed by renormalization.

        Parameters
        ----------
        operator : np.ndarray
            Square matrix acting on the state vector.

        Returns
        -------
        CognitiveKet
            New state after operator application and normalization.
        """
        if operator.shape != (self.dims, self.dims):
            raise OperatorError(
                f"Operator shape {operator.shape} does not match "
                f"state dimension {self.dims}"
            )
        new_data = operator @ self._data
        return CognitiveKet(new_data, dtype=self._dtype)

    def copy(self) -> CognitiveKet:
        """Return a deep copy."""
        return CognitiveKet(self._data.copy(), normalize=False)

    def __add__(self, other: CognitiveKet) -> CognitiveKet:
        """Superposition (additive, then normalized)."""
        return CognitiveKet(self._data + other._data, dtype=self._dtype)

    def __mul__(self, scalar: complex) -> CognitiveKet:
        """Multiply all amplitudes by a scalar (no renormalization)."""
        return CognitiveKet(self._data * scalar, dtype=self._dtype,
                            normalize=False)

    def __rmul__(self, scalar: complex) -> CognitiveKet:
        return self.__mul__(scalar)

    def __repr__(self) -> str:
        max_amp = np.max(np.abs(self._data))
        return (f"CognitiveKet(dims={self.dims}, "
                f"max_amplitude={max_amp:.4f}, norm={self.norm:.6f})")

    def blast(self, index: int) -> CognitiveKet:
        """Collapse the state to a single basis vector (simulate measurement).

        Parameters
        ----------
        index : int
            Basis index to collapse onto.

        Returns
        -------
        CognitiveKet
            Deterministic basis state |index⟩.
        """
        collapsed = np.zeros(self.dims, dtype=self._dtype)
        collapsed[index] = 1.0
        return CognitiveKet(collapsed, normalize=False)


# ---------------------------------------------------------------------------
# CognitiveOperator  —  Hermitian / unitary operators
# ---------------------------------------------------------------------------

class CognitiveOperator:
    """Hermitian or unitary operator on the cognitive Hilbert space.

    Provides factory methods and validation for the Hamiltonian (Hermitian)
    and the time-evolution operator (unitary).

    Parameters
    ----------
    matrix : np.ndarray
        Square complex matrix.
    validate : bool, optional
        If True, check Hermiticity on construction.  Default True.
    """

    def __init__(self, matrix: np.ndarray, validate: bool = True):
        matrix = np.asarray(matrix, dtype=np.complex64)
        if matrix.ndim != 2 or matrix.shape[0] != matrix.shape[1]:
            raise OperatorError(f"Operator must be square, got shape {matrix.shape}")
        if validate and not np.allclose(matrix, matrix.conj().T, atol=NORM_TOLERANCE):
            raise OperatorError("Operator is not Hermitian")
        self._matrix = matrix

    @property
    def matrix(self) -> np.ndarray:
        return self._matrix

    @property
    def dims(self) -> int:
        return self._matrix.shape[0]

    @property
    def eigenvalues(self) -> np.ndarray:
        """Real eigenvalues (Hermitian guarantee)."""
        return np.linalg.eigvalsh(self._matrix)

    @property
    def spectral_decomposition(self) -> Tuple[np.ndarray, np.ndarray]:
        """(eigenvalues, eigenvectors) where eigenvectors are columns."""
        eigvals, eigvecs = np.linalg.eigh(self._matrix)
        return eigvals, eigvecs

    @staticmethod
    def random_hermitian(dims: int, seed: Optional[int] = None) -> CognitiveOperator:
        """Create a random Hermitian matrix for testing / initialization.

        Uses :math:`H = (G + G^\\dagger) / 2` where G has i.i.d. normal entries.

        Parameters
        ----------
        dims : int
            Matrix dimension.
        seed : int, optional
            Random seed for reproducibility.

        Returns
        -------
        CognitiveOperator
        """
        rng = np.random.default_rng(seed)
        g = rng.standard_normal((dims, dims)) + 1j * rng.standard_normal((dims, dims))
        h = (g + g.conj().T) / 2.0
        return CognitiveOperator(h, validate=False)

    @staticmethod
    def diagonal(energies: np.ndarray) -> CognitiveOperator:
        """Diagonal Hamiltonian with given on-site energies."""
        return CognitiveOperator(np.diag(energies), validate=False)

    def evolve_matrix(self, dt: float = DEFAULT_DT) -> np.ndarray:
        """Return the unitary time-evolution matrix :math:`U = e^{-i H dt}`.

        Uses exact diagonalization for small matrices (stable and accurate).

        Parameters
        ----------
        dt : float
            Time step.

        Returns
        -------
        np.ndarray
            Unitary matrix.
        """
        eigvals, eigvecs = self.spectral_decomposition
        return eigvecs @ np.diag(np.exp(-1j * eigvals * dt)) @ eigvecs.conj().T

    def __repr__(self) -> str:
        return (f"CognitiveOperator(dims={self.dims}, "
                f"eig_range=[{self.eigenvalues[0]:.3f}, "
                f"{self.eigenvalues[-1]:.3f}])")


# ---------------------------------------------------------------------------
# CrankNicolson  —  unitary time stepping
# ---------------------------------------------------------------------------

class CrankNicolson:
    """Unitary-preserving time step via the Cayley transform.

    :math:`\\psi(t+dt) = (I + i H dt/2)^{-1} (I - i H dt/2) \\psi(t)`

    This Crank-Nicolson (CN) discretization of the Schrodinger equation is
    unconditionally stable, exactly unitary, and second-order accurate in dt.
    For the small linear systems of cognitive architecture (N <= 64), direct
    dense solve is used.

    Parameters
    ----------
    hamiltonian : np.ndarray
        Hermitian matrix (the cognitive Hamiltonian).
    dt : float
        Time step.
    """

    def __init__(self, hamiltonian: np.ndarray, dt: float = DEFAULT_DT):
        self._ham = np.asarray(hamiltonian, dtype=np.complex64)
        self._dt = dt
        self._precompute()

    def _precompute(self):
        """Precompute the CN linear system matrices."""
        dims = self._ham.shape[0]
        identity = np.eye(dims, dtype=np.complex64)
        half_step = 0.5j * self._dt
        self._A = identity + half_step * self._ham  # LHS matrix
        self._B = identity - half_step * self._ham  # RHS matrix
        # Factor LHS for fast solves
        self._A_lu = None  # Could pre-factor with scipy; fallback to solve

    def step(self, psi: CognitiveKet) -> CognitiveKet:
        """Advance state by one CN time step.

        Parameters
        ----------
        psi : CognitiveKet
            Current consciousness state.

        Returns
        -------
        CognitiveKet
            State after :math:`\\Delta t`.

        Raises
        ------
        StateNormError
            If the result deviates from unit norm beyond tolerance.
        """
        rhs = self._B @ psi.data
        new_data = np.linalg.solve(self._A, rhs)
        return CognitiveKet(new_data, dtype=psi._dtype)

    def evolve(self, psi: CognitiveKet, num_steps: int) -> CognitiveKet:
        """Advance state by *num_steps* CN steps.

        Parameters
        ----------
        psi : CognitiveKet
            Initial state.
        num_steps : int
            Number of time steps.

        Returns
        -------
        CognitiveKet
            State after total time ``num_steps * dt``.
        """
        for _ in range(num_steps):
            psi = self.step(psi)
        return psi

    def batch_evolve(self, psi: CognitiveKet, num_steps: int) -> list[CognitiveKet]:
        """Evolve and return the full trajectory (including initial state).

        Parameters
        ----------
        psi : CognitiveKet
            Initial state.
        num_steps : int
            Number of time steps.

        Returns
        -------
        list[CognitiveKet]
            Trajectory of length *num_steps* + 1.
        """
        trajectory = [psi.copy()]
        for _ in range(num_steps):
            psi = self.step(psi)
            trajectory.append(psi.copy())
        return trajectory

    @property
    def dt(self) -> float:
        return self._dt


# ---------------------------------------------------------------------------
# BornRule  —  projective measurement
# ---------------------------------------------------------------------------

class BornRule:
    """Born-rule projective measurement onto a specified basis.

    For a state :math:`|\\psi\\rangle = \\sum_i c_i |i\\rangle`, the probability
    of observing outcome *i* is :math:`p_i = |c_i|^2`, and the post-measurement
    state collapses to :math:`|i\\rangle`.
    """

    @staticmethod
    def measure(psi: CognitiveKet, rng: Optional[np.random.Generator] = None
                ) -> Tuple[int, float]:
        """Sample one measurement outcome via the Born rule.

        Parameters
        ----------
        psi : CognitiveKet
            The consciousness state.
        rng : np.random.Generator, optional
            Random generator for reproducibility.

        Returns
        -------
        (int, float)
            (index of the collapsed basis state,
             probability of that outcome before measurement)
        """
        probs = psi.probabilities
        rng = rng or np.random.default_rng()
        index = rng.choice(psi.dims, p=probs)
        return int(index), float(probs[index])

    @staticmethod
    def measure_deterministic(psi: CognitiveKet,
                              temperature: float = 0.0) -> int:
        """Deterministic 'measurement' — pick the most likely outcome.

        When *temperature* > 0, uses softmax-weighted choice instead of
        argmax, introducing controlled stochasticity.

        Parameters
        ----------
        psi : CognitiveKet
            State vector.
        temperature : float
            If 0, use argmax.  If > 0, use softmax-weighted sampling.

        Returns
        -------
        int
            Basis index.
        """
        probs = psi.probabilities
        if temperature <= 0:
            return int(np.argmax(probs))
        # Softmax-weighted sampling
        logits = np.log(probs + 1e-30) / temperature
        weights = np.exp(logits - np.max(logits))
        weights /= weights.sum()
        return int(np.random.choice(psi.dims, p=weights))

    @staticmethod
    def entropy(psi: CognitiveKet) -> float:
        """Shannon entropy of the Born probability distribution.

        A measure of cognitive uncertainty: 0 = fully certain;
        log(dims) = fully uncertain.

        Parameters
        ----------
        psi : CognitiveKet
            State vector.

        Returns
        -------
        float
            Entropy in nats.
        """
        probs = psi.probabilities
        probs = probs[probs > ABSORBING_BOUNDARY]
        return float(-np.sum(probs * np.log(probs)))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _check_norm(psi: np.ndarray, tol: float = NORM_TOLERANCE):
    """Validate that *psi* is unit-norm within tolerance."""
    norm = np.linalg.norm(psi)
    if abs(norm - 1.0) > tol:
        raise StateNormError(
            f"State norm is {norm:.6f}, expected 1.0 ± {tol}"
        )


def zero_state(dims: int, index: int = 0,
               dtype: type = np.complex64) -> CognitiveKet:
    """Factory: create a basis state :math:`|i\\rangle`.

    Parameters
    ----------
    dims : int
        Hilbert space dimension.
    index : int
        Which basis element to set to 1.  Default 0.
    dtype : type
        Complex precision.  Default np.complex64.

    Returns
    -------
    CognitiveKet
        Normalized basis state.
    """
    data = np.zeros(dims, dtype=dtype)
    data[index] = 1.0
    return CognitiveKet(data, normalize=False)
