"""BCI Neuro Bridge — primitive types and event constants.

This module intentionally avoids any top-level imports of hardware drivers
(e.g. BrainFlow). Such imports must remain lazy inside methods so the package
can be imported and used without physical BCI hardware or optional dependencies.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

import numpy as np

logger = logging.getLogger("laap.bci")

# BCI event-type constants used by the pipeline, decoder and feedback layers.
EVENT_COGNITIVE_STATE = "cognitive_state"
EVENT_SIGNAL_QUALITY = "signal_quality"
EVENT_MARKER = "marker"
EVENT_CALIBRATION_SAMPLE = "calibration_sample"
EVENT_FEEDBACK = "feedback"
EVENT_HARDWARE_ERROR = "hardware_error"
EVENT_PIPELINE_START = "pipeline_start"
EVENT_PIPELINE_STOP = "pipeline_stop"


class BCIHardwareType(Enum):
    """Supported BCI hardware streams."""

    OPENBCI_GALEA = "openbci_galea"
    OPENBCI_CYTON = "openbci_cyton"
    EMOTIV_EPOC_X = "emotiv_epoc_x"
    MUSE_S_ATHENA = "muse_s_athena"
    MOCK_STREAM = "mock_stream"


@dataclass
class NeuroDataFrame:
    """A single multimodal neuro-observation.

    Fields that are not hardware-specific use ``Optional`` so mock pipelines can
    leave sensors empty without breaking downstream consumers.
    """

    timestamp: float
    eeg: Optional[np.ndarray] = None
    emg: Optional[np.ndarray] = None
    eda: Optional[np.ndarray] = None
    ppg: Optional[np.ndarray] = None
    eye_gaze: Optional[Dict[str, Any]] = None
    fnirs: Optional[np.ndarray] = None
    marker: Optional[str] = None


@dataclass
class CognitiveState:
    """Decoded cognitive state emitted by the BCI pipeline."""

    attention_focus: str
    cognitive_load: float
    emotion_vad: Dict[str, float] = field(default_factory=lambda: {
        "valence": 0.0,
        "arousal": 0.0,
        "dominance": 0.0,
    })
    motor_intent: Optional[str] = None
    signal_quality: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = 0.0
