"""Real-time EEG signal processing pipeline.

The pipeline keeps imports of optional numerical/signal libraries at the top
because ``scipy`` is a declared project dependency, but it still degrades
gracefully with warnings if the environment is missing it.
"""

from __future__ import annotations

import logging
from typing import Dict, Optional

import numpy as np

try:
    from scipy import signal

    _HAS_SCIPY = True
except Exception:  # pragma: no cover - defensive import
    _HAS_SCIPY = False
    signal = None  # type: ignore[assignment]

from laap.bci.primitives import NeuroDataFrame

logger = logging.getLogger("laap.bci")

# Standard EEG filter bank used by the real-time pipeline.
BANDS = {
    "delta": (0.5, 4.0),
    "theta": (4.0, 8.0),
    "alpha": (8.0, 13.0),
    "beta": (13.0, 30.0),
    "gamma": (30.0, 100.0),
}

_DEFAULT_FRONTAL_CHANNELS = {"F3": 0, "F4": 1}


def _notch_filter(data: np.ndarray, sfreq: float, freq: float, quality: int = 30) -> np.ndarray:
    """Apply a second-order IIR notch filter to a (channels, samples) array."""
    data = np.asarray(data, dtype=np.float64)
    if not _HAS_SCIPY:
        logger.warning("scipy unavailable; skipping notch filter at %.1f Hz", freq)
        return data

    b, a = signal.iirnotch(freq, quality, sfreq)
    return signal.filtfilt(b, a, data, axis=1)


def _bandpass_filter(
    data: np.ndarray,
    sfreq: float,
    low: float,
    high: float,
    order: int = 4,
) -> np.ndarray:
    """Apply a zero-phase Butterworth bandpass filter."""
    data = np.asarray(data, dtype=np.float64)
    if not _HAS_SCIPY:
        logger.warning("scipy unavailable; skipping bandpass filter %.1f-%.1f Hz", low, high)
        return data

    nyq = sfreq / 2.0
    low_norm = low / nyq
    high_norm = high / nyq
    sos = signal.butter(order, [low_norm, high_norm], btype="bandpass", output="sos")
    return signal.sosfiltfilt(sos, data, axis=1)


def _band_power(data: np.ndarray, sfreq: float, low: float, high: float) -> np.ndarray:
    """Return per-channel power estimate inside a frequency band.

    Uses Welch's method when scipy is available and the window is long enough;
    otherwise falls back to an FFT magnitude estimate so the pipeline can still
    run in a minimal environment.
    """
    data = np.asarray(data, dtype=np.float64)
    n_channels, n_samples = data.shape
    if n_samples == 0:
        return np.zeros(n_channels)

    if _HAS_SCIPY and n_samples >= 16:
        nperseg = min(256, n_samples)
        freqs, psd = signal.welch(data, fs=sfreq, nperseg=nperseg, axis=1)
    else:
        freqs = np.fft.rfftfreq(n_samples, d=1.0 / sfreq)
        psd = np.abs(np.fft.rfft(data, axis=1)) ** 2

    mask = (freqs >= low) & (freqs < high)
    if not np.any(mask):
        return np.zeros(n_channels)

    return np.mean(psd[:, mask], axis=1)


class RealtimeNeuroPipeline:
    """Real-time EEG signal processing pipeline for one window at a time."""

    def __init__(
        self,
        sfreq: float = 250.0,
        n_channels: int = 16,
        frontal_channels: Optional[Dict[str, int]] = None,
    ):
        self.sfreq = float(sfreq)
        self.n_channels = int(n_channels)
        self.bands = dict(BANDS)
        self.frontal_channels = frontal_channels or dict(_DEFAULT_FRONTAL_CHANNELS)

    def process_window(self, frame: NeuroDataFrame) -> Dict:
        """Process a single ``NeuroDataFrame`` and return band powers, spatial metrics, and quality."""
        if frame.eeg is None:
            raise ValueError("NeuroDataFrame does not contain EEG data")

        data = np.asarray(frame.eeg, dtype=np.float64)
        if data.ndim != 2:
            raise ValueError(f"EEG data must be 2-D (channels, samples), got shape {data.shape}")

        # Pre-processing: remove line noise and limit to the physiological band.
        data = _notch_filter(data, self.sfreq, 50.0)
        data = _notch_filter(data, self.sfreq, 60.0)
        data = _bandpass_filter(data, self.sfreq, 0.5, 100.0)

        # Per-channel band powers.
        band_powers = {
            name: _band_power(data, self.sfreq, low, high)
            for name, (low, high) in self.bands.items()
        }

        # Frontal alpha asymmetry: log(R) - log(L).
        alpha = band_powers["alpha"]
        left_idx = self.frontal_channels.get("F3")
        right_idx = self.frontal_channels.get("F4")
        if (
            left_idx is not None
            and right_idx is not None
            and 0 <= left_idx < len(alpha)
            and 0 <= right_idx < len(alpha)
        ):
            left_power = float(alpha[left_idx])
            right_power = float(alpha[right_idx])
            eps = 1e-12
            frontal_asymmetry = float(np.log(right_power + eps) - np.log(left_power + eps))
        else:
            frontal_asymmetry = 0.0

        # Global field power: average-referenced standard deviation.
        avg_referenced = data - np.mean(data, axis=0, keepdims=True)
        gfp = float(np.std(avg_referenced, axis=0).mean())

        # Signal quality: physiological-band power divided by a non-overlapping
        # high-frequency noise proxy. The pipeline bandpasses 0.5-100 Hz, so
        # energy above 100 Hz is mostly noise/artifact and does not overlap
        # with useful EEG bands such as gamma (30-100 Hz).
        signal_power = _band_power(data, self.sfreq, 0.5, 100.0)
        noise_power = _band_power(data, self.sfreq, 100.0, self.sfreq / 2.0)
        eps = 1e-12
        snr = signal_power / (noise_power + eps)
        per_channel_snr = [float(v) for v in snr]
        overall_snr = float(np.mean(snr))

        return {
            "timestamp": float(frame.timestamp),
            "band_powers": band_powers,
            "spatial": {
                "frontal_asymmetry": frontal_asymmetry,
                "gfp": gfp,
            },
            "raw_quality": {
                "per_channel_snr": per_channel_snr,
                "overall_snr": overall_snr,
            },
        }
