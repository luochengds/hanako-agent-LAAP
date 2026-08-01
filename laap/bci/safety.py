"""BCI Neuro Bridge — neuro-safety layer.

Implements a gating policy that inspects decoded ``CognitiveState`` objects
before downstream modules act on them.  Decisions are always audited.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import asdict
from datetime import datetime
from typing import Any, Dict, List, Optional

import numpy as np

from laap.bci.primitives import CognitiveState
from laap.config.paths import get_logs_dir


class BCISecurityLayer:
    """Safety gate for neuro-injection decisions.

    The layer evaluates every ``CognitiveState`` through a sequence of gates
    and returns a decision dictionary.  Every scan is appended as a JSON line
    to an audit log.
    """

    _DEFAULT_AUDIT_LOG = str(get_logs_dir() / "bci_audit.log")
    _HISTORY_SIZE = 5
    _ANOMALY_Z = 2.5

    def __init__(self, audit_log_path: Optional[str] = None):
        self.audit_log_path = audit_log_path or self._DEFAULT_AUDIT_LOG
        self._history: List[CognitiveState] = []

    def scan_neuro_injection(self, cog_state: CognitiveState) -> Dict[str, Any]:
        """Evaluate *cog_state* against all safety gates."""
        # Gate 1 — Signal quality.
        signal_quality = cog_state.signal_quality or {}
        overall_snr = signal_quality.get("overall_snr")
        try:
            snr_value = float(overall_snr) if overall_snr is not None else 0.0
        except (TypeError, ValueError):
            snr_value = 0.0

        if snr_value < 3.0:
            result = {
                "action": "block",
                "reason": "poor_signal_quality",
                "attenuate": 0.0,
            }
            self._audit_log(cog_state, result["action"], result["reason"])
            self._remember(cog_state)
            return result

        # Gate 2 — State anomaly.
        if self._detect_state_anomaly(cog_state, self._history):
            result = {
                "action": "warn",
                "reason": "state_anomaly_detected",
                "attenuate": 0.5,
            }
            self._audit_log(cog_state, result["action"], result["reason"])
            self._remember(cog_state)
            return result

        # Gate 3 — Autonomy override (placeholder heuristic).
        emotion = cog_state.emotion_vad or {}
        valence = emotion.get("valence", 0.0)
        arousal = emotion.get("arousal", 0.0)

        if (
            cog_state.attention_focus is None
            or not str(cog_state.attention_focus).strip()
            or (isinstance(valence, float) and math.isnan(valence))
            or (isinstance(arousal, float) and math.isnan(arousal))
        ):
            result = {
                "action": "block",
                "reason": "autonomy_override",
                "attenuate": 0.0,
            }
            self._audit_log(cog_state, result["action"], result["reason"])
            self._remember(cog_state)
            return result

        # Gate 4 — Extreme emotion.
        try:
            valence_f = float(valence)
            arousal_f = float(arousal)
        except (TypeError, ValueError):
            valence_f = 0.0
            arousal_f = 0.0

        if abs(valence_f) > 0.95 or arousal_f > 0.95:
            result = {
                "action": "warn",
                "reason": "extreme_emotional_state",
                "attenuate": 0.5,
            }
            self._audit_log(cog_state, result["action"], result["reason"])
            self._remember(cog_state)
            return result

        # Gate 5 — Audit and allow.
        result = {"action": "allow", "reason": "ok", "attenuate": 1.0}
        self._audit_log(cog_state, result["action"], result["reason"])
        self._remember(cog_state)
        return result

    def _detect_state_anomaly(
        self, cog_state: CognitiveState, history: List[CognitiveState]
    ) -> bool:
        """Return True if *cog_state* deviates from the recent rolling mean."""
        if len(history) < 2:
            return False

        def _features(state: CognitiveState):
            emotion = state.emotion_vad or {}
            return [
                float(emotion.get("valence", 0.0)),
                float(emotion.get("arousal", 0.0)),
                float(state.cognitive_load),
            ]

        past = np.array([_features(s) for s in history], dtype=np.float64)
        current = np.array(_features(cog_state), dtype=np.float64)

        mean = past.mean(axis=0)
        std = past.std(axis=0)
        diff = np.abs(current - mean)

        # Guard against zero std: any non-zero deviation from a constant
        # history is treated as anomalous once we have enough samples.
        threshold = self._ANOMALY_Z * std
        threshold[threshold == 0] = 0.0

        return bool(np.any(diff > threshold))

    def _audit_log(self, cog_state: CognitiveState, action: str, reason: str) -> None:
        """Append a JSON audit record for this scan."""
        record = {
            "timestamp": datetime.now().isoformat(),
            "action": action,
            "reason": reason,
            "state": _json_safe(asdict(cog_state)),
        }

        log_dir = os.path.dirname(self.audit_log_path)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)

        with open(self.audit_log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _remember(self, cog_state: CognitiveState) -> None:
        """Store *cog_state* in rolling history."""
        self._history.append(cog_state)
        if len(self._history) > self._HISTORY_SIZE:
            self._history.pop(0)


def _json_safe(value: Any) -> Any:
    """Recursively make a value JSON-serialisable."""
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (np.floating, np.integer)):
        return float(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, float) and math.isinf(value):
        return None
    return value
