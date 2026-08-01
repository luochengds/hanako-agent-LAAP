"""Unit tests for the real-time EEG processing pipeline."""

from __future__ import annotations

import numpy as np
import pytest

from laap.bci.pipeline import RealtimeNeuroPipeline
from laap.bci.primitives import NeuroDataFrame

SFREQ = 250.0
N_CHANNELS = 16
N_SAMPLES = int(SFREQ)


def _frame(eeg: np.ndarray, timestamp: float = 0.0) -> NeuroDataFrame:
    return NeuroDataFrame(timestamp=timestamp, eeg=eeg)


def test_process_window_returns_expected_keys_and_shape():
    pipeline = RealtimeNeuroPipeline(sfreq=SFREQ, n_channels=N_CHANNELS)
    rng = np.random.default_rng(42)
    eeg = rng.normal(size=(N_CHANNELS, N_SAMPLES))

    result = pipeline.process_window(_frame(eeg))

    assert result["timestamp"] == 0.0
    assert set(result["band_powers"].keys()) == {"delta", "theta", "alpha", "beta", "gamma"}
    for band, powers in result["band_powers"].items():
        assert len(powers) == N_CHANNELS, f"band {band} should have {N_CHANNELS} channel powers"

    assert "frontal_asymmetry" in result["spatial"]
    assert "gfp" in result["spatial"]

    quality = result["raw_quality"]
    assert "per_channel_snr" in quality
    assert "overall_snr" in quality
    assert len(quality["per_channel_snr"]) == N_CHANNELS
    assert quality["overall_snr"] > 0


def test_alpha_signal_has_higher_alpha_power():
    pipeline = RealtimeNeuroPipeline(sfreq=SFREQ, n_channels=N_CHANNELS)
    t = np.arange(N_SAMPLES) / SFREQ
    eeg = 1.0 * np.sin(2.0 * np.pi * 10.0 * t)
    eeg = np.broadcast_to(eeg, (N_CHANNELS, N_SAMPLES)).copy()
    eeg += 0.05 * np.random.default_rng(7).normal(size=eeg.shape)

    result = pipeline.process_window(_frame(eeg))
    bp = result["band_powers"]
    alpha_mean = float(np.mean(bp["alpha"]))

    assert alpha_mean > np.mean(bp["beta"])
    assert alpha_mean > np.mean(bp["gamma"])


def test_gamma_signal_has_higher_gamma_power():
    pipeline = RealtimeNeuroPipeline(sfreq=SFREQ, n_channels=N_CHANNELS)
    t = np.arange(N_SAMPLES) / SFREQ
    eeg = 1.0 * np.sin(2.0 * np.pi * 40.0 * t)
    eeg = np.broadcast_to(eeg, (N_CHANNELS, N_SAMPLES)).copy()
    eeg += 0.05 * np.random.default_rng(8).normal(size=eeg.shape)

    result = pipeline.process_window(_frame(eeg))
    bp = result["band_powers"]
    gamma_mean = float(np.mean(bp["gamma"]))

    for band in ("delta", "theta", "alpha", "beta"):
        assert gamma_mean > np.mean(bp[band]), f"gamma should exceed {band}"


def test_signal_quality_is_positive():
    pipeline = RealtimeNeuroPipeline(sfreq=SFREQ, n_channels=N_CHANNELS)
    t = np.arange(N_SAMPLES) / SFREQ
    eeg = 0.5 * np.sin(2.0 * np.pi * 10.0 * t)
    eeg = np.broadcast_to(eeg, (N_CHANNELS, N_SAMPLES)).copy()
    eeg += 0.05 * np.random.default_rng(9).normal(size=eeg.shape)

    result = pipeline.process_window(_frame(eeg))
    quality = result["raw_quality"]

    assert quality["overall_snr"] > 1.0
    assert all(snr > 0.0 for snr in quality["per_channel_snr"])


def test_frontal_asymmetry_sign_flips():
    pipeline = RealtimeNeuroPipeline(
        sfreq=SFREQ,
        n_channels=2,
        frontal_channels={"F3": 0, "F4": 1},
    )
    t = np.arange(N_SAMPLES) / SFREQ

    left_dominant = np.zeros((2, N_SAMPLES))
    left_dominant[0, :] = 2.0 * np.sin(2.0 * np.pi * 10.0 * t)  # F3 strong
    left_dominant[1, :] = 0.2 * np.sin(2.0 * np.pi * 10.0 * t)  # F4 weak

    right_dominant = np.zeros((2, N_SAMPLES))
    right_dominant[0, :] = 0.2 * np.sin(2.0 * np.pi * 10.0 * t)  # F3 weak
    right_dominant[1, :] = 2.0 * np.sin(2.0 * np.pi * 10.0 * t)  # F4 strong

    asym_left = pipeline.process_window(_frame(left_dominant))["spatial"]["frontal_asymmetry"]
    asym_right = pipeline.process_window(_frame(right_dominant))["spatial"]["frontal_asymmetry"]

    assert asym_left < 0.0, "left-dominant alpha should produce negative asymmetry"
    assert asym_right > 0.0, "right-dominant alpha should produce positive asymmetry"
