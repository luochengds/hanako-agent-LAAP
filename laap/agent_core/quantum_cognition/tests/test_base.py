"""Tests for the quantum cognition engine components.

Run with: python -m pytest D:\LAAP\laap\agent_core\quantum_cognition\tests\ -v
"""
from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))

import numpy as np
import pytest

from laap.agent_core.quantum_cognition.base import (
    CognitiveKet, CognitiveOperator, CrankNicolson, BornRule,
    zero_state, StateNormError, OperatorError,
)


class TestCognitiveKet:
    def test_initialization(self):
        ket = CognitiveKet(dims=4)
        assert ket.dims == 4
        assert ket.norm == 0.0

    def test_normalized_initialization(self):
        data = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.complex64)
        ket = CognitiveKet(data=data)
        assert abs(ket.norm - 1.0) < 1e-6

    def test_auto_normalization(self):
        data = np.array([2.0, 0.0, 0.0, 0.0], dtype=np.complex64)
        ket = CognitiveKet(data=data)
        assert abs(ket.norm - 1.0) < 1e-6
        assert abs(ket.data[0] - 1.0) < 1e-6

    def test_zero_vector_raises(self):
        with pytest.raises(StateNormError):
            CognitiveKet(data=np.zeros(4, dtype=np.complex64))

    def test_inner_product(self):
        a = CognitiveKet(data=np.array([1.0, 0.0, 0.0, 0.0], dtype=np.complex64))
        b = CognitiveKet(data=np.array([0.0, 1.0, 0.0, 0.0], dtype=np.complex64))
        assert abs(a.inner(b)) < 1e-6
        assert abs(a.inner(a) - 1.0) < 1e-6

    def test_bra_ket_operator(self):
        a = CognitiveKet(data=np.array([0.5+0.5j, 0.5-0.5j], dtype=np.complex64),
                          normalize=True)
        result = a | a
        assert abs(result - 1.0) < 0.01

    def test_outer_product(self):
        a = zero_state(3, index=0)
        b = zero_state(3, index=1)
        outer = a.outer(b)
        assert outer.shape == (3, 3)
        assert abs(outer[0, 1] - 1.0) < 1e-6
        assert abs(outer[0, 0]) < 1e-6

    def test_evolve(self):
        ket = zero_state(4, index=0)
        I = np.eye(4, dtype=np.complex64)
        evolved = ket.evolve(I)
        assert abs(evolved.inner(ket) - 1.0) < 1e-6

    def test_probabilities(self):
        data = np.array([1.0, 1.0, 0.0, 0.0], dtype=np.complex64)
        ket = CognitiveKet(data=data)
        probs = ket.probabilities
        assert abs(probs[0] - 0.5) < 1e-6
        assert abs(probs[1] - 0.5) < 1e-6
        assert abs(sum(probs) - 1.0) < 1e-6

    def test_superposition(self):
        a = zero_state(3, index=0)
        b = zero_state(3, index=1)
        c = a + b
        assert abs(c.norm - 1.0) < 1e-6
        assert abs(c.probabilities[0] - 0.5) < 1e-6

    def test_blast(self):
        ket = zero_state(8, index=3)
        assert abs(ket.data[3] - 1.0) < 1e-6


class TestCognitiveOperator:
    def test_hermitian_construction(self):
        H = np.array([[1.0, 0.5j], [-0.5j, 2.0]], dtype=np.complex64)
        op = CognitiveOperator(H)
        assert op.dims == 2

    def test_non_hermitian_raises(self):
        H = np.array([[1.0, 2.0], [0.0, 1.0]], dtype=np.complex64)
        with pytest.raises(OperatorError):
            CognitiveOperator(H)

    def test_eigenvalues_real(self):
        op = CognitiveOperator.random_hermitian(5, seed=42)
        ev = op.eigenvalues
        assert np.all(np.isreal(ev))

    def test_spectral_decomposition(self):
        op = CognitiveOperator.random_hermitian(4, seed=42)
        evals, evecs = op.spectral_decomposition
        assert evals.shape == (4,)
        assert evecs.shape == (4, 4)

    def test_diagonal(self):
        op = CognitiveOperator.diagonal(np.array([1.0, 2.0, 3.0]))
        assert op.eigenvalues[0] == 1.0

    def test_evolve_matrix_unitary(self):
        op = CognitiveOperator.random_hermitian(4, seed=42)
        U = op.evolve_matrix(dt=0.1)
        # U @ U^dagger = I
        prod = U @ U.conj().T
        assert np.allclose(prod, np.eye(4), atol=1e-6)


class TestCrankNicolson:
    def test_unitarity(self):
        H = CognitiveOperator.random_hermitian(4, seed=42)
        cn = CrankNicolson(H.matrix, dt=0.025)
        psi = zero_state(4, index=0)
        for _ in range(100):
            psi = cn.step(psi)
        assert abs(psi.norm - 1.0) < 1e-4

    def test_energy_conservation(self):
        H = CognitiveOperator.diagonal(np.array([1.0, 2.0, 3.0, 4.0]))
        cn = CrankNicolson(H.matrix, dt=0.025)
        psi = zero_state(4, index=1)
        initial_energy = np.real(np.vdot(psi.data, H.matrix @ psi.data))
        for _ in range(50):
            psi = cn.step(psi)
        final_energy = np.real(np.vdot(psi.data, H.matrix @ psi.data))
        assert abs(initial_energy - final_energy) < 1e-4

    def test_batch_evolve(self):
        H = CognitiveOperator.random_hermitian(4, seed=42)
        cn = CrankNicolson(H.matrix, dt=0.025)
        psi = zero_state(4, index=0)
        traj = cn.batch_evolve(psi, 10)
        assert len(traj) == 11
        assert all(abs(t.norm - 1.0) < 1e-4 for t in traj)


class TestBornRule:
    def test_entropy_zero_for_pure_state(self):
        ket = zero_state(4, index=0)
        entropy = BornRule.entropy(ket)
        assert abs(entropy) < 1e-6

    def test_entropy_max_for_equal_superposition(self):
        data = np.ones(4, dtype=np.complex64)
        ket = CognitiveKet(data=data)
        entropy = BornRule.entropy(ket)
        assert abs(entropy - np.log(4)) < 0.01

    def test_measurement_outcome(self):
        data = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.complex64)
        ket = CognitiveKet(data=data)
        idx, prob = BornRule.measure(ket)
        assert idx == 0
        assert abs(prob - 1.0) < 1e-6

    def test_measure_deterministic(self):
        data = np.array([0.1, 0.9, 0.0, 0.0], dtype=np.complex64)
        ket = CognitiveKet(data=data)
        idx = BornRule.measure_deterministic(ket)
        assert idx == 1  # highest probability


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
