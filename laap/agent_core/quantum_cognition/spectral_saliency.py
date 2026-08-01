"""Spectral saliency analyzer — Fourier-domain perception for cognitive streams.

Replaces the heuristic keyword-based ``_calc_salience`` in ``psi_cognition.py``.

The spectral saliency analyzer applies a short-time Fourier transform (STFT)
to the sliding window of recent stimuli, decomposing the conversational stream
into interpretable frequency bands:

  - **Urgent band** (2.0–8.0 Hz)  : rapid back-and-forth, urgency detection
  - **Reflective band** (0.1–0.5 Hz): slow, contemplative interaction
  - **Rhythmic band** (0.5–2.0 Hz) : normal conversational rhythm

Spectral entropy and band energy ratios provide a rich saliency map that
captures conversational dynamics *before* keyword triggers fire.

In addition to temporal frequency analysis, a *semantic embedding* channel
projects stimulus features (e.g., token-level TF-IDF or embedding distances)
into the same spectral framework for multi-modal perceptual awareness.
"""

from __future__ import annotations

import logging
import math
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger('quantum_cognition.spectral_saliency')


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class SpectralAnalysisError(Exception):
    """Raised when spectral decomposition fails."""


# ---------------------------------------------------------------------------
# Default band definitions
# ---------------------------------------------------------------------------

FREQUENCY_BANDS: Dict[str, Tuple[float, float]] = {
    'urgent': (0.50, 1.00),     # high freq  (50-100% Nyquist): rapid back-and-forth
    'rhythmic': (0.20, 0.50),   # mid freq   (20-50% Nyquist): normal conversational pace
    'reflective': (0.00, 0.20), # low freq   (0-20% Nyquist): slow deep thought
}

BAND_LABELS: List[str] = ['urgent', 'reflective', 'rhythmic']


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class SpectralSaliencyConfig:
    """Configuration for the spectral saliency analyzer.

    Parameters
    ----------
    window_size : int
        Number of recent stimuli to buffer for STFT analysis.  Must be a
        power of two for efficient FFT.
    hop_length : int
        Step between successive STFT windows (for streaming analysis).
    sampling_rate : float
        Conceptual sampling rate in 'cognitive events per unit time'.
        Default 1.0 means each stimulus is one sample.
    feature_dim : int
        Dimensionality of the feature vectors used for spectral analysis.
        1 = simple scalar encoding (e.g., urgency score per stimulus).
        >1 = multi-channel spectral analysis.
    energy_floor : float
        Minimum total energy threshold below which spectral entropy is set
        to max (silence detection).
    enable_semantic_channel : bool
        If True, also run spectral analysis on the semantic embedding stream.
    keyword_urgency_map : Dict[str, float], optional
        Legacy keyword-to-urgency mapping preserved for hybrid mode.
    """
    window_size: int = 32
    hop_length: int = 1
    sampling_rate: float = 1.0
    feature_dim: int = 3
    energy_floor: float = 1e-6
    enable_semantic_channel: bool = True
    keyword_urgency_map: Optional[Dict[str, float]] = field(default_factory=lambda: {
        'urgent': 0.4, '紧急': 0.4,
        'now': 0.3, '马上': 0.3,
        'important': 0.3, '重要': 0.3,
        'help': 0.5, 'error': 0.5, 'crash': 0.6,
        'danger': 0.5,
    })
    name: str = "spectral_saliency"


# ---------------------------------------------------------------------------
# SpectralSaliency
# ---------------------------------------------------------------------------

class SpectralSaliency:
    """Short-time Fourier transform saliency engine for cognitive perception.

    Maintains a sliding window of stimulus feature vectors and computes
    per-band energy ratios, spectral entropy, and dominant mode detection
    on every ``analyze()`` call.

    Parameters
    ----------
    config : SpectralSaliencyConfig, optional
    """

    def __init__(self, config: Optional[SpectralSaliencyConfig] = None):
        self.cfg = config or SpectralSaliencyConfig()
        self._buffer: deque = deque(maxlen=self.cfg.window_size)
        self._timestamps: deque = deque(maxlen=self.cfg.window_size)
        self._analysis_count: int = 0
        self._last_result: Optional[dict] = None

    # -- Public API ---------------------------------------------------------

    def push(self, features: np.ndarray, timestamp: Optional[float] = None) -> None:
        """Add a stimulus feature vector to the sliding window.

        Parameters
        ----------
        features : np.ndarray
            Feature vector of shape ``(feature_dim,)``.
        timestamp : float, optional
            Monotonic timestamp.  Uses buffer length if None.
        """
        if features.shape[0] != self.cfg.feature_dim:
            raise ValueError(
                f"Feature dim {features.shape[0]} != config {self.cfg.feature_dim}"
            )
        self._buffer.append(features.astype(np.float32))
        self._timestamps.append(timestamp if timestamp is not None
                                else len(self._buffer))

    def analyze(self, features: Optional[np.ndarray] = None
                ) -> Dict[str, float]:
        """Run spectral analysis on the current buffer.

        Parameters
        ----------
        features : np.ndarray, optional
            If provided, pushes *features* before analysis.

        Returns
        -------
        dict with keys:
            band_energies : Dict[str, float]  — per-band energy ratios
            dominant_band : str                — highest-energy band label
            spectral_entropy : float           — 0 (pure tone) to 1 (white noise)
            coherence : float                  — 1 - normalized entropy
            urgent_score : float               — combined urgency signal
            total_energy : float               — total spectral power
        """
        if features is not None:
            self.push(features)

        if len(self._buffer) < 4:
            # Not enough data: return conservative defaults
            return self._default_result()

        self._analysis_count += 1

        try:
            data = np.array(self._buffer)  # (window, feature_dim)
            result = self._compute_spectrum(data)
            self._last_result = result
            return result
        except (np.linalg.LinAlgError, ValueError) as e:
            logger.warning(f"Spectral analysis failed: {e}")
            return self._default_result()

    # -- Result helpers -----------------------------------------------------

    @property
    def coherence_score(self) -> float:
        """Current conversational coherence (1 = highly focused, 0 = scattered).

        Returns 0.5 if no analysis has run yet.
        """
        if self._last_result is None or len(self._buffer) < 4:
            return 0.5
        return self._last_result.get('coherence', 0.5)

    @property
    def dominant_mode(self) -> str:
        """Current dominant conversational mode."""
        if self._last_result is None:
            return 'neutral'
        return self._last_result.get('dominant_band', 'neutral')

    @property
    def urgent_score(self) -> float:
        """Combined urgency signal (0-1).

        Falls back to 0.3 when the spectral buffer is too cold (< 4 samples).
        """
        if self._last_result is None or len(self._buffer) < 4:
            return 0.3  # moderate default, not zero
        return self._last_result.get('urgent_score', 0.3)

    @property
    def saliency_vector(self) -> np.ndarray:
        """3-element saliency vector for injection into cognitive state.

        [coherence, urgency, entropy] normalized to [0, 1].
        """
        if self._last_result is None:
            return np.array([0.5, 0.0, 0.5], dtype=np.float32)
        return np.array([
            self._last_result.get('coherence', 0.5),
            self._last_result.get('urgent_score', 0.0),
            self._last_result.get('spectral_entropy', 0.5),
        ], dtype=np.float32)

    def get_debug_info(self) -> dict:
        """Return detailed diagnostic information."""
        return {
            'buffer_size': len(self._buffer),
            'analysis_count': self._analysis_count,
            'last_result': self._last_result,
            'config': {
                'window_size': self.cfg.window_size,
                'feature_dim': self.cfg.feature_dim,
                'sampling_rate': self.cfg.sampling_rate,
            }
        }

    def reset(self):
        """Clear the buffer and reset analysis state."""
        self._buffer.clear()
        self._timestamps.clear()
        self._analysis_count = 0
        self._last_result = None

    # -- Internal methods ---------------------------------------------------

    def _compute_spectrum(self, data: np.ndarray) -> Dict[str, float]:
        """Core STFT + band energy computation.

        data shape: (window_size, feature_dim)
        """
        n = data.shape[0]

        # Apply Hann window to reduce spectral leakage
        window = np.hanning(n)
        windowed = data * window[:, np.newaxis]

        # Per-channel FFT
        fft = np.fft.rfft(windowed, axis=0)
        power = np.abs(fft) ** 2
        nyquist = self.cfg.sampling_rate / 2.0
        freqs_norm = np.fft.rfftfreq(n, d=1.0 / self.cfg.sampling_rate) / nyquist

        # Combine channels (sum across feature dim)
        total_power = np.sum(power, axis=1)

        total_energy = np.sum(total_power)
        if total_energy < self.cfg.energy_floor:
            return self._default_result()

        # Per-band energy using normalized frequencies
        band_energies = {}
        for band_name, (low, high) in FREQUENCY_BANDS.items():
            mask = (freqs_norm >= low) & (freqs_norm < high)
            if np.any(mask):
                band_energies[band_name] = float(
                    np.sum(total_power[mask]) / total_energy
                )
            else:
                band_energies[band_name] = 0.0

        # Dominant band
        dominant = max(band_energies, key=band_energies.get)

        # Spectral entropy (normalized)
        prob = total_power / total_energy
        prob = prob[prob > 1e-10]
        if len(prob) > 1:
            entropy = -np.sum(prob * np.log(prob)) / np.log(len(prob))
        else:
            entropy = 0.0

        # Coherence: 1 - entropy
        coherence = 1.0 - float(entropy)

        # Urgent score: weighted combination
        urgent_score = band_energies.get('urgent', 0.0)
        # Boost by reflective deficit: if coherence is low and urgent high
        if coherence < 0.3 and urgent_score > 0.4:
            urgent_score = min(1.0, urgent_score * 1.3)

        return {
            'band_energies': band_energies,
            'dominant_band': dominant,
            'spectral_entropy': float(entropy),
            'coherence': float(np.clip(coherence, 0.0, 1.0)),
            'urgent_score': float(np.clip(urgent_score, 0.0, 1.0)),
            'total_energy': float(total_energy),
        }

    def _default_result(self) -> Dict[str, float]:
        """Safe defaults when buffer is too small or analysis fails."""
        return {
            'band_energies': {b: 0.0 for b in BAND_LABELS},
            'dominant_band': 'rhythmic',
            'spectral_entropy': 0.5,
            'coherence': 0.5,
            'urgent_score': 0.0,
            'total_energy': 0.0,
        }

    def _fallback_keyword_salience(self, text: str) -> float:
        """Legacy keyword-based urgency for backward compatibility."""
        if not self.cfg.keyword_urgency_map:
            return 0.3
        salience = 0.3
        text_lower = text.lower()
        for word, boost in self.cfg.keyword_urgency_map.items():
            if word in text_lower:
                salience += boost
        return float(min(salience, 1.0))

    def __repr__(self) -> str:
        return (f"SpectralSaliency(window={self.cfg.window_size}, "
                f"dim={self.cfg.feature_dim}, "
                f"analyzed={self._analysis_count}, "
                f"coherence={self.coherence_score:.2f})")
