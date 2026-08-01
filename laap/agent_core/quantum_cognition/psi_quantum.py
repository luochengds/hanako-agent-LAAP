"""PsiQuantumCognition — unified quantum cognitive cycle.

This is the capstone class that integrates all five theoretical components
into a single cognitive engine, with an interface compatible with the
existing ``PSICognition`` class in ``psi_cognition.py``.

Architecture (one consciousness frame):

    1. [Fourier]   SpectralSaliency.analyze() → spectrum
    2. [Kalman]    KalmanSelfModel.predict() → prior
    3. [Schrodinger] SchrodingerEvolver.step() → |psi⟩
    4. [Bayesian]  BayesianIntentionSelector.select() → intention
    5. [Kalman]    KalmanSelfModel.update(obs) → posterior
    6. [Occam]     (periodic) OccamMetaController.audit() → simplification

The engine supports three operational modes:
  - ``pure_quantum`` : full quantum cognitive cycle (default)
  - ``hybrid``       : quantum dynamics + classical intention scoring (fallback)
  - ``classic``      : original PSI heuristic (no quantum components)
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from .kalman_self import (
    KalmanSelfModel,
    KalmanConfig,
    STATE_LABELS,
    IDX_CONFIDENCE,
    IDX_AROUSAL,
    IDX_VALENCE,
    IDX_FATIGUE,
    IDX_ATTENTION,
    IDX_COHERENCE,
)
from .spectral_saliency import (
    SpectralSaliency,
    SpectralSaliencyConfig,
)
from .bayesian_selector import (
    BayesianIntentionSelector,
    BayesianSelectorConfig,
    Intention,
)
from .occam_meta import (
    OccamMetaController,
    OccamConfig,
    ComplexityAuditRecord,
)
from .schrodinger import (
    SchrodingerEvolver,
    SchrodingerConfig,
)
from .base import CognitiveKet, BornRule

logger = logging.getLogger('quantum_cognition.psi_quantum')


# ---------------------------------------------------------------------------
# Operational modes
# ---------------------------------------------------------------------------

class QuantumMode(str, Enum):
    """Operational mode for the quantum cognitive engine."""
    PURE_QUANTUM = "pure_quantum"
    HYBRID = "hybrid"
    CLASSIC = "classic"


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class QuantumCognitionConfig:
    """Top-level configuration for PsiQuantumCognition.

    Parameters
    ----------
    dim_state : int
        Dimensionality of the consciousness Hilbert space.
    mode : str or QuantumMode
        Operational mode.
    dt : float
        Cognitive time step.
    curiosity_initial : float
        Initial curiosity coefficient for Bayesian exploration.
    audit_interval : int
        How many cycles between Occam audits.
    enable_spectral : bool
        Enable spectral saliency analysis.
    enable_kalman : bool
        Enable Kalman self-model.
    enable_schrodinger : bool
        Enable Schrodinger state evolution.
    enable_bayesian : bool
        Enable Bayesian intention selection.
    enable_occam : bool
        Enable Occam meta-controller.
    verbose_logging : bool
        If True, log every cognitive cycle.
    name : str
        Human-readable identifier.
    """
    dim_state: int = 8
    mode: str = "pure_quantum"
    dt: float = 0.025
    curiosity_initial: float = 1.0
    audit_interval: int = 10
    enable_spectral: bool = True
    enable_kalman: bool = True
    enable_schrodinger: bool = True
    enable_bayesian: bool = True
    enable_occam: bool = True
    verbose_logging: bool = False
    name: str = "psi_quantum"


# ---------------------------------------------------------------------------
# PsiQuantumCognition
# ---------------------------------------------------------------------------

class PsiQuantumCognition:
    """Unified quantum cognitive engine.

    Can be used as a drop-in replacement for ``PSICognition`` with the same
    ``decide()``, ``perceive()``, ``learn()``, ``rest()``, and ``get_stats()``
    interface.

    Parameters
    ----------
    config : QuantumCognitionConfig, optional
    """

    def __init__(self, config: Optional[QuantumCognitionConfig] = None):
        self.cfg = config or QuantumCognitionConfig()
        self._mode = QuantumMode(self.cfg.mode)
        self._cycle_count: int = 0
        self._start_time: float = time.time()
        self._current_stimulus: str = ""

        # Sub-component initialization
        self._init_components()

        # Compatibility with PSICognition state enum
        self.state = "idle"

        logger.info(
            f"[psi_q] initialized mode={self._mode.value}, "
            f"dim={self.cfg.dim_state}, "
            f"components: spectral={self.cfg.enable_spectral}, "
            f"kalman={self.cfg.enable_kalman}, "
            f"schrodinger={self.cfg.enable_schrodinger}, "
            f"bayesian={self.cfg.enable_bayesian}, "
            f"occam={self.cfg.enable_occam}"
        )

    def _init_components(self):
        """Initialize all sub-components based on config."""
        dim = self.cfg.dim_state

        # Spectral saliency
        if self.cfg.enable_spectral:
            self.spectral = SpectralSaliency(
                SpectralSaliencyConfig(feature_dim=3)
            )
        else:
            self.spectral = None

        # Kalman self-model
        if self.cfg.enable_kalman:
            kc = KalmanConfig(dim_state=6)
            self.kalman = KalmanSelfModel(kc)
        else:
            self.kalman = None

        # Schrodinger evolver
        if self.cfg.enable_schrodinger:
            sc = SchrodingerConfig(
                dims=dim,
                dt=self.cfg.dt,
                coupling_strength=0.15,
            )
            self.schrodinger = SchrodingerEvolver(sc)
        else:
            self.schrodinger = None

        # Bayesian intention selector
        if self.cfg.enable_bayesian:
            bc = BayesianSelectorConfig(
                feature_dim=6,
                curiosity_initial=self.cfg.curiosity_initial,
            )
            self.bayesian = BayesianIntentionSelector(bc)
        else:
            self.bayesian = None

        # Occam meta-controller
        if self.cfg.enable_occam:
            oc = OccamConfig(audit_interval=self.cfg.audit_interval)
            self.occam = OccamMetaController(oc)
        else:
            self.occam = None

        # Born rule utility
        self._born = BornRule()

    # -- PSICognition compatible API ----------------------------------------

    def perceive(self, stimulus: str, modality: str = "text") -> dict:
        """Perception step: analyze stimulus through spectral + quantum lens.

        Parameters
        ----------
        stimulus : str
            Raw input text.
        modality : str, optional
            Input modality (default 'text').

        Returns
        -------
        dict
            Perception result including saliency features.
        """
        self.state = "perceive"
        self._current_stimulus = stimulus

        result = {
            'stimulus': stimulus[:100],
            'modality': modality,
            'timestamp': time.time(),
            'salience': 0.3,  # fallback
        }

        # Spectral analysis
        if self.spectral is not None:
            features = self._extract_spectral_features(stimulus)
            self.spectral.push(features)
            analysis = self.spectral.analyze()
            result['coherence'] = analysis.get('coherence', 0.5)
            result['urgent_score'] = analysis.get('urgent_score', 0.0)
            result['dominant_band'] = analysis.get('dominant_band', 'rhythmic')
            result['spectral_entropy'] = analysis.get('spectral_entropy', 0.5)
            result['salience'] = max(
                result.get('salience', 0.3),
                analysis.get('urgent_score', 0.0)
            )

        # Build spectral stimulus vector for Schrodinger
        spectral_vec = self._build_stimulus_vector(stimulus, result)

        # Feed into Schrodinger
        if self.schrodinger is not None:
            try:
                self.schrodinger.step(stimulus=spectral_vec)
            except Exception as e:
                logger.warning(f"Schrodinger step failed: {e}")

        if self.cfg.verbose_logging:
            logger.debug(
                f"[psi_q] perceive: "
                f"coherence={result.get('coherence', 'N/A'):.2f}, "
                f"urgent={result.get('urgent_score', 'N/A'):.2f}"
            )

        return result

    def decide(self, stimulus: str) -> Tuple[str, str]:
        """Full quantum cognitive cycle: perceive → select → integrate → act.

        Parameters
        ----------
        stimulus : str
            Input to process.

        Returns
        -------
        (str, str)
            (goal, state_label)  — selected intention goal and final state.
        """
        self._cycle_count += 1

        # 1. Perceive (Fourier + Schrodinger stimulus)
        perception = self.perceive(stimulus)

        # 2. Kalman predict (self-model prior)
        if self.kalman is not None:
            self.kalman.predict()

        # 3. Integrate (Schrodinger does this internally via evolution)
        if self.schrodinger is not None:
            try:
                self.schrodinger.step()
            except Exception as e:
                logger.warning(f"Schrodinger integrate step failed: {e}")

        # 4. Select intention (Bayesian optimization)
        intention = self._select_intention(perception)
        goal = intention.goal if intention is not None else "unknown"

        # 5. Act
        self.state = "act"

        # 6. (Periodic) Occam audit
        if self.occam is not None and self.schrodinger is not None:
            audit = self.occam.audit(
                self.schrodinger.hamiltonian,
                observations=np.array([perception.get('coherence', 0.5)]),
            )
            if audit.simplified_recommended:
                self._apply_simplification(audit)

        # 7. Kalman update (self-model posterior from observation)
        if self.kalman is not None:
            obs = self._build_kalman_observation(perception)
            self.kalman.update(obs)

        if self.cfg.verbose_logging:
            logger.debug(
                f"[psi_q] decide cycle={self._cycle_count}: "
                f"goal='{goal[:30]}'"
            )

        return goal, self.state

    def learn(self, outcome: str, success: bool):
        """Learning step: update Bayesian GP and Schrodinger Hamiltonian.

        Parameters
        ----------
        outcome : str
            Description of the outcome.
        success : bool
            Whether the outcome was positive.
        """
        self.state = "learn"

        # Update Bayesian selector
        if self.bayesian is not None and self._last_intention is not None:
            reward = 1.0 if success else 0.0
            self.bayesian.observe(self._last_intention, success, reward)

        # Update Schrodinger Hamiltonian (Hebbian reinforcement)
        if self.schrodinger is not None:
            try:
                outcome_state = self.schrodinger.psi
                reward_val = 1.0 if success else -0.3
                self.schrodinger.learn_from_experience(outcome_state, reward_val)
            except Exception as e:
                logger.warning(f"Hamiltonian learning failed: {e}")

        if self.cfg.verbose_logging:
            logger.debug(
                f"[psi_q] learn: outcome='{outcome[:30]}', "
                f"success={success}"
            )

    def rest(self):
        """Cognitive reset: allow state to drift toward ground state."""
        self.state = "rest"
        if self.schrodinger is not None:
            dr = self.schrodinger.cfg.dt
            num_steps = 10
            for _ in range(num_steps):
                try:
                    self.schrodinger.step()
                except Exception:
                    break

    # -- State queries ------------------------------------------------------

    def get_stats(self) -> dict:
        """Return statistics compatible with PSICognition interface."""
        stats = {
            'state': self.state,
            'cycle': self._cycle_count,
            'mode': self._mode.value,
        }

        if self.kalman is not None:
            sd = self.kalman.state_dict
            stats.update({
                'confidence': sd.get('confidence', 0.5),
                'arousal': sd.get('arousal', 0.5),
                'coherence': sd.get('coherence', 0.5),
                'uncertainty': self.kalman.total_uncertainty,
            })

        if self.schrodinger is not None:
            info = self.schrodinger.get_debug_info()
            stats.update({
                'quantum_entropy': info['entropy'],
                'quantum_energy': info['energy'],
                'most_likely_mode': info['most_likely_mode'],
                'mode_prob': info['mode_probability'],
            })

        if self.bayesian is not None:
            stats.update({
                'curiosity': self.bayesian.curiosity,
                'success_rate': self.bayesian.success_rate,
            })

        if self.spectral is not None:
            stats.update({
                'spectral_coherence': self.spectral.coherence_score,
                'urgent_score': self.spectral.urgent_score,
                'salience': self.spectral.urgent_score,
            })

        return stats

    def get_attention(self) -> str:
        """Current attention focus as a string."""
        if self.schrodinger is not None:
            mode, prob = self.schrodinger.most_likely_mode()
            return f"{mode} ({prob:.0%})"
        return "unknown"

    # -- Internal methods ---------------------------------------------------

    def _extract_spectral_features(self, stimulus: str) -> np.ndarray:
        """Convert text stimulus into a 3D spectral feature vector.

        Features: [keyword_urgency, length_signal, novelty_signal]
        """
        text_lower = stimulus.lower()

        # Feature 0: keyword urgency (0-1)
        urgency = 0.0
        for word, boost in [
            ('urgent', 0.4), ('紧急', 0.4), ('now', 0.3), ('马上', 0.3),
            ('help', 0.5), ('danger', 0.5), ('error', 0.5), ('crash', 0.6),
            ('important', 0.3), ('重要', 0.3),
        ]:
            if word in text_lower:
                urgency = max(urgency, boost)

        # Feature 1: length signal (normalized)
        length = np.clip(len(stimulus) / 500, 0, 1)

        # Feature 2: novelty — simple hash-based (placeholder)
        novelty = float(len(set(stimulus.split())) / max(len(stimulus.split()), 1))

        return np.array([urgency, length, novelty], dtype=np.float32)

    def _build_stimulus_vector(self, stimulus: str,
                                perception: dict) -> np.ndarray:
        """Build a stimulus vector for the Schrodinger Hamiltonian perturbation.

        Each dimension of the vector maps to a cognitive mode, encoding
        how strongly this stimulus excites each mode.
        """
        dim = self.cfg.dim_state
        vec = np.zeros(dim, dtype=np.float32)

        # Mode 0 (perceive): always excited by new stimulus
        vec[0] = 0.8
        # Mode 6 (attention): excited by coherence/urgency
        coherence = perception.get('coherence', 0.5)
        urgent = perception.get('urgent_score', 0.0)
        if dim > 6:
            vec[6] = 0.5 + coherence * 0.3
        # Mode 7 (emotion): excited by urgency
        if dim > 7:
            vec[7] = urgent * 0.6
        # Mode 8 (meta): excited by low coherence (unexpected input)
        if dim > 8:
            vec[8] = (1.0 - coherence) * 0.4

        return vec

    def _build_kalman_observation(self, perception: dict) -> np.ndarray:
        """Build a 6D Kalman observation from spectral perception."""
        obs = np.zeros(6, dtype=np.float32)
        obs[IDX_CONFIDENCE] = 0.5 + perception.get('coherence', 0.5) * 0.3
        obs[IDX_AROUSAL] = 0.3 + perception.get('urgent_score', 0.0) * 0.5
        obs[IDX_VALENCE] = 0.5 - perception.get('urgent_score', 0.0) * 0.3
        obs[IDX_FATIGUE] = 0.2
        obs[IDX_ATTENTION] = perception.get('coherence', 0.5)
        obs[IDX_COHERENCE] = perception.get('coherence', 0.5)
        return obs

    def _select_intention(self, perception: dict) -> Optional[Intention]:
        """Build and select an intention using the Bayesian selector.

        Falls back to heuristic scoring in classic/hybrid mode.
        """
        intention = self._build_default_intention(perception)

        if self.bayesian is not None and self._mode != QuantumMode.CLASSIC:
            try:
                selected = self.bayesian.select([intention])
                self._last_intention = selected
                return selected
            except Exception as e:
                logger.warning(f"Bayesian selection failed: {e}")

        # Fallback: heuristic
        intention.selected = True
        intention.efe_score = intention.priority * 0.6 + intention.urgency * 0.4
        self._last_intention = intention
        return intention

    def _build_default_intention(self, perception: dict) -> Intention:
        """Construct a default Intention from perception."""
        coherence = perception.get('coherence', 0.5)
        urgent = perception.get('urgent_score', 0.0)

        # Determine goal from perception
        if urgent > 0.5:
            goal = "respond_urgent"
            priority = 0.9
            urgency = 0.8
        elif coherence < 0.3:
            goal = "seek_clarification"
            priority = 0.6
            urgency = 0.5
        else:
            goal = "continue_discussion"
            priority = 0.5
            urgency = 0.3

        # Build feature vector from state
        features = np.zeros(self.cfg.dim_state + 2, dtype=np.float32)
        features[0] = priority
        features[1] = urgency
        features[2] = coherence
        features[3] = 1.0 - coherence  # uncertainty
        features[4] = time.time() % 100 / 100  # temporal context
        features[5] = self._cycle_count / max(self._cycle_count, 1) % 1

        return Intention(
            id=f"int_{uuid.uuid4().hex[:8]}",
            goal=goal,
            features=features[:6],
            priority=priority,
            urgency=urgency,
        )

    def _apply_simplification(self, audit: ComplexityAuditRecord):
        """Apply Occam-recommended simplification to the Hamiltonian."""
        if self.schrodinger is not None and audit.simplified_recommended:
            simplified = self.occam.suggest_simplified_hamiltonian(
                self.schrodinger.hamiltonian
            )
            new_op = type(self.schrodinger)._CognitiveOperator__(simplified)
            # Rebuild with simplified Hamiltonian
            self.schrodinger._hamiltonian = self.schrodinger._CognitiveOperator__(
                simplified
            )
            self.schrodinger._rebuild_cn()
            logger.info(
                f"[psi_q] simplification applied: "
                f"rank reduced via Occam audit"
            )

    # -- Debug & introspection ----------------------------------------------

    def get_debug_report(self) -> dict:
        """Full diagnostic report of all sub-components."""
        return {
            'config': {
                'mode': self._mode.value,
                'dim_state': self.cfg.dim_state,
                'cycle': self._cycle_count,
                'uptime': time.time() - self._start_time,
            },
            'kalman': repr(self.kalman) if self.kalman else 'disabled',
            'spectral': repr(self.spectral) if self.spectral else 'disabled',
            'schrodinger': repr(self.schrodinger) if self.schrodinger else 'disabled',
            'bayesian': repr(self.bayesian) if self.bayesian else 'disabled',
            'occam': repr(self.occam) if self.occam else 'disabled',
            'stats': self.get_stats(),
        }

    def __repr__(self) -> str:
        return (
            f"PsiQuantumCognition(mode={self._mode.value}, "
            f"cycles={self._cycle_count})"
        )
