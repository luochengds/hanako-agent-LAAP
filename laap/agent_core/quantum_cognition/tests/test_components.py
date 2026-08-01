"""Tests for Kalman self-model, spectral saliency, Bayesian selector,
Schrodinger evolver, Occam meta-controller, and PsiQuantumCognition.
"""
from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))

import numpy as np
import pytest

from laap.agent_core.quantum_cognition.kalman_self import (
    KalmanSelfModel, KalmanConfig, IDX_CONFIDENCE,
)
from laap.agent_core.quantum_cognition.spectral_saliency import (
    SpectralSaliency, SpectralSaliencyConfig,
)
from laap.agent_core.quantum_cognition.bayesian_selector import (
    BayesianIntentionSelector, BayesianSelectorConfig, Intention,
)
from laap.agent_core.quantum_cognition.schrodinger import (
    SchrodingerEvolver, SchrodingerConfig,
)
from laap.agent_core.quantum_cognition.occam_meta import (
    OccamMetaController, OccamConfig,
)
from laap.agent_core.quantum_cognition.psi_quantum import (
    PsiQuantumCognition, QuantumCognitionConfig, QuantumMode,
)


class TestKalmanSelfModel:
    def test_initialization(self):
        km = KalmanSelfModel()
        assert km.calibrated_confidence == pytest.approx(0.5, abs=0.05)

    def test_predict_step(self):
        km = KalmanSelfModel()
        state = km.predict()
        assert state.shape == (km.cfg.dim_state,)

    def test_predict_update_cycle(self):
        km = KalmanSelfModel()
        obs = np.array([0.8, 0.6, 0.3, 0.1, 0.7, 0.8], dtype=np.float32)
        state = km.observe(obs)
        assert state.shape == (6,)
        # After observing high confidence, state should reflect it
        assert state[IDX_CONFIDENCE] > 0.3

    def test_uncertainty_decreases_with_more_observations(self):
        km = KalmanSelfModel()
        u0 = km.total_uncertainty
        for _ in range(20):
            obs = np.full(6, 0.7, dtype=np.float32)
            km.observe(obs)
        u1 = km.total_uncertainty
        assert u1 < u0  # Uncertainty should decrease

    def test_state_dict(self):
        km = KalmanSelfModel()
        sd = km.state_dict
        assert 'confidence' in sd
        assert 'arousal' in sd

    def test_reset(self):
        km = KalmanSelfModel()
        km.observe(np.full(6, 0.9, dtype=np.float32))
        km.reset()
        assert abs(km.calibrated_confidence - 0.5) < 0.1


class TestSpectralSaliency:
    def test_initialization(self):
        ss = SpectralSaliency()
        assert ss.coherence_score == 0.5

    def test_push_and_analyze(self):
        ss = SpectralSaliency(SpectralSaliencyConfig(window_size=16))
        for _ in range(20):
            features = np.random.randn(3).astype(np.float32) * 0.3 + 0.5
            ss.push(features)
        result = ss.analyze()
        assert 'coherence' in result
        assert 'urgent_score' in result
        assert 'dominant_band' in result
        assert 0 <= result['coherence'] <= 1

    def test_analyze_with_features(self):
        ss = SpectralSaliency(SpectralSaliencyConfig(window_size=8))
        features = np.array([0.5, 0.5, 0.5], dtype=np.float32)
        result = ss.analyze(features)
        assert result is not None

    def test_saliency_vector(self):
        ss = SpectralSaliency()
        sv = ss.saliency_vector
        assert sv.shape == (3,)

    def test_reset(self):
        ss = SpectralSaliency()
        features = np.array([0.5, 0.5, 0.5], dtype=np.float32)
        ss.analyze(features)
        ss.reset()
        assert ss.coherence_score == 0.5
        assert ss.get_debug_info()['buffer_size'] == 0


class TestBayesianIntentionSelector:
    def test_initialization(self):
        bs = BayesianIntentionSelector()
        assert bs.curiosity == pytest.approx(1.0, abs=0.1)

    def test_select_single_intention(self):
        bs = BayesianIntentionSelector()
        intention = Intention(
            id="test", goal="test_goal",
            features=np.zeros(6, dtype=np.float32),
        )
        selected = bs.select([intention])
        assert selected.id == "test"
        assert selected.selected

    def test_select_most_promising(self):
        bs = BayesianIntentionSelector()
        intentions = [
            Intention(id="a", goal="low", features=np.full(6, -1.0, dtype=np.float32),
                      priority=0.3, urgency=0.2),
            Intention(id="b", goal="high", features=np.full(6, 1.0, dtype=np.float32),
                      priority=0.8, urgency=0.7),
        ]
        selected = bs.select(intentions)
        assert selected.id == "b"

    def test_observe_updates_gp(self):
        bs = BayesianIntentionSelector()
        intention = Intention(
            id="test", goal="test",
            features=np.zeros(6, dtype=np.float32),
        )
        n0 = bs.gp_training_size
        bs.select([intention])
        bs.observe(intention, success=True)
        assert bs.gp_training_size >= n0

    def test_curiosity_adapts(self):
        bs = BayesianIntentionSelector(
            BayesianSelectorConfig(curiosity_initial=1.0)
        )
        intention = Intention(
            id="test", goal="test",
            features=np.zeros(6, dtype=np.float32),
        )
        # Simulate many successes — curiosity should decrease
        for _ in range(15):
            bs.observe(intention, success=True)
        assert bs.curiosity < 0.9

    def test_reset(self):
        bs = BayesianIntentionSelector()
        intention = Intention(
            id="test", goal="test",
            features=np.zeros(6, dtype=np.float32),
        )
        for _ in range(10):
            bs.observe(intention, success=True)
        bs.reset()
        assert bs.curiosity == pytest.approx(1.0, abs=0.1)


class TestSchrodingerEvolver:
    def test_initialization(self):
        se = SchrodingerEvolver(SchrodingerConfig(dims=8))
        assert se.psi.dims == 8
        assert abs(se.psi.norm - 1.0) < 1e-6

    def test_step_maintains_norm(self):
        se = SchrodingerEvolver()
        for _ in range(100):
            se.step()
        assert abs(se.psi.norm - 1.0) < 1e-4

    def test_step_with_stimulus(self):
        se = SchrodingerEvolver(SchrodingerConfig(dims=8))
        stimulus = np.array([0.8, 0.0, 0.0, 0.0, 0.0, 0.0, 0.5, 0.0],
                            dtype=np.float32)
        se.step(stimulus=stimulus)
        assert abs(se.psi.norm - 1.0) < 1e-4

    def test_measurement(self):
        se = SchrodingerEvolver(SchrodingerConfig(dims=4))
        idx = se.measure(temperature=0.0)
        assert 0 <= idx < 4

    def test_entropy(self):
        se = SchrodingerEvolver(SchrodingerConfig(dims=4))
        S = se.entropy()
        assert S >= 0

    def most_likely_mode(self):
        se = SchrodingerEvolver()
        mode, prob = se.most_likely_mode()
        assert isinstance(mode, str)
        assert 0 <= prob <= 1

    def test_hamiltonian_property(self):
        se = SchrodingerEvolver(SchrodingerConfig(dims=8))
        H = se.hamiltonian
        assert H.shape == (8, 8)

    def test_ground_state(self):
        se = SchrodingerEvolver()
        gs = se.ground_state
        assert abs(gs.norm - 1.0) < 1e-6

    def test_learn_from_experience(self):
        se = SchrodingerEvolver(SchrodingerConfig(learn_rate=0.01))
        H0 = se.hamiltonian.copy()
        se.learn_from_experience(se.psi, reward=1.0)
        H1 = se.hamiltonian
        # Hamiltonian should have changed
        assert not np.allclose(H0, H1)

    def test_reset(self):
        se = SchrodingerEvolver()
        se.step()
        se.reset()
        assert se.psi.data[0] == pytest.approx(1.0, abs=1e-6)


class TestOccamMetaController:
    def test_initialization(self):
        oc = OccamMetaController()
        assert oc.simplification_count == 0

    def test_audit_skip(self):
        oc = OccamMetaController(OccamConfig(audit_interval=10))
        H = np.eye(4, dtype=np.complex64)
        audit = oc.audit(H)
        # First call should skip (cycle 1 != 10)
        assert not audit.simplified_recommended

    def test_audit_force(self):
        oc = OccamMetaController()
        H = np.eye(4, dtype=np.complex64)
        obs = np.random.randn(10)
        audit = oc.audit(H, observations=obs, force=True)
        assert isinstance(audit.effective_rank, int)

    def test_suggest_simplified_hamiltonian(self):
        oc = OccamMetaController()
        H = np.random.randn(8, 8).astype(np.complex64)
        H = (H + H.conj().T) / 2.0
        Hs = oc.suggest_simplified_hamiltonian(H)
        assert Hs.shape == H.shape

    @staticmethod
    def test_default_model_evidence():
        H = np.eye(4, dtype=np.complex64)
        obs = np.random.randn(10, 4)
        evidence = OccamMetaController._default_model_evidence(H, obs)
        assert np.isfinite(evidence)


class TestPsiQuantumCognition:
    def test_initialization(self):
        pq = PsiQuantumCognition()
        assert pq.state is not None

    def test_perceive(self):
        pq = PsiQuantumCognition()
        result = pq.perceive("Hello, this is a test message")
        assert 'salience' in result
        assert 'coherence' in result

    def test_decide(self):
        pq = PsiQuantumCognition()
        goal, state = pq.decide("What do you think about this?")
        assert isinstance(goal, str)
        assert state == 'act'

    def test_learn(self):
        pq = PsiQuantumCognition()
        pq.decide("test")
        pq.learn("positive outcome", success=True)
        stats = pq.get_stats()
        assert 'confidence' in stats

    def test_rest(self):
        pq = PsiQuantumCognition()
        pq.rest()
        assert pq.state == 'rest'

    def test_get_stats(self):
        pq = PsiQuantumCognition()
        stats = pq.get_stats()
        assert 'cycle' in stats
        assert 'mode' in stats

    def test_get_attention(self):
        pq = PsiQuantumCognition()
        attention = pq.get_attention()
        assert isinstance(attention, str)

    def test_classic_mode(self):
        cfg = QuantumCognitionConfig(mode='classic',
                                     enable_spectral=False,
                                     enable_kalman=False,
                                     enable_schrodinger=False,
                                     enable_bayesian=False,
                                     enable_occam=False)
        pq = PsiQuantumCognition(cfg)
        goal, state = pq.decide("test")
        assert isinstance(goal, str)

    def test_multi_cycle_stability(self):
        pq = PsiQuantumCognition()
        for i in range(20):
            goal, state = pq.decide(f"Message number {i}")
            pq.learn(f"Outcome {i}", success=(i % 2 == 0))
        stats = pq.get_stats()
        assert stats['cycle'] == 20


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
