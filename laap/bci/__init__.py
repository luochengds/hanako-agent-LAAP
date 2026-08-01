"""BCI Neuro Bridge package for LAAP.

This package provides primitives, hardware abstraction, pipeline processing,
decoding, calibration, security and feedback control for non-invasive BCI data.
All heavy/optional dependencies (e.g. BrainFlow) are imported lazily so the
package remains importable without physical hardware.
"""

from laap.bci.primitives import (
    BCIHardwareType,
    CognitiveState,
    NeuroDataFrame,
    EVENT_CALIBRATION_SAMPLE,
    EVENT_COGNITIVE_STATE,
    EVENT_FEEDBACK,
    EVENT_HARDWARE_ERROR,
    EVENT_MARKER,
    EVENT_PIPELINE_START,
    EVENT_PIPELINE_STOP,
    EVENT_SIGNAL_QUALITY,
    logger,
)
from laap.bci.hardware import BCIHardwareInterface, MockNeuroGenerator
from laap.bci.pipeline import RealtimeNeuroPipeline
from laap.bci.decoder import CognitiveStateDecoder
from laap.bci.safety import BCISecurityLayer
from laap.bci.bridge import BCICognitiveBridge
from laap.bci.calibration import BCICalibrationEngine


class NeuroFeedbackController:
    """Controller that maps cognitive state to actionable feedback."""

    def __init__(self):
        self.handlers = []

    def register(self, handler):
        self.handlers.append(handler)

    def dispatch(self, state: CognitiveState):
        for handler in self.handlers:
            handler(state)


__all__ = [
    "BCIHardwareType",
    "NeuroDataFrame",
    "CognitiveState",
    "BCIHardwareInterface",
    "MockNeuroGenerator",
    "RealtimeNeuroPipeline",
    "CognitiveStateDecoder",
    "BCISecurityLayer",
    "BCICalibrationEngine",
    "BCICognitiveBridge",
    "NeuroFeedbackController",
]
