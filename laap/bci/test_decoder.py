"""Unit tests for the cognitive state decoder."""

from __future__ import annotations

import numpy as np

from laap.bci.decoder import CalibrationProfile, CognitiveStateDecoder, apply_calibration
from laap.bci.primitives import CognitiveState


def _make_features(
    alpha: float = 1.0,
    beta: float = 0.5,
    gamma: float = 0.1,
    theta: float = 0.5,
    frontal_asymmetry: float = 0.0,
    timestamp: float = 0.0,
) -> dict:
    """Build a synthetic feature dict matching ``RealtimeNeuroPipeline`` output."""
    n_channels = 2
    return {
        "timestamp": timestamp,
        "band_powers": {
            "delta": np.full(n_channels, 0.2),
            "theta": np.full(n_channels, theta),
            "alpha": np.full(n_channels, alpha),
            "beta": np.full(n_channels, beta),
            "gamma": np.full(n_channels, gamma),
        },
        "spatial": {
            "frontal_asymmetry": frontal_asymmetry,
            "gfp": 1.0,
        },
        "raw_quality": {
            "per_channel_snr": [10.0, 10.0],
            "overall_snr": 10.0,
        },
    }


def test_decode_high_gamma_low_alpha_is_focused_executive():
    decoder = CognitiveStateDecoder()
    features = _make_features(alpha=1.0, gamma=5.2)
    state = decoder.decode(features)

    assert isinstance(state, CognitiveState)
    assert state.attention_focus == "focused_executive"


def test_decode_high_theta_low_alpha_has_high_cognitive_load():
    decoder = CognitiveStateDecoder()
    features = _make_features(alpha=0.1, theta=10.0)
    state = decoder.decode(features)

    assert isinstance(state, CognitiveState)
    assert state.cognitive_load >= 0.9


def test_decode_right_frontal_alpha_asymmetry_gives_positive_valence():
    decoder = CognitiveStateDecoder()
    # Positive frontal asymmetry (log(R) - log(L) > 0) implies right > left alpha.
    features = _make_features(frontal_asymmetry=0.6)
    state = decoder.decode(features)

    assert isinstance(state, CognitiveState)
    assert state.emotion_vad["valence"] > 0.0


def test_calibration_profile_changes_thresholds():
    decoder = CognitiveStateDecoder()
    original_focused = decoder.attention_focused_executive_threshold
    original_selective = decoder.attention_selective_attention_threshold

    profile = CalibrationProfile(
        attention_focused_executive_threshold=3.5,
        attention_selective_attention_threshold=2.5,
        cognitive_load_offset=0.5,
        cognitive_load_scale=0.4,
    )
    apply_calibration(decoder, profile)

    assert decoder.attention_focused_executive_threshold == 3.5
    assert decoder.attention_selective_attention_threshold == 2.5
    assert decoder.cognitive_load_offset == 0.5
    assert decoder.cognitive_load_scale == 0.4

    # Sanity check: the new thresholds are actually different from defaults.
    assert decoder.attention_focused_executive_threshold != original_focused
    assert decoder.attention_selective_attention_threshold != original_selective


def test_decoder_accepts_dict_calibration_profile():
    decoder = CognitiveStateDecoder(
        calibration_profile={
            "attention_focused_executive_threshold": 4.0,
            "cognitive_load_offset": 0.0,
        }
    )
    assert decoder.attention_focused_executive_threshold == 4.0
    assert decoder.cognitive_load_offset == 0.0


def test_decode_returns_valid_cognitive_state():
    decoder = CognitiveStateDecoder()
    features = _make_features(timestamp=42.0)
    state = decoder.decode(features)

    assert isinstance(state, CognitiveState)
    assert state.attention_focus in {
        "focused_executive",
        "selective_attention",
        "relaxed_diffuse",
        "neutral",
    }
    assert 0.0 <= state.cognitive_load <= 1.0
    assert set(state.emotion_vad.keys()) == {"valence", "arousal", "dominance"}
    assert -1.0 <= state.emotion_vad["valence"] <= 1.0
    assert 0.0 <= state.emotion_vad["arousal"] <= 1.0
    assert state.motor_intent is None
    assert state.timestamp == 42.0
    assert "overall_snr" in state.signal_quality
