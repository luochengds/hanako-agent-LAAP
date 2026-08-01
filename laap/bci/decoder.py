"""Cognitive state decoder for the BCI Neuro Bridge.

The decoder translates spectral features produced by ``RealtimeNeuroPipeline``
into a higher-level ``CognitiveState``. All heavy numerical work is delegated to
``numpy``; this module does not depend on hardware drivers.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

import numpy as np

from laap.bci.primitives import CognitiveState

logger = logging.getLogger("laap.bci")


@dataclass
class CalibrationProfile:
    """Per-user calibration thresholds for the cognitive state decoder.

    Default values are suitable for a typical adult EEG recording. Each field
    can be overridden independently via a calibration session.
    """

    attention_focused_executive_threshold: float = 2.5
    attention_selective_attention_threshold: float = 1.5
    cognitive_load_offset: float = 1.0
    cognitive_load_scale: float = 0.5


def apply_calibration(decoder: "CognitiveStateDecoder", profile: CalibrationProfile) -> None:
    """Update ``decoder`` thresholds using ``profile``."""
    decoder.attention_focused_executive_threshold = profile.attention_focused_executive_threshold
    decoder.attention_selective_attention_threshold = profile.attention_selective_attention_threshold
    decoder.cognitive_load_offset = profile.cognitive_load_offset
    decoder.cognitive_load_scale = profile.cognitive_load_scale


class CognitiveStateDecoder:
    """Decode spectral EEG features into a cognitive state representation."""

    def __init__(self, sfreq: float = 250.0, calibration_profile: Optional[Dict] = None):
        self.sfreq = float(sfreq)

        # Default thresholds; may be overridden by calibration.
        self.attention_focused_executive_threshold = 2.5
        self.attention_selective_attention_threshold = 1.5
        self.cognitive_load_offset = 1.0
        self.cognitive_load_scale = 0.5

        if calibration_profile is not None:
            self._apply_profile(calibration_profile)

    def _apply_profile(self, profile: Dict) -> None:
        """Apply a dictionary-style calibration profile if provided."""
        if isinstance(profile, CalibrationProfile):
            apply_calibration(self, profile)
            return

        self.attention_focused_executive_threshold = float(
            profile.get("attention_focused_executive_threshold", self.attention_focused_executive_threshold)
        )
        self.attention_selective_attention_threshold = float(
            profile.get("attention_selective_attention_threshold", self.attention_selective_attention_threshold)
        )
        self.cognitive_load_offset = float(profile.get("cognitive_load_offset", self.cognitive_load_offset))
        self.cognitive_load_scale = float(profile.get("cognitive_load_scale", self.cognitive_load_scale))

    def decode(self, features: Dict) -> CognitiveState:
        """Decode a feature dictionary into a ``CognitiveState``.

        ``features`` must match the output of ``RealtimeNeuroPipeline.process_window``:
        keys ``band_powers``, ``spatial``, ``raw_quality``, and ``timestamp``.
        """
        band_powers = features.get("band_powers", {})
        spatial = features.get("spatial", {})
        raw_quality = features.get("raw_quality", {})
        timestamp = float(features.get("timestamp", 0.0))

        alpha = self._mean_band_power(band_powers, "alpha")
        beta = self._mean_band_power(band_powers, "beta")
        gamma = self._mean_band_power(band_powers, "gamma")
        theta = self._mean_band_power(band_powers, "theta")

        attention_focus = self._decode_attention(gamma, alpha, beta)
        cognitive_load = self._decode_cognitive_load(theta, alpha)
        emotion_vad = self._decode_emotion(spatial, beta, alpha)

        return CognitiveState(
            attention_focus=attention_focus,
            cognitive_load=cognitive_load,
            emotion_vad=emotion_vad,
            motor_intent=None,
            signal_quality=raw_quality,
            timestamp=timestamp,
        )

    @staticmethod
    def _mean_band_power(band_powers: Dict, band: str) -> float:
        """Return the mean power for ``band`` or 0.0 when missing."""
        power = band_powers.get(band)
        if power is None:
            return 0.0
        return float(np.mean(np.asarray(power, dtype=np.float64)))

    def _decode_attention(self, gamma: float, alpha: float, beta: float) -> str:
        """Decode attention focus from gamma/alpha and alpha/beta ratios."""
        eps = 1e-10
        gamma_alpha_ratio = gamma / (alpha + eps)

        if gamma_alpha_ratio > self.attention_focused_executive_threshold:
            return "focused_executive"
        if gamma_alpha_ratio > self.attention_selective_attention_threshold:
            return "selective_attention"
        if alpha > beta:
            return "relaxed_diffuse"
        return "neutral"

    def _decode_cognitive_load(self, theta: float, alpha: float) -> float:
        """Decode cognitive load from theta/alpha ratio using a sigmoid-like map."""
        eps = 1e-10
        ratio = theta / (alpha + eps)
        load = np.tanh(ratio - self.cognitive_load_offset) * self.cognitive_load_scale + 0.5
        return float(np.clip(load, 0.0, 1.0))

    @staticmethod
    def _decode_emotion(spatial: Dict, beta: float, alpha: float) -> Dict[str, float]:
        """Decode a VAD emotion vector from frontal asymmetry and beta/alpha ratio."""
        eps = 1e-10
        frontal_asymmetry = float(spatial.get("frontal_asymmetry", 0.0))

        valence = float(np.clip(frontal_asymmetry * 2.0, -1.0, 1.0))
        arousal = float(np.clip((beta / (alpha + eps)) / 3.0, 0.0, 1.0))
        dominance = 0.5

        return {"valence": valence, "arousal": arousal, "dominance": dominance}
