"""BCI hardware abstraction and mock data generator.

This module keeps all BrainFlow imports lazy so that ``laap.bci`` can be
imported without optional hardware drivers installed.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Dict, List, Optional

import numpy as np

from laap.bci.primitives import BCIHardwareType, NeuroDataFrame

logger = logging.getLogger("laap.bci")

# Approximate EEG band ranges used by the mock generator and converters.
_BANDS = {
    "delta": (1.0, 4.0),
    "theta": (4.0, 8.0),
    "alpha": (8.0, 13.0),
    "beta": (13.0, 30.0),
    "gamma": (30.0, 50.0),
}

# Scenario-driven band-power biases for synthetic EEG.
# The chosen amplitudes and noise level keep the per-window SNR above 3.0.
_SCENARIO_BIAS = {
    "focused_coding": {"delta": 0.8, "theta": 0.7, "alpha": 0.3, "beta": 2.0, "gamma": 1.8},
    "stress_debug": {"delta": 0.9, "theta": 1.8, "alpha": 0.4, "beta": 1.5, "gamma": 0.9},
    "creative_flow": {"delta": 0.8, "theta": 0.9, "alpha": 1.5, "beta": 0.9, "gamma": 1.1},
    "meditation": {"delta": 1.0, "theta": 1.1, "alpha": 2.0, "beta": 0.3, "gamma": 0.4},
    "excited_insight": {"delta": 0.7, "theta": 0.6, "alpha": 0.5, "beta": 0.8, "gamma": 2.2},
}

# Mock signal parameters tuned to guarantee SNR > 3.0 across all scenarios.
_MOCK_BASE_AMP = 50.0
_MOCK_NOISE_STD = 0.2


def _band_powers(eeg: np.ndarray, sfreq: float) -> Dict[str, float]:
    """Return mean band powers across channels for a synthetic EEG window."""
    n_samples = eeg.shape[1]
    if n_samples == 0:
        return {name: 0.0 for name in _BANDS}

    freqs = np.fft.rfftfreq(n_samples, d=1.0 / sfreq)
    spectrum = np.abs(np.fft.rfft(eeg, axis=1))
    powers: Dict[str, float] = {}
    for name, (low, high) in _BANDS.items():
        mask = (freqs >= low) & (freqs < high)
        powers[name] = float(np.mean(spectrum[:, mask]))
    return powers


def _convert_to_frame(raw_data: Optional[np.ndarray], hw_type: BCIHardwareType) -> Optional[NeuroDataFrame]:
    """Convert a BrainFlow-style data matrix into a ``NeuroDataFrame``.

    This is a best-effort placeholder: without a live board we fall back to
    reasonable channel counts for each supported hardware family.
    """
    if raw_data is None or raw_data.size == 0:
        return None

    channel_map = {
        BCIHardwareType.OPENBCI_GALEA: 16,
        BCIHardwareType.OPENBCI_CYTON: 8,
        BCIHardwareType.EMOTIV_EPOC_X: 14,
        BCIHardwareType.MUSE_S_ATHENA: 4,
        BCIHardwareType.MOCK_STREAM: 16,
    }
    n_channels = channel_map.get(hw_type, raw_data.shape[0] - 1)

    if raw_data.shape[0] >= n_channels + 1:
        eeg = raw_data[1 : 1 + n_channels, :]
    else:
        eeg = raw_data[:n_channels, :]

    return NeuroDataFrame(timestamp=time.time(), eeg=eeg)


class MockNeuroGenerator:
    """Synthetic multi-channel EEG generator with scenario-based band biases."""

    def __init__(
        self,
        sfreq: float = 250.0,
        n_channels: int = 16,
        scenario: str = "focused_coding",
    ):
        if scenario not in _SCENARIO_BIAS:
            raise ValueError(f"Unknown scenario {scenario!r}; choose from {list(_SCENARIO_BIAS)}")
        self.sfreq = sfreq
        self.n_channels = n_channels
        self.scenario = scenario
        self._rng = np.random.default_rng()

    def generate_window(self, duration_sec: float = 1.0) -> np.ndarray:
        """Generate one realistic EEG window as ``(n_channels, n_samples)``.

        The window is built from a sum of sinusoids (one per EEG band) with
        per-channel random phase and amplitude, scaled by the scenario bias,
        plus a small amount of Gaussian noise. The resulting SNR is kept
        above 3.0 so downstream tests receive clean synthetic data.
        """
        n_samples = int(round(self.sfreq * duration_sec))
        t = np.linspace(0.0, duration_sec, n_samples, endpoint=False)
        eeg = np.zeros((self.n_channels, n_samples), dtype=np.float64)

        bias = _SCENARIO_BIAS[self.scenario]
        for band, (low, high) in _BANDS.items():
            freq = (low + high) / 2.0 + self._rng.uniform(-0.5, 0.5)
            amplitude = _MOCK_BASE_AMP * bias[band] / self.n_channels
            phases = self._rng.uniform(0.0, 2.0 * np.pi, size=self.n_channels)
            amp_factors = self._rng.uniform(0.5, 1.5, size=self.n_channels)
            for ch in range(self.n_channels):
                eeg[ch, :] += (
                    amplitude
                    * amp_factors[ch]
                    * np.sin(2.0 * np.pi * freq * t + phases[ch])
                )

        noise = self._rng.normal(0.0, _MOCK_NOISE_STD, size=(self.n_channels, n_samples))
        eeg += noise
        return eeg


class BCIHardwareInterface:
    """Hardware adapter for BCI devices with a built-in mock stream."""

    def __init__(
        self,
        hw_type: BCIHardwareType,
        config: Dict = None,
        sfreq: float = 250.0,
        n_channels: int = 16,
    ):
        self._hw_type = hw_type
        self._config = config or {}
        self._sfreq = sfreq
        self._n_channels = n_channels

        self._callbacks: List[Callable[[NeuroDataFrame], None]] = []
        self._callbacks_lock = threading.Lock()

        self._running = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._board: Optional[object] = None
        self._pending_marker: Optional[str] = None

        scenario = self._config.get("scenario", "focused_coding")
        self._generator = MockNeuroGenerator(
            sfreq=self._sfreq,
            n_channels=self._n_channels,
            scenario=scenario,
        )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------
    @property
    def hw_type(self) -> BCIHardwareType:
        return self._hw_type

    @property
    def running(self) -> bool:
        return self._running.is_set()

    @property
    def sfreq(self) -> float:
        return self._sfreq

    @property
    def n_channels(self) -> int:
        return self._n_channels

    @property
    def config(self) -> Dict:
        return self._config

    # ------------------------------------------------------------------
    # Callback & marker API
    # ------------------------------------------------------------------
    def register_stream_callback(self, cb: Callable[[NeuroDataFrame], None]) -> None:
        """Register a callback invoked for each incoming ``NeuroDataFrame``."""
        with self._callbacks_lock:
            self._callbacks.append(cb)

    def inject_marker(self, marker: str) -> None:
        """Store a marker to include in the next dispatched frame."""
        with self._callbacks_lock:
            self._pending_marker = marker

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def _init_brainflow_board(self) -> Optional[object]:
        """Lazily initialize a BrainFlow ``BoardShim`` for real hardware.

        If BrainFlow is not installed a warning is logged and ``None`` is
        returned so the interface falls back to mock-stream behaviour.
        """
        try:
            from brainflow import BoardShim, BrainFlowInputParams
        except ImportError:
            logger.warning(
                "BrainFlow is not installed; falling back to MOCK_STREAM behaviour "
                "for %s",
                self._hw_type.value,
            )
            return None

        cfg = self._config
        params = BrainFlowInputParams()
        params.serial_port = cfg.get("serial_port", "")
        params.mac_address = cfg.get("mac_address", "")
        params.ip_address = cfg.get("ip_address", "")
        params.ip_port = int(cfg.get("ip_port", 0))
        params.ip_protocol = int(cfg.get("ip_protocol", 0))
        params.timeout = int(cfg.get("timeout", 0))
        params.other_info = cfg.get("other_info", "")

        board_id_map = {
            BCIHardwareType.OPENBCI_GALEA: 3,
            BCIHardwareType.OPENBCI_CYTON: 0,
            BCIHardwareType.EMOTIV_EPOC_X: 38,
            BCIHardwareType.MUSE_S_ATHENA: 39,
        }
        board_id = cfg.get("board_id", board_id_map.get(self._hw_type, 0))
        return BoardShim(board_id, params)

    def start_stream(self, buffer_size: int = 450000) -> None:
        """Prepare the session and start the acquisition/dispatch thread."""
        if self._running.is_set():
            return

        if self._hw_type != BCIHardwareType.MOCK_STREAM:
            self._board = self._init_brainflow_board()
            if self._board is not None:
                self._board.prepare_session()
                self._board.start_stream(buffer_size)
            else:
                # BrainFlow missing: ensure a mock generator is available for fallback.
                scenario = self._config.get("scenario", "focused_coding")
                self._generator = MockNeuroGenerator(
                    sfreq=self._sfreq,
                    n_channels=self._n_channels,
                    scenario=scenario,
                )

        self._running.set()
        self._thread = threading.Thread(target=self._dispatch_loop, daemon=True)
        self._thread.start()

    def stop_stream(self) -> None:
        """Stop the acquisition thread and release the board."""
        if not self._running.is_set():
            return
        self._running.clear()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

        if self._board is not None:
            try:
                self._board.stop_stream()
            except Exception:  # pragma: no cover - hardware dependent
                logger.exception("Error stopping BrainFlow stream")
            try:
                self._board.release_session()
            except Exception:  # pragma: no cover - hardware dependent
                logger.exception("Error releasing BrainFlow session")
            self._board = None

    # ------------------------------------------------------------------
    # Internal dispatch
    # ------------------------------------------------------------------
    def _dispatch_loop(self) -> None:
        """Pull data from the board or mock generator and dispatch callbacks."""
        if self._hw_type == BCIHardwareType.MOCK_STREAM or self._board is None:
            self._mock_dispatch_loop()
            return

        while self._running.is_set():
            try:
                raw = self._board.get_current_board_data(self._board.get_sample_rate())
            except Exception:  # pragma: no cover - hardware dependent
                logger.exception("Error reading BrainFlow board data")
                time.sleep(0.05)
                continue

            frame = _convert_to_frame(raw, self._hw_type)
            if frame is not None:
                self._dispatch_frame(frame)
            time.sleep(0.05)

    def _mock_dispatch_loop(self) -> None:
        """Generate 1-second windows and dispatch them at 1 Hz."""
        while self._running.is_set():
            window = self._generator.generate_window(duration_sec=1.0)
            self._dispatch_frame_from_array(window)
            time.sleep(1.0)

    def _dispatch_frame_from_array(self, eeg: np.ndarray) -> None:
        """Wrap a raw EEG array in a ``NeuroDataFrame`` and dispatch."""
        with self._callbacks_lock:
            marker = self._pending_marker
            self._pending_marker = None
            callbacks = list(self._callbacks)

        frame = NeuroDataFrame(
            timestamp=time.time(),
            eeg=eeg,
            marker=marker,
        )
        self._dispatch_to_callbacks(frame, callbacks)

    def _dispatch_frame(self, frame: NeuroDataFrame) -> None:
        """Dispatch an already-built frame to registered callbacks."""
        with self._callbacks_lock:
            callbacks = list(self._callbacks)
        self._dispatch_to_callbacks(frame, callbacks)

    def _dispatch_to_callbacks(
        self,
        frame: NeuroDataFrame,
        callbacks: List[Callable[[NeuroDataFrame], None]],
    ) -> None:
        for cb in callbacks:
            try:
                cb(frame)
            except Exception:
                logger.exception("Stream callback failed")
