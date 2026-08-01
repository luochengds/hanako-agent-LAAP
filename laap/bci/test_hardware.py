"""Unit tests for ``laap.bci.hardware``."""

import threading
import time

import numpy as np
import pytest

from laap.bci.hardware import BCIHardwareInterface, MockNeuroGenerator, _BANDS
from laap.bci.primitives import BCIHardwareType, NeuroDataFrame


def _band_powers(eeg: np.ndarray, sfreq: float) -> dict:
    n_samples = eeg.shape[1]
    freqs = np.fft.rfftfreq(n_samples, d=1.0 / sfreq)
    spectrum = np.abs(np.fft.rfft(eeg, axis=1))
    powers = {}
    for name, (low, high) in _BANDS.items():
        mask = (freqs >= low) & (freqs < high)
        powers[name] = float(np.mean(spectrum[:, mask]))
    return powers


def test_mock_generator_window_shape():
    gen = MockNeuroGenerator(sfreq=250.0, n_channels=16)
    window = gen.generate_window(duration_sec=1.0)

    assert isinstance(window, np.ndarray)
    assert window.shape == (16, 250)
    assert window.dtype == np.float64


def test_mock_stream_callback_receives_frame_with_timestamp():
    received = []
    ready = threading.Event()

    def callback(frame: NeuroDataFrame) -> None:
        received.append(frame)
        ready.set()

    iface = BCIHardwareInterface(
        BCIHardwareType.MOCK_STREAM,
        sfreq=250.0,
        n_channels=16,
    )
    iface.register_stream_callback(callback)

    iface.start_stream()
    assert iface.running

    assert ready.wait(timeout=3.0), "Mock stream did not dispatch a frame in time"

    iface.stop_stream()
    assert not iface.running

    assert len(received) >= 1
    for frame in received:
        assert isinstance(frame, NeuroDataFrame)
        assert frame.eeg is not None
        assert frame.eeg.shape == (16, 250)
        assert frame.timestamp > 0
        assert frame.timestamp <= time.time()


def test_scenario_profiles_produce_different_band_power_signatures():
    scenarios = [
        "focused_coding",
        "stress_debug",
        "creative_flow",
        "meditation",
        "excited_insight",
    ]
    powers = {}
    for scenario in scenarios:
        gen = MockNeuroGenerator(n_channels=16, sfreq=250.0, scenario=scenario)
        window = gen.generate_window(duration_sec=1.0)
        powers[scenario] = _band_powers(window, 250.0)

    # Scenario biases should produce separable band-power signatures.
    assert (
        powers["focused_coding"]["beta"] + powers["focused_coding"]["gamma"]
        > powers["meditation"]["beta"] + powers["meditation"]["gamma"]
    )
    assert powers["meditation"]["alpha"] > powers["focused_coding"]["alpha"]
    assert powers["stress_debug"]["theta"] > powers["meditation"]["theta"]
    assert powers["excited_insight"]["gamma"] > powers["creative_flow"]["gamma"]

    signatures = np.array(
        [[powers[s][band] for band in _BANDS] for s in scenarios]
    )
    # At least one band must differ meaningfully across scenarios.
    assert np.std(signatures, axis=0).max() > 0.1


def test_start_stop_stream_lifecycle():
    iface = BCIHardwareInterface(BCIHardwareType.MOCK_STREAM)
    assert not iface.running

    iface.start_stream()
    assert iface.running

    iface.stop_stream()
    assert not iface.running

    # Idempotent stop should not raise.
    iface.stop_stream()
    assert not iface.running


def test_marker_injection_is_carried_in_frame():
    received = []
    ready = threading.Event()

    def callback(frame: NeuroDataFrame) -> None:
        received.append(frame)
        ready.set()

    iface = BCIHardwareInterface(BCIHardwareType.MOCK_STREAM)
    iface.register_stream_callback(callback)
    iface.inject_marker("calibration_start")

    iface.start_stream()
    assert ready.wait(timeout=3.0), "Mock stream did not dispatch a frame in time"
    iface.stop_stream()

    assert any(frame.marker == "calibration_start" for frame in received)
