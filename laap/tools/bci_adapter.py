"""LAAP — BCI mock stream adapter for native state-delta integration."""
from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

from laap.orchestration.primitives import AetherMessage, MessageType


@dataclass
class BCIMockStream:
    """Deterministic mock NeuroFrame generator."""

    seed: int = 42

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)

    def next_frame(self) -> Dict[str, Any]:
        """Return a synthetic NeuroFrame dict."""
        return {
            "attention": round(self._rng.random(), 4),
            "cognitive_load": round(self._rng.random(), 4),
            "emotion_vad": [
                round(self._rng.random(), 4),
                round(self._rng.random(), 4),
                round(self._rng.random(), 4),
            ],
            "timestamp": time.time(),
        }


class BCIAdapterTool:
    """Expose mock BCI frames as orchestration STATE_DELTA messages."""

    def __init__(self, stream: Optional[BCIMockStream] = None) -> None:
        self.stream = stream or BCIMockStream()

    def next_frame(self) -> Dict[str, Any]:
        """Pull the next frame from the underlying stream."""
        return self.stream.next_frame()

    @staticmethod
    def to_state_delta(frame: Dict[str, Any]) -> AetherMessage:
        """Convert a NeuroFrame dict into a STATE_DELTA payload."""
        return AetherMessage(
            msg_type=MessageType.STATE_DELTA,
            payload={"bci": frame},
        )
